"""Validação da T2 contra o ZARC, na classe de solo do próprio município.

Critério do ZARC (Teixeira et al., 2021; metodologia do ZARC): risco hídrico = frequência de anos em que
o ISNA (ETa/ETc) da fase crítica fica abaixo de 0,5; o plantio é indicado se esse risco ≤ 40%.
Equivalente na T2: ``indicado_t2 = prob_isna_critico ≤ 0,40`` (estado inicial climatológico, para
não depender da umidade de hoje).

Comparação: mesma amostra de municípios da calibração da T1; para cada um, a linha do ZARC da classe
AD que a T2 estimou (SoilGrids → PTF). Reporta T1, T2 e T1∧T2 (o ZARC também reprova por frio/geada).
"""
from __future__ import annotations

import logging
import re
from datetime import date

import polars as pl

from towers.data.culturas import carregar_culturas, culturas_exibiveis
from towers.data.power import PARAMS_T2, clima_diario
from towers.data.zarc import decendio, indicacao_por_decendio, inicio_decendio
from towers.t1_aptidao.calibracao import CULTURAS_CALIBRACAO

from .torre import avaliar_t2, solo_do_local

log = logging.getLogger(__name__)

LIMIAR_RISCO_ZARC = 0.40


def cod_solo_zarc(classe_ad: str | None) -> str:
    """'AD 4 (1,10)' → '14' (Cod_Solo do ZARC); AD 0/desconhecida → '11' (a classe mais restritiva)."""
    m = re.search(r"AD\s*(\d)", classe_ad or "")
    n = int(m.group(1)) if m else 1
    return str(10 + max(n, 1))


def resultados_t2(municipios: pl.DataFrame, ano: int = 2026, culturas=CULTURAS_CALIBRACAO,
                  raizes_max: tuple[float | None, ...] = (None,)) -> pl.DataFrame:
    cat = culturas_exibiveis(carregar_culturas()).filter(pl.col("id_cultura").is_in(list(culturas)))
    inicio = date(ano, 1, 1)
    deslocamentos = [(inicio_decendio(d, ano) - inicio).days for d in range(1, 37)]
    partes = []
    for i, (geo, nome, uf, lat, lon) in enumerate(municipios.select("geocodigo", "nome", "uf", "lat", "lon").iter_rows(), 1):
        solo = solo_do_local(lat, lon)
        clima = clima_diario(lat, lon, params=PARAMS_T2)
        for raiz in raizes_max:
            r = avaliar_t2(lat, lon, inicio, deslocamentos=deslocamentos, culturas=cat, clima=clima, solo=solo,
                           estado_inicial="climatologico", ano_referencia=ano, colapsar_variantes=False,
                           raiz_max_m=raiz)
            partes.append(r.select("id_cultura", "plantio", "score_t2", "prob_isna_critico", "ad_mm_cm", "classe_ad")
                          .with_columns(geocodigo=pl.lit(geo), uf=pl.lit(uf), cod_solo=pl.lit(cod_solo_zarc(solo.get("classe_ad"))),
                                        raiz_max_m=pl.lit(raiz, dtype=pl.Float64)))
        log.info("validação T2: %d/%d (%s-%s, %s)", i, municipios.height, nome, uf, solo.get("classe_ad"))
    return pl.concat(partes).with_columns(
        dec=pl.col("plantio").map_elements(decendio, return_dtype=pl.Int8),
        indicado_t2=pl.col("prob_isna_critico") <= LIMIAR_RISCO_ZARC,
    )


def comparar(res_t2: pl.DataFrame, res_t1: pl.DataFrame | None = None, por=()) -> pl.DataFrame:
    """Acurácia balanceada de T1, T2 e T1∧T2 contra o ZARC (classe de solo do município)."""
    if "raiz_max_m" in res_t2.columns and res_t2["raiz_max_m"].n_unique() > 1 and "raiz_max_m" not in por:
        por = ("raiz_max_m", *por)
    zarc = indicacao_por_decendio(res_t2["geocodigo"].unique().to_list(), por_solo=True)
    df = res_t2.join(zarc.select("geocodigo", "id_cultura", "dec", "cod_solo", "indicado"),
                     on=["geocodigo", "id_cultura", "dec", "cod_solo"], how="inner")
    preditores = {"T2": pl.col("indicado_t2")}
    if res_t1 is not None:
        df = df.join(res_t1.select("geocodigo", "id_cultura", "dec", "gate_t1"), on=["geocodigo", "id_cultura", "dec"])
        preditores |= {"T1": pl.col("gate_t1"), "T1 e T2": pl.col("gate_t1") & pl.col("indicado_t2")}
    linhas = []
    for nome, pred in preditores.items():
        m = df.with_columns(_p=pred).group_by(list(por) or pl.lit(1).alias("_todos")).agg(
            n=pl.len(),
            sensibilidade=pl.col("_p").filter(pl.col("indicado")).mean(),
            especificidade=(~pl.col("_p")).filter(~pl.col("indicado")).mean(),
        ).with_columns(modelo=pl.lit(nome), acuracia_balanceada=(pl.col("sensibilidade") + pl.col("especificidade")) / 2)
        linhas.append(m)
    return pl.concat(linhas, how="diagonal_relaxed").drop("_todos", strict=False).sort(*por, "modelo")
