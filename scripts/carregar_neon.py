"""Cria as tabelas do db/schema.sql no NeonDB e carrega os dados locais (rodar da raiz do repositório).

    python scripts/carregar_neon.py                # todas as tabelas
    python scripts/carregar_neon.py zarc power     # só algumas

Usa ``url_direta`` de ``.streamlit/secrets.toml`` (DDL e carga em massa não passam bem pelo pooler).
A URL nunca é impressa. Cada tabela é recarregada inteira numa transação (TRUNCATE + COPY): rodar de novo
substitui o conteúdo, não duplica.
Pré-requisito: ``python scripts/preparar_dados.py`` (arquivos em data/raw) e, para os caches, ter rodado o app.
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import re
import sys
import tomllib
from decimal import Decimal
from pathlib import Path

import polars as pl
import psycopg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from towers.data import neon  # noqa: E402
from towers.data.zarc import CAMINHO_PADRAO as CAMINHO_ZARC, DECENDIOS, tabua  # noqa: E402

log = logging.getLogger("carregar_neon")

SECRETS = ROOT / ".streamlit" / "secrets.toml"
SCHEMA = ROOT / "db" / "schema.sql"
RAW = ROOT / "data" / "raw"
CACHE = ROOT / "data" / "cache"
ARQUIVOS = [*neon.ARQUIVOS, "data/raw/zarc/manifest.json"]
# risco do ZARC (%) → caractere em zarc_vigente.riscos
COD_RISCO = {0: "0", 20: "2", 30: "3", 40: "4", 50: "5"}
TEXTO, BPCHAR = 25, 1042   # OIDs de text e char(n)


def url_direta() -> str:
    cfg = tomllib.loads(SECRETS.read_text(encoding="utf-8"))["neon"]
    return cfg["url_direta"]


def sha256(caminho: Path) -> str:
    return hashlib.sha256(caminho.read_bytes()).hexdigest()


def copiar(con: psycopg.Connection, tabela: str, df: pl.DataFrame, origem: str, sha: str | None = None) -> None:
    """TRUNCATE + COPY de ``df`` (colunas com o mesmo nome da tabela) e registro em ``cargas``."""
    colunas = df.columns
    with con.cursor() as cur:
        cur.execute(f"truncate {tabela} cascade")
        tipos = dict(cur.execute(
            "select attname, atttypid::int from pg_attribute where attrelid = %s::regclass and attnum > 0 "
            "and not attisdropped", (tabela,)).fetchall())
        faltando = [c for c in colunas if c not in tipos]
        if faltando:
            raise ValueError(f"{tabela}: colunas sem correspondência no banco: {faltando}")
        lista = ", ".join(f'"{c}"' for c in colunas)
        with cur.copy(f"copy {tabela} ({lista}) from stdin") as cp:
            cp.set_types([TEXTO if tipos[c] == BPCHAR else tipos[c] for c in colunas])   # char(n): enviado como texto
            for linha in df.iter_rows():
                cp.write_row(linha)
        cur.execute(
            "insert into cargas (tabela, linhas, origem, sha256_origem, carregado_em) values (%s, %s, %s, %s, now()) "
            "on conflict (tabela) do update set linhas = excluded.linhas, origem = excluded.origem, "
            "sha256_origem = excluded.sha256_origem, carregado_em = now()",
            (tabela, df.height, origem, sha))
    log.info("%-16s %9d linhas  ← %s", tabela, df.height, origem)


# --- tabelas -----------------------------------------------------------------------------------

def carregar_arquivos(con):
    linhas = []
    for rel in ARQUIVOS:
        p = ROOT / rel
        if p.exists():
            b = p.read_bytes()
            linhas.append({"caminho": rel, "conteudo": b, "bytes": len(b), "sha256": hashlib.sha256(b).hexdigest()})
        else:
            log.warning("arquivo ausente, pulado: %s", rel)
    copiar(con, "arquivos", pl.DataFrame(linhas, schema={"caminho": pl.String, "conteudo": pl.Binary,
                                                         "bytes": pl.Int64, "sha256": pl.String}), "data/raw")


def carregar_municipios(con):
    p = RAW / "ibge" / "municipios.csv"
    df = pl.read_csv(p).with_columns(pl.col("capital").cast(pl.Boolean))
    copiar(con, "municipios", df, str(p.relative_to(ROOT).as_posix()), sha256(p))


def carregar_ptf(con):
    p = RAW / "embrapa" / "Preditos_triangulo_AD_m2.csv"
    df = pl.read_csv(p, separator=";", decimal_comma=True, encoding="utf8-lossy").select(
        areia="AT", silte="SIL", argila="ARG", ad_mm_cm="ADm2_mm_cm", classe_ad="ClasseAD_m2",
        li_ic="LI_ICm2", ls_ic="LS_ICm2")
    copiar(con, "ptf_zarc", df, str(p.relative_to(ROOT).as_posix()), sha256(p))


def carregar_gbif(con):
    p = CACHE / "gbif" / "nomes.parquet"
    copiar(con, "gbif_nomes", pl.read_parquet(p), str(p.relative_to(ROOT).as_posix()), sha256(p))


def carregar_culturas(con):
    from towers.data.culturas import carregar_culturas as catalogo
    df = catalogo()
    copiar(con, "culturas", df.rename({c: c.lower() for c in df.columns}), "towers.data.culturas.carregar_culturas()")


def carregar_zarc(con):
    z = tabua(caminho=CAMINHO_ZARC, incluir_irrigado=True).collect()
    chave = ["geocodigo", "id_cultura", "irrigado", "Cod_Solo", "Cod_Ciclo"]
    port = (z.select("id_cultura", "SafraIni", "Portaria").unique().sort("id_cultura", "Portaria")
            .with_row_index("id", offset=1)
            .select(pl.col("id").cast(pl.Int16), "id_cultura", safra_ini="SafraIni", portaria="Portaria"))
    # climas e outros manejos agregados pelo menor risco indicado; sem indicação → 0; sem valor → nulo
    agreg = z.group_by(chave).agg(
        pl.col("Portaria").first(), pl.col("SafraIni").first(),
        *[pl.when((pl.col(d) > 0).any()).then(pl.col(d).filter(pl.col(d) > 0).min())
          .when(pl.col(d).is_not_null().any()).then(0).alias(d) for d in DECENDIOS],
    )
    vig = agreg.join(port.rename({"safra_ini": "SafraIni", "portaria": "Portaria"}),
                     on=["id_cultura", "SafraIni", "Portaria"]).select(
        "geocodigo", "id_cultura", "irrigado", cod_solo="Cod_Solo", cod_ciclo="Cod_Ciclo", portaria_id="id",
        riscos=pl.concat_str([pl.col(d).replace_strict(COD_RISCO, default=None, return_dtype=pl.String).fill_null("-")
                              for d in DECENDIOS]),
    ).sort("geocodigo", "id_cultura", "irrigado", "cod_solo", "cod_ciclo")
    assert vig.height == agreg.height and vig["riscos"].str.len_chars().eq(36).all()
    sha = sha256(CAMINHO_ZARC)
    copiar(con, "zarc_portarias", port, str(CAMINHO_ZARC.relative_to(ROOT).as_posix()), sha)
    copiar(con, "zarc_vigente", vig, str(CAMINHO_ZARC.relative_to(ROOT).as_posix()), sha)


def carregar_power(con):
    padrao = re.compile(r"power_(\w+?)_([+-]\d+\.\d+)_([+-]\d+\.\d+)\.parquet$")
    linhas = []
    for p in sorted((CACHE / "power").glob("power_*.parquet")):
        m = padrao.match(p.name)
        if not m:
            continue
        datas = pl.read_parquet(p, columns=["data"])["data"]
        linhas.append({"lat_c": Decimal(m[2]), "lon_c": Decimal(m[3]), "padrao_horario": m[1], "parquet": p.read_bytes(),
                       "n_dias": datas.len(), "data_ini": datas.min(), "data_fim": datas.max()})
    copiar(con, "power_cache", pl.DataFrame(linhas, schema_overrides={"lat_c": pl.Object, "lon_c": pl.Object}),
           "data/cache/power")


def carregar_soilgrids(con):
    padrao = re.compile(r"(textura|quimica|classe)_([+-]\d+\.\d+)_([+-]\d+\.\d+)\.json$")
    linhas = []
    for p in sorted((CACHE / "soilgrids").glob("*.json")):
        m = padrao.match(p.name)
        if m:
            dados = json.loads(p.read_text(encoding="utf-8"))
            linhas.append({"tipo": m[1], "lat": Decimal(m[2]), "lon": Decimal(m[3]),
                           "dados": None if dados is None else json.dumps(dados, ensure_ascii=False)})
    copiar(con, "soilgrids_cache", pl.DataFrame(linhas, schema={"tipo": pl.String, "lat": pl.Object,
                                                                "lon": pl.Object, "dados": pl.String}),
           "data/cache/soilgrids")


def carregar_soilgrids_grade(con):
    from towers.data.soilgrids_grade import CAMINHO_GRADE
    if not CAMINHO_GRADE.exists():
        log.warning("grade do SoilGrids ausente: rode scripts/preparar_soilgrids.py; pulado")
        return
    copiar(con, "soilgrids_grade", pl.read_parquet(CAMINHO_GRADE), CAMINHO_GRADE.relative_to(ROOT).as_posix(),
           sha256(CAMINHO_GRADE))


ETAPAS = {"arquivos": carregar_arquivos, "municipios": carregar_municipios, "ptf": carregar_ptf,
          "gbif": carregar_gbif, "culturas": carregar_culturas, "zarc": carregar_zarc,
          "power": carregar_power, "soilgrids": carregar_soilgrids,
          "soilgrids_grade": carregar_soilgrids_grade}


def main(etapas: list[str]) -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    desconhecidas = set(etapas) - set(ETAPAS)
    if desconhecidas:
        raise SystemExit(f"etapas desconhecidas: {sorted(desconhecidas)}; opções: {list(ETAPAS)}")
    with psycopg.connect(url_direta(), connect_timeout=20) as con:
        con.execute(SCHEMA.read_text(encoding="utf-8"))
        con.commit()
        for nome in etapas or list(ETAPAS):
            ETAPAS[nome](con)
            con.commit()
        tam = con.execute("select pg_size_pretty(pg_database_size(current_database()))").fetchone()[0]
        log.info("tamanho do banco: %s", tam)


if __name__ == "__main__":
    main(sys.argv[1:])
