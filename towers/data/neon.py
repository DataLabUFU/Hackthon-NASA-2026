"""Leitura (e gravação dos caches) no NeonDB, para o app rodar sem os arquivos de ``data/``.

O banco é carregado por ``scripts/carregar_neon.py`` (esquema em ``db/schema.sql``). Aqui:

- ``garantir_arquivos()``: baixa do banco os arquivos pequenos que faltam no disco (ECOCROP, municípios, PTF,
  nomes do GBIF) e os grava nos mesmos caminhos de ``data/``; o resto do código não muda.
- ``zarc_linhas(geocodigos)``: linhas da safra vigente do ZARC por município, no formato de ``zarc.tabua``
  (a tábua inteira não é baixada: o app só consulta um município por vez).
- ``ler_power`` / ``enviar_power`` e ``ler_soilgrids`` / ``enviar_soilgrids``: caches compartilhados entre
  execuções (no Streamlit Cloud o disco é apagado a cada reinício).

Configuração (a primeira que existir): variável ``NEON_URL``; ``st.secrets["neon"]["url"]``; o arquivo
``.streamlit/secrets.toml``. ``RECOMENDADOR_NEON=0`` desliga (os testes desligam). Falhas de rede viram log e
o chamador segue o caminho antigo (arquivo local ou API de origem): o banco nunca derruba a recomendação.
A URL nunca vai para o log.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import tomllib
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Iterable

import polars as pl

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
SECRETS = ROOT / ".streamlit" / "secrets.toml"
TIMEOUT_CONEXAO_S = 10
# arquivos que o código lê do disco (caminho relativo à raiz), guardados na tabela ``arquivos``
ARQUIVOS = (
    "data/raw/ecocrop/EcoCrop_DB.csv",
    "data/raw/ecocrop/Ecocrop_variable_lookup.csv",
    "data/raw/ibge/municipios.csv",
    "data/raw/embrapa/Preditos_triangulo_AD_m2.csv",
    "data/cache/gbif/nomes.parquet",
)
RISCO_POR_COD = {"0": 0, "2": 20, "3": 30, "4": 40, "5": 50}

_envios = ThreadPoolExecutor(max_workers=2, thread_name_prefix="neon-envio")
_lock_arquivos = threading.Lock()


# --- configuração e conexão --------------------------------------------------------------------

@lru_cache(maxsize=1)
def url() -> str | None:
    """URL com pool (``[neon] url``), ou None quando não configurado ou desligado."""
    if os.getenv("RECOMENDADOR_NEON", "1").strip().lower() in ("0", "false", "nao", "não", "off"):
        return None
    if os.getenv("NEON_URL"):
        return os.environ["NEON_URL"]
    if SECRETS.exists():
        try:
            return tomllib.loads(SECRETS.read_text(encoding="utf-8"))["neon"]["url"] or None
        except (KeyError, tomllib.TOMLDecodeError) as e:
            log.warning("Neon: .streamlit/secrets.toml sem [neon] url válido (%s)", type(e).__name__)
            return None
    try:   # Streamlit Cloud: os segredos ficam no painel do app
        import streamlit as st
        return st.secrets["neon"]["url"]
    except Exception:
        return None


def habilitado() -> bool:
    return url() is not None


def conectar():
    import psycopg
    return psycopg.connect(url(), connect_timeout=TIMEOUT_CONEXAO_S, application_name="recomendador")


def _falha(o_que: str, e: Exception) -> None:
    # sem a mensagem completa: erros de conexão do libpq podem citar o host
    log.warning("Neon: falha ao %s (%s: %s)", o_que, type(e).__name__, str(e).split("\n")[0][:120])


# --- arquivos ----------------------------------------------------------------------------------

def garantir_arquivos(caminhos: Iterable[str] = ARQUIVOS, raiz: Path = ROOT) -> list[str]:
    """Baixa do banco os arquivos de ``caminhos`` que faltam em disco. Devolve os que foram gravados."""
    with _lock_arquivos:
        faltam = [c for c in caminhos if not (raiz / c).exists()]
        if not faltam or not habilitado():
            return []
        try:
            with conectar() as con:
                linhas = con.execute("select caminho, conteudo from arquivos where caminho = any(%s)",
                                     (faltam,)).fetchall()
        except Exception as e:
            _falha("baixar arquivos", e)
            return []
        gravados = []
        for caminho, conteudo in linhas:
            destino = raiz / caminho
            destino.parent.mkdir(parents=True, exist_ok=True)
            tmp = destino.with_suffix(destino.suffix + f".{os.getpid()}.tmp")
            tmp.write_bytes(bytes(conteudo))
            os.replace(tmp, destino)
            gravados.append(caminho)
        if gravados:
            log.info("Neon: %d arquivo(s) baixado(s): %s", len(gravados), ", ".join(gravados))
        if ausentes := sorted(set(faltam) - set(gravados)):
            log.warning("Neon: arquivos que não estão no banco: %s", ", ".join(ausentes))
        return gravados


# --- ZARC --------------------------------------------------------------------------------------

def _zarc_vazio() -> pl.DataFrame:
    from .zarc import DECENDIOS
    return pl.DataFrame(schema={
        "geocodigo": pl.String, "UF": pl.String, "municipio": pl.String, "id_cultura": pl.String,
        "irrigado": pl.Boolean, "Cod_Solo": pl.String, "Cod_Ciclo": pl.String, "Portaria": pl.String,
        "SafraIni": pl.Int16, **{d: pl.Int8 for d in DECENDIOS}})


@lru_cache(maxsize=64)
def _zarc_municipios(geocodigos: tuple[str, ...]) -> pl.DataFrame | None:
    from .municipios import UF_POR_CODIGO
    try:
        with conectar() as con:
            linhas = con.execute(
                "select v.geocodigo, m.codigo_uf, m.nome, v.id_cultura, v.irrigado, v.cod_solo, v.cod_ciclo, "
                "p.portaria, p.safra_ini, v.riscos "
                "from zarc_vigente v join zarc_portarias p on p.id = v.portaria_id "
                "left join municipios m on m.codigo_ibge = v.geocodigo::int "
                "where v.geocodigo = any(%s)", (list(geocodigos),)).fetchall()
    except Exception as e:
        _falha("consultar o ZARC", e)
        return None
    vazio = _zarc_vazio()
    if not linhas:
        return vazio
    df = pl.DataFrame(linhas, orient="row", schema=[
        "geocodigo", "codigo_uf", "municipio", "id_cultura", "irrigado", "Cod_Solo", "Cod_Ciclo", "Portaria",
        "SafraIni", "riscos"])
    df = df.with_columns(
        UF=pl.col("codigo_uf").replace_strict(UF_POR_CODIGO, default=None, return_dtype=pl.String),
        geocodigo=pl.col("geocodigo").str.strip_chars(),
        SafraIni=pl.col("SafraIni").cast(pl.Int16),
        **{f"dec{i + 1}": pl.col("riscos").str.slice(i, 1)
           .replace_strict(RISCO_POR_COD, default=None, return_dtype=pl.Int8) for i in range(36)},
    )
    return df.select(vazio.columns)


def zarc_linhas(geocodigos: Iterable[str]) -> pl.DataFrame | None:
    """Linhas vigentes do ZARC (com ``id_cultura`` e ``irrigado``) dos municípios; None se o banco falhar."""
    return _zarc_municipios(tuple(sorted({str(g) for g in geocodigos})))


# --- caches: POWER e SoilGrids -----------------------------------------------------------------

def ler_power(lat_c: float, lon_c: float, padrao: str, destino: Path) -> bool:
    """Grava em ``destino`` o parquet da célula, se estiver no banco (mtime = última atualização)."""
    if not habilitado():
        return False
    try:
        with conectar() as con:
            r = con.execute("select parquet, atualizado_em from power_cache where lat_c = %s and lon_c = %s "
                            "and padrao_horario = %s", (Decimal(f"{lat_c:.3f}"), Decimal(f"{lon_c:.3f}"),
                                                        padrao)).fetchone()
    except Exception as e:
        _falha("ler o cache do POWER", e)
        return False
    if r is None:
        return False
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_suffix(f".{os.getpid()}.{threading.get_ident()}.neon")
    tmp.write_bytes(bytes(r[0]))
    os.replace(tmp, destino)
    os.utime(destino, (r[1].timestamp(), r[1].timestamp()))   # "atualizado hoje" vale a data do banco
    log.info("POWER: cache da célula (%s, %s) lido do Neon", lat_c, lon_c)
    return True


def _enviar_power(lat_c: float, lon_c: float, padrao: str, conteudo: bytes, n: int, ini, fim) -> None:
    try:
        with conectar() as con:
            con.execute(
                "insert into power_cache (lat_c, lon_c, padrao_horario, parquet, n_dias, data_ini, data_fim, "
                "atualizado_em) values (%s, %s, %s, %s, %s, %s, %s, now()) "
                "on conflict (lat_c, lon_c, padrao_horario) do update set parquet = excluded.parquet, "
                "n_dias = excluded.n_dias, data_ini = excluded.data_ini, data_fim = excluded.data_fim, "
                "atualizado_em = now()",
                (Decimal(f"{lat_c:.3f}"), Decimal(f"{lon_c:.3f}"), padrao, conteudo, n, ini, fim))
        log.info("POWER: cache da célula (%s, %s) enviado ao Neon", lat_c, lon_c)
    except Exception as e:
        _falha("gravar o cache do POWER", e)


def enviar_power(lat_c: float, lon_c: float, padrao: str, arquivo: Path, df: pl.DataFrame) -> None:
    """Envia o cache da célula em segundo plano (não atrasa a recomendação)."""
    if habilitado():
        _envios.submit(_enviar_power, lat_c, lon_c, padrao, arquivo.read_bytes(), df.height,
                       df["data"].min(), df["data"].max())


def ler_bloco_soilgrids(lat_n: int, lon_w: int) -> bytes | None:
    """Bloco de 1° da grade do SoilGrids (npz comprimido), None se não existir. Erro de rede → exceção."""
    with conectar() as con:
        r = con.execute("select bloco from soilgrids_grade where lat_n = %s and lon_w = %s",
                        (lat_n, lon_w)).fetchone()
    return None if r is None else bytes(r[0])


def ler_soilgrids(tipo: str, lat: float, lon: float) -> tuple[bool, dict | None]:
    """(achou, dados). ``dados`` vazio ou nulo = já consultado e sem dado válido."""
    if not habilitado():
        return False, None
    try:
        with conectar() as con:
            r = con.execute("select dados from soilgrids_cache where tipo = %s and lat = %s and lon = %s",
                            (tipo, Decimal(f"{lat:.3f}"), Decimal(f"{lon:.3f}"))).fetchone()
    except Exception as e:
        _falha("ler o cache do SoilGrids", e)
        return False, None
    return (False, None) if r is None else (True, r[0] or None)


def _enviar_soilgrids(tipo: str, lat: float, lon: float, dados: dict | None) -> None:
    try:
        with conectar() as con:
            con.execute(
                "insert into soilgrids_cache (tipo, lat, lon, dados, atualizado_em) values (%s, %s, %s, %s, now()) "
                "on conflict (tipo, lat, lon) do update set dados = excluded.dados, atualizado_em = now()",
                (tipo, Decimal(f"{lat:.3f}"), Decimal(f"{lon:.3f}"), json.dumps(dados or {})))
    except Exception as e:
        _falha("gravar o cache do SoilGrids", e)


def enviar_soilgrids(tipo: str, lat: float, lon: float, dados: dict | None) -> None:
    if habilitado():
        _envios.submit(_enviar_soilgrids, tipo, lat, lon, dados)
