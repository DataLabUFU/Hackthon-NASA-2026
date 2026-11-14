"""Consulta à Tábua de Risco do ZARC (MAPA) por município, cultura e decêndio.

Fonte: https://dados.agricultura.gov.br/dataset/tabua-de-risco-zoneamento-agricola-de-risco-climatico
(baixada como parquet em ``data/raw/zarc/tabua_risco_zarc.parquet``).

Decêndios do ZARC: 3 por mês (dias 1–10, 11–20, 21–fim), ``dec1`` = 1–10/jan … ``dec36`` = 21–31/dez.
Valores: 20/30/40 = risco de perda ≤ 20/30/40%; 0 = não indicado.

Nesta etapa o ZARC serve para:
- suprimir o alerta de fotoperíodo quando a cultura é indicada no município (há cultivares adaptadas);
- calibrar a regra de geada da Torre 1.
A Torre 4 (score do ZARC) usará as mesmas funções.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Iterable

import polars as pl

ROOT = Path(__file__).resolve().parents[2]
CAMINHO_PADRAO = ROOT / "data" / "raw" / "zarc" / "tabua_risco_zarc.parquet"
DECENDIOS = [f"dec{i}" for i in range(1, 37)]

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
NAO_IRRIGADO = ~pl.col("Nome_cultura").str.contains("Irrigad")


def decendio(d: date) -> int:
    """Decêndio do ZARC (1–36) de uma data."""
    return (d.month - 1) * 3 + min((d.day - 1) // 10, 2) + 1


def inicio_decendio(dec: int, ano: int) -> date:
    return date(ano, (dec - 1) // 3 + 1, ((dec - 1) % 3) * 10 + 1)


def indicacao_por_decendio(geocodigos: Iterable[str] | None = None, caminho: Path | str = CAMINHO_PADRAO,
                           incluir_irrigado: bool = False, por_solo: bool = False) -> pl.DataFrame:
    """(geocodigo, id_cultura, dec, [cod_solo], melhor_risco, indicado) na safra mais recente de cada cultura.

    Agrega ciclos e manejos (e os solos, se ``por_solo`` = False): ``indicado`` = existe ao menos uma
    combinação indicada; ``melhor_risco`` = menor risco entre as indicadas (20/30/40).
    """
    lf = pl.scan_parquet(caminho)
    if not incluir_irrigado:
        lf = lf.filter(NAO_IRRIGADO)
    if geocodigos is not None:
        lf = lf.filter(pl.col("geocodigo").is_in(list(geocodigos)))
    lf = lf.filter(pl.col("SafraIni") == pl.col("SafraIni").max().over("Nome_cultura"))
    return (
        lf.with_columns(id_cultura=pl.col("Nome_cultura").replace_strict(ZARC_PARA_CULTURA, default=None))
        .drop_nulls("id_cultura")
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
