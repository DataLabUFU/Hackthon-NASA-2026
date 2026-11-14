"""Recomendador: roda as seis torres, combina os scores e devolve os setores.

    from towers.combinador import recomendar
    rec = recomendar(lat=-23.3, lon=-51.2, data_plantio=date(2026, 11, 20), cultura_desejada="Soja",
                     ultimo="Soja", penultimo="Milho", objetivo="equilibrado")
    rec.setores["melhores"], rec.desejada, rec.ranking

Cada torre roda de forma independente (mesmo catálogo de culturas). O resultado traz o ranking completo,
os três setores (``top_n`` culturas cada, padrão 3) e a posição da cultura desejada.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import date

import polars as pl

from towers.data.culturas import carregar_culturas, culturas_exibiveis
from towers.data.municipios import municipio_mais_proximo
from towers.data.power import PARAMS_T2, clima_diario
from towers.t1_aptidao import avaliar_t1
from towers.t2_hidrica import avaliar_t2
from towers.t3_solo import avaliar_t3
from towers.t4_zarc import avaliar_t4
from towers.t5_rotacao import avaliar_t5
from towers.t5_rotacao.torre import resolver_cultura
from towers.t6_elegibilidade import avaliar_t6

from .combinador import combinar
from .ordenador import localizar, ordenar, setores
from .pesos import OBJETIVOS

log = logging.getLogger(__name__)

TOP_N_PADRAO = 3


@dataclass
class Recomendacao:
    ranking: pl.DataFrame
    setores: dict[str, pl.DataFrame]
    desejada: dict | None
    objetivo: str
    entrada: dict
    tempos_s: dict[str, float] = field(default_factory=dict)
    candidatos: pl.DataFrame | None = None   # todas as (cultura × data) combinadas, antes de escolher a melhor data


def recomendar(lat: float, lon: float, data_plantio: date, cultura_desejada: str | None = None,
               ultimo: str | None = None, penultimo: str | None = None,
               problemas_solo: tuple[str, ...] | list[str] = (), analise_solo: dict | None = None,
               imovel: dict | None = None, objetivo: str = "equilibrado", irrigado: bool = False,
               somente_financiaveis: bool | None = None, incluir_silvicultura: bool = True,
               top_n: int = TOP_N_PADRAO, geocodigo: str | None = None, tipos_cultura: list[str] | None = None,
               peso_evidencia: float | None = None,
               extras: dict[str, tuple[pl.DataFrame, float]] | None = None) -> Recomendacao:
    """``tipos_cultura``: o que o produtor considera plantar (chaves de ``TIPOS_CULTURA``); None = todos.
    A cultura desejada é sempre avaliada, mesmo fora dos tipos escolhidos."""
    if objetivo not in OBJETIVOS:
        raise ValueError(f"objetivo desconhecido: {objetivo!r} (válidos: {sorted(OBJETIVOS)})")
    tempos: dict[str, float] = {}

    def medir(nome, f, *a, **k):
        t = time.perf_counter()
        r = f(*a, **k)
        tempos[nome] = round(time.perf_counter() - t, 2)
        return r

    catalogo = medir("catalogo", carregar_culturas)
    desejada_nome = resolver_cultura(cultura_desejada, catalogo.filter("exibivel"))["nome_pt"] if cultura_desejada else None
    culturas = culturas_exibiveis(catalogo, incluir_silvicultura=incluir_silvicultura, tipos=tipos_cultura)
    if desejada_nome and desejada_nome not in culturas["nome_pt"].to_list():
        culturas = pl.concat([culturas, catalogo.filter(pl.col("exibivel") & (pl.col("nome_pt") == desejada_nome))])
    geocodigo = geocodigo or municipio_mais_proximo(lat, lon)["geocodigo"]
    clima = medir("clima", clima_diario, lat, lon, params=PARAMS_T2)
    comum = dict(culturas=culturas, colapsar_variantes=False)

    t1 = medir("t1", avaliar_t1, lat, lon, data_plantio, clima=clima, geocodigo=geocodigo, irrigado=irrigado, **comum)
    t2 = medir("t2", avaliar_t2, lat, lon, data_plantio, clima=clima, irrigado=irrigado, **comum)
    t3 = medir("t3", avaliar_t3, lat, lon, problemas_solo=problemas_solo, analise=analise_solo, **comum)
    t4 = medir("t4", avaliar_t4, lat, lon, data_plantio, geocodigo=geocodigo, irrigado=irrigado, **comum)
    t5 = medir("t5", avaliar_t5, ultimo, penultimo, **comum)
    t6 = medir("t6", avaliar_t6, lat, lon, data_plantio, geocodigo=geocodigo, imovel=imovel, irrigado=irrigado, **comum)

    kw = {} if peso_evidencia is None else {"peso_evidencia": peso_evidencia}
    comb = combinar(t1, t2, t3, t4, t5, t6, objetivo=objetivo, somente_financiaveis=somente_financiaveis,
                    extras=extras, **kw)
    ranking = ordenar(comb)
    sets = setores(ranking, top_n=top_n)
    desejada = localizar(ranking, desejada_nome, sets) if desejada_nome else None
    entrada = dict(lat=lat, lon=lon, geocodigo=geocodigo, data_plantio=data_plantio, cultura_desejada=desejada_nome,
                   ultimo=ultimo, penultimo=penultimo, problemas_solo=list(problemas_solo), objetivo=objetivo,
                   irrigado=irrigado, top_n=top_n, tipos_cultura=tipos_cultura)
    log.info("Recomendação: %d culturas ranqueadas; tempos %s", ranking.height, tempos)
    return Recomendacao(ranking, sets, desejada, objetivo, entrada, tempos, comb)
