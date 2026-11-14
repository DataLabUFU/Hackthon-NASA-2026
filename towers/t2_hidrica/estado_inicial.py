"""Componente 3 da T2: umidade do solo no início da simulação, a partir do GWETROOT (NASA POWER).

O GWETROOT é a umidade da zona de raízes como fração da saturação (reanálise MERRA-2). O valor
absoluto não diz quanta água disponível existe: em Londrina ele nunca sai de 0,58–1,00. Por isso
é normalizado pelo histórico da própria célula:

    fração_disponível = (gwet − p02) / (p98 − p02), limitada a [0, 1]

(p02/p98 = percentis 2 e 98 da série da célula). Depleção inicial: Dr0 = (1 − fração) × TAW.
"""
from __future__ import annotations

from datetime import date

import polars as pl

PERCENTIS = (0.02, 0.98)


def _limites(clima: pl.DataFrame) -> tuple[float, float]:
    g = clima["GWETROOT"].drop_nulls()
    return float(g.quantile(PERCENTIS[0])), float(g.quantile(PERCENTIS[1]))


def fracao_disponivel(clima: pl.DataFrame, em: date | None = None) -> tuple[date, float]:
    """(data usada, fração de água disponível) na data ``em`` ou, se None, no último dia publicado."""
    serie = clima.select("data", "GWETROOT").drop_nulls()
    if serie.is_empty():
        raise ValueError("Série sem GWETROOT: inclua o parâmetro na consulta à POWER (PARAMS_T2).")
    lo, hi = _limites(clima)
    linha = serie.filter(pl.col("data") <= em).tail(1) if em else serie.tail(1)
    if linha.is_empty():
        linha = serie.head(1)
    d, g = linha.row(0)
    return d, min(max((g - lo) / (hi - lo), 0.0), 1.0) if hi > lo else 0.5
