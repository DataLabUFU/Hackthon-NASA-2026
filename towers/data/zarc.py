"""Tábua de Risco do ZARC (MAPA): download e consulta por município, cultura e decêndio.

Fonte (CC-BY): https://dados.agricultura.gov.br/dataset/tabua-de-risco-zoneamento-agricola-de-risco-climatico
Baixada como parquet em ``data/raw/zarc/tabua_risco_zarc.parquet`` (``baixar_zarc``).

Decêndios do ZARC: 3 por mês (dias 1–10, 11–20, 21–fim), ``dec1`` = 1–10/jan … ``dec36`` = 21–31/dez.
Valores: 20/30/40 = risco de perda ≤ 20/30/40%; 0 = não indicado.

Cuidados com a tábua:
- **Safra vigente por cultura:** os nomes mudaram ao longo do tempo (ex.: "Arroz Irrigado"/"Arroz Sequeiro"
  até 2023 → "Arroz" com o manejo em ``Nome_Outros_Manejos`` em 2026; "Milho" → "Milho 1ª/2ª Safra").
  Vale só a safra mais recente de cada **cultura** (``id_cultura``), não de cada nome.
- **Irrigado:** pelo nome antigo ("... Irrigado") ou pela coluna ``Nome_Outros_Manejos`` = "Irrigado".
- **Dois sistemas de solo:** classes AD 11–16 (IN MAPA nº 1/2022) e os tipos antigos 1/2/3 por textura
  (ainda usados por algumas culturas).
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Iterable

import polars as pl
import requests

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
CAMINHO_PADRAO = ROOT / "data" / "raw" / "zarc" / "tabua_risco_zarc.parquet"
DECENDIOS = [f"dec{i}" for i in range(1, 37)]
CKAN_API = "https://dados.agricultura.gov.br/api/3/action/package_show"
DATASET_ID = "tabua-de-risco-zoneamento-agricola-de-risco-climatico"
USER_AGENT = "towers-zarc/0.1 (python-requests)"
COLUNAS = [
    "Nome_cultura", "SafraIni", "SafraFin", "Cod_Cultura", "Cod_Ciclo", "Cod_Solo", "geocodigo", "UF", "municipio",
    "Cod_Clima", "Nome_Clima", "Cod_Outros_Manejos", "Nome_Outros_Manejos", "Portaria", *DECENDIOS,
]

# Nome_cultura do ZARC → id_cultura do catálogo (towers.data.culturas).
ZARC_PARA_CULTURA = {
    "Algodão Herbáceo": "algodao-herbaceo",
    "Amendoim": "amendoim",
    "Arroz": "arroz", "Arroz Irrigado": "arroz", "Arroz Sequeiro": "arroz",
    "Aveia": "aveia-branca", "Aveia Irrigada": "aveia-branca", "Aveia Sequeiro": "aveia-branca",
    "Canola": "canola",
    "Cevada Cervejeira": "cevada", "Cevada Grãos": "cevada",
    "Cevada Grãos Irrigada": "cevada", "Cevada Grãos Sequeiro": "cevada",
    "Feijão": "feijao", "Feijão 1ª Safra": "feijao", "Feijão 2ª Safra": "feijao",
    "Feijão Caupi": "feijao-caupi",
    "Girassol": "girassol",
    "Mamona": "mamona", "Mamona Semi-árido Sequeiro": "mamona",
    "Milho": "milho", "Milho 1ª Safra": "milho", "Milho 2ª Safra": "milho",
    "Milho 1ª Safra consorciado com Braquiária": "milho", "Milho 2ª Safra consorciado com Braquiária": "milho",
    "Soja": "soja",
    "Sorgo Forrageiro": "sorgo-forrageiro", "Sorgo Forrageiro 2ª Safra": "sorgo-forrageiro",
    "Sorgo Granífero": "sorgo-granifero", "Sorgo Granífero 2ª Safra": "sorgo-granifero",
    "Trigo": "trigo", "Trigo - Duplo Propósito": "trigo", "Trigo Irrigado": "trigo", "Trigo Sequeiro": "trigo",
}


def decendio(d: date) -> int:
    """Decêndio do ZARC (1–36) de uma data."""
    return (d.month - 1) * 3 + min((d.day - 1) // 10, 2) + 1


def inicio_decendio(dec: int, ano: int) -> date:
    return date(ano, (dec - 1) // 3 + 1, ((dec - 1) % 3) * 10 + 1)


def codigos_solo(solo: dict | None) -> set[str]:
    """Códigos de solo do ZARC compatíveis com o solo do local: classe AD (11–16) pela PTF e o tipo
    antigo 1/2/3 pela argila (< 15% = 1, 15–35% = 2, ≥ 35% = 3)."""
    if not solo:
        return set()
    cods = set()
    if solo.get("classe_ad"):
        partes = solo["classe_ad"].split()
        n = int(partes[1]) if len(partes) > 1 and partes[1].isdigit() else 1
        cods.add(str(10 + max(n, 1)))
    if solo.get("argila") is not None:
        a = solo["argila"]
        cods.add("1" if a < 15 else ("2" if a < 35 else "3"))
    return cods


def solo_local(lat: float, lon: float) -> dict | None:
    """Classe AD (PTF do ZARC sobre a textura do SoilGrids) + argila do local, ou None sem dado."""
    from .ptf_zarc import agua_disponivel
    from .soilgrids import textura
    try:
        t = textura(lat, lon)
    except Exception as e:
        log.warning("SoilGrids indisponível (%s)", e)
        return None
    if not t:
        return None
    return agua_disponivel(t["areia"], t["silte"], t["argila"]) | {"argila": t["argila"]}


# --- download ----------------------------------------------------------------------------------

def baixar_zarc(safras: Iterable[int] | None = None, destino: Path | str = CAMINHO_PADRAO, sessao=None) -> Path:
    """Baixa as safras (padrão: as 3 mais recentes publicadas) e grava um parquet único."""
    sessao = sessao or requests.Session()
    sessao.headers["User-Agent"] = USER_AGENT
    r = sessao.get(CKAN_API, params={"id": DATASET_ID}, timeout=60)
    r.raise_for_status()
    recursos = {}
    for res in r.json()["result"]["resources"]:
        nome = res.get("name", "")
        if res.get("format", "").upper() == "CSV" and "Safra " in nome:
            ini = nome.split("Safra ", 1)[1].split("/")[0].strip()
            if ini.isdigit():
                recursos[int(ini)] = res["url"]
    safras = sorted(safras) if safras else sorted(recursos)[-3:]
    partes = []
    for s in safras:
        log.info("ZARC: baixando safra %d/%d", s, s + 1)
        conteudo = sessao.get(recursos[s], timeout=(30, 600)).content.decode("utf-8-sig")
        partes.append(pl.read_csv(conteudo.encode(), separator=";", columns=COLUNAS, infer_schema_length=0)
                      .with_columns(pl.col("SafraIni", "SafraFin").cast(pl.Int16), pl.col(DECENDIOS).cast(pl.Int8)))
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    pl.concat(partes).write_parquet(destino)
    return destino


# --- consulta ----------------------------------------------------------------------------------

def tabua(geocodigos: Iterable[str] | None = None, caminho: Path | str = CAMINHO_PADRAO,
          incluir_irrigado: bool = False) -> pl.LazyFrame:
    """Linhas da safra vigente de cada cultura, com ``id_cultura`` e ``irrigado``."""
    lf = pl.scan_parquet(caminho)
    nomes = lf.collect_schema().names()
    manejo = pl.col("Nome_Outros_Manejos") if "Nome_Outros_Manejos" in nomes else pl.lit(None, pl.String)
    if geocodigos is not None:
        lf = lf.filter(pl.col("geocodigo").is_in(list(geocodigos)))
    lf = (
        lf.with_columns(
            id_cultura=pl.col("Nome_cultura").replace_strict(ZARC_PARA_CULTURA, default=None),
            irrigado=pl.col("Nome_cultura").str.contains("Irrigad") | (manejo.fill_null("") == "Irrigado"),
        )
        .drop_nulls("id_cultura")
        # arroz irrigado por inundação é outra cultura no catálogo ("Arroz irrigado"); o "Arroz" é o de sequeiro
        .with_columns(id_cultura=pl.when((pl.col("id_cultura") == "arroz") & pl.col("irrigado"))
                      .then(pl.lit("arroz-irrigado")).otherwise(pl.col("id_cultura")))
        .filter(pl.col("SafraIni") == pl.col("SafraIni").max().over("id_cultura"))
    )
    if not incluir_irrigado:
        lf = lf.filter(~pl.col("irrigado"))
    return lf


def indicacao_por_decendio(geocodigos: Iterable[str] | None = None, caminho: Path | str = CAMINHO_PADRAO,
                           incluir_irrigado: bool = False, por_solo: bool = False) -> pl.DataFrame:
    """(geocodigo, id_cultura, dec, [cod_solo], melhor_risco, indicado) na safra vigente de cada cultura.

    Agrega ciclos e manejos (e os solos, se ``por_solo`` = False): ``indicado`` = existe ao menos uma
    combinação indicada; ``melhor_risco`` = menor risco entre as indicadas (20/30/40).
    """
    return (
        tabua(geocodigos, caminho, incluir_irrigado)
        .rename({"Cod_Solo": "cod_solo"})
        .unpivot(index=["geocodigo", "id_cultura", "cod_solo"], on=DECENDIOS, variable_name="dec", value_name="risco")
        .with_columns(dec=pl.col("dec").str.strip_prefix("dec").cast(pl.Int8))
        .group_by("geocodigo", "id_cultura", "dec", *(["cod_solo"] if por_solo else []))
        .agg(
            melhor_risco=pl.col("risco").filter(pl.col("risco") > 0).min(),
            indicado=(pl.col("risco") > 0).any(),
        )
        .sort("geocodigo", "id_cultura", "dec", *(["cod_solo"] if por_solo else []))
        .collect()
    )


def indicadas_para(geocodigo: str, plantios: Iterable[date], caminho: Path | str = CAMINHO_PADRAO) -> set[tuple[str, date]]:
    """Pares (id_cultura, plantio) indicados pelo ZARC no município (para suprimir alertas)."""
    if not Path(caminho).exists():
        return set()
    ind = indicacao_por_decendio([geocodigo], caminho).filter("indicado")
    por_dec: dict[int, list[str]] = {}
    for id_c, dec in ind.select("id_cultura", "dec").iter_rows():
        por_dec.setdefault(dec, []).append(id_c)
    return {(c, p) for p in plantios for c in por_dec.get(decendio(p), [])}
