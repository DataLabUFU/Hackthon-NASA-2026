"""Municípios brasileiros com coordenadas (geocódigo IBGE → nome, UF, latitude, longitude).

Fonte: compilação pública "municipios-brasileiros" (kelvins, licença MIT), com geocódigo IBGE e
coordenadas da sede municipal: https://github.com/kelvins/municipios-brasileiros
"""
from __future__ import annotations

from pathlib import Path

import polars as pl
import requests

ROOT = Path(__file__).resolve().parents[2]
CAMINHO_PADRAO = ROOT / "data" / "raw" / "ibge" / "municipios.csv"
URL = "https://raw.githubusercontent.com/kelvins/municipios-brasileiros/main/csv/municipios.csv"

UF_POR_CODIGO = {
    11: "RO", 12: "AC", 13: "AM", 14: "RR", 15: "PA", 16: "AP", 17: "TO", 21: "MA", 22: "PI", 23: "CE",
    24: "RN", 25: "PB", 26: "PE", 27: "AL", 28: "SE", 29: "BA", 31: "MG", 32: "ES", 33: "RJ", 35: "SP",
    41: "PR", 42: "SC", 43: "RS", 50: "MS", 51: "MT", 52: "GO", 53: "DF",
}


def municipio_mais_proximo(lat: float, lon: float, municipios: pl.DataFrame | None = None) -> dict:
    """Município cuja sede está mais próxima da coordenada (distância aproximada em km)."""
    mun = municipios if municipios is not None else carregar_municipios()
    import math
    k = math.cos(math.radians(lat))
    r = mun.with_columns(
        dist_km=(((pl.col("lat") - lat) ** 2 + ((pl.col("lon") - lon) * k) ** 2).sqrt() * 111.2)
    ).sort("dist_km").row(0, named=True)
    return r


def carregar_municipios(caminho: Path | str = CAMINHO_PADRAO, baixar: bool = True) -> pl.DataFrame:
    """Colunas: geocodigo (texto, 7 dígitos), nome, uf, lat, lon."""
    caminho = Path(caminho)
    if not caminho.exists():
        if not baixar:
            raise FileNotFoundError(caminho)
        caminho.parent.mkdir(parents=True, exist_ok=True)
        r = requests.get(URL, timeout=60)
        r.raise_for_status()
        caminho.write_bytes(r.content)
    df = pl.read_csv(caminho)
    return df.select(
        geocodigo=pl.col("codigo_ibge").cast(pl.String),
        nome=pl.col("nome"),
        uf=pl.col("codigo_uf").replace_strict(UF_POR_CODIGO, return_dtype=pl.String),
        lat=pl.col("latitude"),
        lon=pl.col("longitude"),
    )
