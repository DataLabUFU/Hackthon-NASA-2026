"""Calibração da regra de geada da Torre 1 contra o ZARC.

Parâmetros calibrados: ``margem_geada`` (°C somados à temperatura letal, para compensar a
diferença entre o ar a 2 m numa célula de ~50 km e a folha no talhão) e ``dias_fase_inicial``
(quanto tempo vale o KTMP, mais rigoroso, antes de passar ao KTMPR).

Referência: para cada (município × cultura × decêndio), o ZARC diz se o plantio é indicado em
pelo menos uma combinação de solo/ciclo. Comparamos com o ``gate_t1``.

Métrica principal: **acurácia balanceada** = média de
- sensibilidade: P(T1 aprova | ZARC indica)
- especificidade: P(T1 reprova | ZARC não indica)

Diagnóstico de geada: ``geada_em_indicado`` = P(T1 diz que a geada mata em ≥ 50% dos anos | ZARC indica).
Deve ser baixo: o ZARC não indica plantios que a geada costuma matar.

O ZARC também reprova por falta de água, que é tarefa da T2; por isso a concordância absoluta
não chega a 100%. O que importa é a comparação entre as combinações de parâmetros.
"""
from __future__ import annotations

import logging
from datetime import date
from itertools import product
from typing import Iterable

import polars as pl

from towers.data.culturas import carregar_culturas, culturas_exibiveis
from towers.data.municipios import carregar_municipios
from towers.data.power import clima_diario
from towers.data.zarc import decendio, indicacao_por_decendio, inicio_decendio

from .torre import avaliar_t1

log = logging.getLogger(__name__)

CULTURAS_CALIBRACAO = ("trigo", "aveia-branca", "cevada", "milho", "soja", "feijao")
UFS_PADRAO = ("RS", "SC", "PR", "SP", "MS", "MG", "GO")
MARGENS = (0.0, 1.0, 2.0, 3.0)
FASES = (15, 30, 45)
FLORACOES: tuple[tuple[float, float] | None, ...] = (None,)


def amostrar_municipios(n_por_uf: int = 6, ufs: Iterable[str] = UFS_PADRAO, seed: int = 42,
                        culturas: Iterable[str] = CULTURAS_CALIBRACAO) -> pl.DataFrame:
    """Amostra estratificada por UF entre os municípios que têm ZARC para as culturas de calibração."""
    mun = carregar_municipios().filter(pl.col("uf").is_in(list(ufs)))
    com_zarc = set(indicacao_por_decendio(mun["geocodigo"].to_list())
                   .filter(pl.col("id_cultura").is_in(list(culturas)))["geocodigo"].unique().to_list())
    return (
        mun.filter(pl.col("geocodigo").is_in(list(com_zarc)))
        .group_by("uf", maintain_order=True)
        .map_groups(lambda g: g.sample(min(n_por_uf, g.height), seed=seed))
        .sort("uf", "nome")
    )


def resultados_t1(municipios: pl.DataFrame, margens=MARGENS, fases=FASES, floracoes=FLORACOES, ano: int = 2026,
                  culturas: Iterable[str] = CULTURAS_CALIBRACAO) -> pl.DataFrame:
    """gate_t1 e prob_letal da T1 para cada (município × combinação × cultura × decêndio)."""
    cat = culturas_exibiveis(carregar_culturas()).filter(pl.col("id_cultura").is_in(list(culturas)))
    inicio = date(ano, 1, 1)
    deslocamentos = [(inicio_decendio(d, ano) - inicio).days for d in range(1, 37)]
    partes = []
    for i, (geo, nome, uf, lat, lon) in enumerate(municipios.select("geocodigo", "nome", "uf", "lat", "lon").iter_rows(), 1):
        clima = clima_diario(lat, lon)
        for margem, fase, flor in product(margens, fases, floracoes):
            r = avaliar_t1(lat, lon, inicio, deslocamentos=deslocamentos, culturas=cat, clima=clima,
                           margem_geada=margem, dias_fase_inicial=fase, fase_floracao=flor, ano_referencia=ano,
                           indicadas_zarc=set(), colapsar_variantes=False)
            partes.append(r.select("id_cultura", "plantio", "gate_t1", "prob_letal").with_columns(
                geocodigo=pl.lit(geo), uf=pl.lit(uf), margem_geada=pl.lit(margem), dias_fase_inicial=pl.lit(fase),
                fase_floracao=pl.lit("desligada" if flor is None else f"{flor[0]:.2f}-{flor[1]:.2f}")))
        log.info("calibração: %d/%d municípios (%s-%s)", i, municipios.height, nome, uf)
    return pl.concat(partes).with_columns(
        dec=pl.col("plantio").map_elements(decendio, return_dtype=pl.Int8))


def metricas(res: pl.DataFrame, por: Iterable[str] = ()) -> pl.DataFrame:
    """Concordância com o ZARC por combinação de parâmetros (e, opcionalmente, por cultura/UF)."""
    zarc = indicacao_por_decendio(res["geocodigo"].unique().to_list())
    df = res.join(zarc.select("geocodigo", "id_cultura", "dec", "indicado"),
                  on=["geocodigo", "id_cultura", "dec"], how="inner")
    chaves = ["margem_geada", "dias_fase_inicial", *(["fase_floracao"] if "fase_floracao" in res.columns else []), *por]
    return (
        df.group_by(chaves)
        .agg(
            n=pl.len(),
            sensibilidade=pl.col("gate_t1").filter(pl.col("indicado")).mean(),
            especificidade=(~pl.col("gate_t1")).filter(~pl.col("indicado")).mean(),
            geada_em_indicado=(pl.col("prob_letal") >= 0.5).filter(pl.col("indicado")).mean(),
        )
        .with_columns(acuracia_balanceada=(pl.col("sensibilidade") + pl.col("especificidade")) / 2)
        .sort("acuracia_balanceada", descending=True)
    )
