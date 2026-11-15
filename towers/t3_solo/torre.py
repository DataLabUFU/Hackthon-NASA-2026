"""Componente 3 da T3: orquestrador.

    avaliar_t3(lat, lon, problemas_solo=(...), analise={...}) → uma linha por cultura

A T3 não depende da data de plantio nem das outras torres. Não pontua a retenção de água do solo
(tarefa da T2), só os requisitos de solo da cultura: pH, textura, drenagem, profundidade,
fertilidade, salinidade e compactação.
"""
from __future__ import annotations

import logging

import polars as pl

from towers.data.culturas import carregar_culturas, culturas_exibiveis

from .aptidao import aptidao_solo
from .perfil import perfil_solo

log = logging.getLogger(__name__)


def avaliar_t3(lat: float, lon: float, problemas_solo: tuple[str, ...] | list[str] = (), analise: dict | None = None,
               culturas: pl.DataFrame | None = None, perfil: dict | None = None,
               incluir_silvicultura: bool = True, colapsar_variantes: bool = True) -> pl.DataFrame:
    """Score da T3 (solo) para todas as culturas exibíveis, ordenado."""
    if culturas is None:
        culturas = culturas_exibiveis(carregar_culturas(), incluir_silvicultura=incluir_silvicultura)
    perfil = perfil or perfil_solo(lat, lon, problemas=problemas_solo, analise=analise)

    res = aptidao_solo(culturas, perfil).join(
        culturas.select("id_cultura", "nome_pt", "uso", "modo", "obrigatoria", "escala_cultivo"), on="id_cultura")
    res = res.with_columns(
        solo_ph=pl.lit(perfil.get("ph")), solo_textura=pl.lit(perfil.get("textura")),
        solo_wrb=pl.lit(perfil.get("wrb")), solo_drenagem=pl.lit(perfil.get("drenagem")),
        solo_profundidade=pl.lit(perfil.get("profundidade")), solo_fertilidade=pl.lit(perfil.get("fertilidade")),
        solo_origem=pl.lit(str(perfil.get("origem"))),
    )
    ordenar = dict(by=["score_t3", "escala_cultivo", "nome_pt"], descending=[True, False, False])
    res = res.sort(**ordenar).with_columns(n_variantes=pl.len().over("nome_pt"))
    if colapsar_variantes:
        res = res.group_by("nome_pt", maintain_order=True).first()
    ordem = ["id_cultura", "nome_pt", "uso", "modo", "score_t3", "fator_limitante_solo", "corrigivel", "alertas_solo",
             "s_ph", "s_textura", "s_drenagem", "s_profundidade", "s_fertilidade", "s_salinidade", "requisitos_sem_dado",
             "solo_ph", "solo_textura", "solo_wrb", "solo_drenagem", "solo_profundidade", "solo_fertilidade",
             "solo_origem", "n_variantes", "obrigatoria", "escala_cultivo"]
    res = res.select(ordem).sort(**ordenar)
    log.info("T3: %d culturas; solo %s, pH %s, textura %s", res.height, perfil.get("wrb"), perfil.get("ph"), perfil.get("textura"))
    return res
