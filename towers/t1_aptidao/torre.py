"""Componente 6: orquestrador da Torre 1 (aptidão climática).

    avaliar_t1(lat, lon, data_plantio) → uma linha por (cultura × data de plantio candidata)

Saída:

| coluna | significado |
|---|---|
| ``score_t1`` | aptidão média ponderada pela recência no melhor ciclo [0, 1] (entra no combinador) |
| ``score_t1_tipico`` | idem, no ciclo típico da espécie (referência realista) |
| ``apt_p20`` | aptidão mínima em 80% dos anos (estabilidade) |
| ``prob_apta`` / ``prob_letal`` | % ponderado de anos aptos (≥ 0,5) / com geada letal |
| ``gate_t1`` | False se ``prob_apta`` < 0,5 (o candidato sai do ranking) |
| ``fator_limitante`` | geada / temperatura / chuva / pegamento |
| ``alerta_foto`` (+ tipo, mensagem, horas) | alerta de fotoperíodo para ESTE plantio |
| ``alerta_ciclo_extremo`` | o melhor ciclo exige cultivar muito precoce/tardia |
| ``indicada_zarc`` | o ZARC indica a cultura no município e decêndio (se ``geocodigo`` for informado) |
| ``n_variantes`` | variantes da mesma cultura (ex.: grupos de arroz) resumidas nesta linha |

Ordenação: aprovadas no gate → score → estabilidade (P20) → culturas curadas/cultivadas em larga escala.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Iterable

import polars as pl

from towers.data.culturas import carregar_culturas, culturas_exibiveis
from towers.data.ecocrop import expandir_ciclos
from towers.data.power import clima_diario
from towers.data.zarc import indicadas_para

from .aptidao import (
    LIMIAR_APTA, MARGEM_GEADA_PADRAO, MEIA_VIDA_PADRAO, MENSAGENS_FOTO,
    agregar_anos, alerta_fotoperiodo, aptidao_por_ano, melhor_ciclo,
)
from .janelas import DIAS_ANO, DIAS_FASE_INICIAL_PADRAO, FASE_FLORACAO_PADRAO, janelas_climaticas

log = logging.getLogger(__name__)

DESLOCAMENTOS_PADRAO = (-30, -20, -10, 0, 10, 20, 30)
LIMIAR_FATOR_GEADA = 0.2   # geada é o fator limitante se mata a cultura em ≥ 20% dos anos (ponderado)

COLUNAS_CULTURA = [
    "id_cultura", "nome_pt", "uso", "modo", "colheita", "obrigatoria", "escala_cultivo",
    "ciclo_conhecido", "chuva_conhecida", "ktmp_origem", "foto_conhecido", "fonte_parametros",
]
COLUNAS_OPCIONAIS = ["tipo_cultura"]


def avaliar_t1(lat: float, lon: float, data_plantio: date,
               deslocamentos: Iterable[int] = DESLOCAMENTOS_PADRAO,
               culturas: pl.DataFrame | None = None, clima: pl.DataFrame | None = None,
               irrigado: bool = False, modo_chuva: str = "ciclo",
               meia_vida: float = MEIA_VIDA_PADRAO, margem_geada: float = MARGEM_GEADA_PADRAO,
               dias_fase_inicial: int = DIAS_FASE_INICIAL_PADRAO,
               fase_floracao: tuple[float, float] | None = FASE_FLORACAO_PADRAO,
               ano_referencia: int | None = None, geocodigo: str | None = None,
               indicadas_zarc: set[tuple[str, date]] | None = None,
               incluir_silvicultura: bool = True, colapsar_variantes: bool = True) -> pl.DataFrame:
    """Score da Torre 1 para todas as culturas exibíveis × datas candidatas, ordenado.

    - ``geocodigo``: município (IBGE). Se informado, o ZARC indica quais culturas têm cultivares
      adaptadas ali (suprime o alerta de fotoperíodo). ``indicadas_zarc`` sobrescreve essa consulta.
    - ``colapsar_variantes``: mantém só a melhor variante de cada cultura por data
      (ex.: arroz índica × javânica); ``n_variantes`` informa quantas foram resumidas.
    """
    if culturas is None:
        culturas = culturas_exibiveis(carregar_culturas(), incluir_silvicultura=incluir_silvicultura)
    if clima is None:
        clima = clima_diario(lat, lon)
    ano_referencia = ano_referencia or date.today().year
    plantios = [data_plantio + timedelta(days=d) for d in deslocamentos]
    if indicadas_zarc is None:
        indicadas_zarc = indicadas_para(geocodigo, plantios) if geocodigo else set()

    # 1) culturas por modo
    safra = expandir_ciclos(culturas, chave="id_cultura")
    implantacao = culturas.filter(pl.col("modo") == "implantacao")
    duracoes = set(safra["ciclo_dias"].unique().to_list()) | {DIAS_ANO}

    # 2) janelas climáticas (uma vez, para todas as culturas)
    janelas = janelas_climaticas(clima, plantios, duracoes, dias_fase_inicial=dias_fase_inicial,
                                 fase_floracao=fase_floracao)
    if janelas.is_empty():
        raise ValueError("Nenhuma janela climática completa: verifique o período da série da POWER.")

    # 3) aptidão por ano → 4) agregação ponderada → 5) melhor ciclo
    apt = aptidao_por_ano(janelas, safra, implantacao.with_columns(ciclo_dias=pl.lit(DIAS_ANO, pl.Int64)),
                          irrigado=irrigado, modo_chuva=modo_chuva, margem_geada=margem_geada)
    agg = agregar_anos(apt, ano_referencia=ano_referencia, meia_vida=meia_vida)
    ciclos = safra.select("id_cultura", "ciclo_dias", "ciclo_tipico", "ciclo_min", "ciclo_max")
    res = melhor_ciclo(agg, ciclos)

    # 6) metadados da cultura, gate, fator limitante
    extras_cult = [c for c in COLUNAS_OPCIONAIS if c in culturas.columns]
    res = res.join(culturas.select(*COLUNAS_CULTURA, *extras_cult, "foto_sensivel", "foto_curto", "foto_neutro", "foto_longo"),
                   on="id_cultura", how="left").with_columns(
        score_t1=pl.col("apt_media"),
        gate_t1=pl.col("prob_apta") >= LIMIAR_APTA,
        ciclo_dias=pl.when(pl.col("modo") == "safra").then(pl.col("ciclo_dias")),
        fator_limitante=(
            pl.when(pl.col("prob_letal") >= LIMIAR_FATOR_GEADA).then(pl.lit("geada"))
            .when((pl.col("s_temp_med") <= pl.col("s_chuva_med")) & (pl.col("s_temp_med") <= pl.col("s_pegamento_med")))
            .then(pl.lit("temperatura"))
            .when(pl.col("s_chuva_med") <= pl.col("s_pegamento_med")).then(pl.lit("chuva"))
            .otherwise(pl.lit("pegamento"))
        ),
        indicada_zarc=pl.struct("id_cultura", "plantio").map_elements(
            lambda r: (r["id_cultura"], r["plantio"]) in indicadas_zarc, return_dtype=pl.Boolean),
    )

    # 7) alerta de fotoperíodo por plantio
    alertas = [
        alerta_fotoperiodo(lat, r["modo"], r["colheita"], r["foto_sensivel"], r["foto_curto"], r["foto_neutro"],
                           r["foto_longo"], r["plantio"], r["ciclo_dias"], indicada_zarc=r["indicada_zarc"])
        for r in res.select("modo", "colheita", "foto_sensivel", "foto_curto", "foto_neutro",
                            "foto_longo", "plantio", "ciclo_dias", "indicada_zarc").iter_rows(named=True)
    ]
    res = res.with_columns(
        alerta_foto=pl.Series([a[0] for a in alertas], dtype=pl.Boolean),
        alerta_foto_tipo=pl.Series([a[1] for a in alertas], dtype=pl.String),
        dia_fase_indutiva_h=pl.Series([a[2] for a in alertas], dtype=pl.Float64).round(2),
    ).with_columns(
        alerta_foto_mensagem=pl.col("alerta_foto_tipo").replace_strict(MENSAGENS_FOTO, default=None),
    ).drop("foto_sensivel", "foto_curto", "foto_neutro", "foto_longo", "apt_media")

    # 8) ordenação e variantes
    ordenar = dict(by=["gate_t1", "score_t1", "apt_p20", "escala_cultivo", "nome_pt", "plantio"],
                   descending=[True, True, True, False, False, False])
    res = res.sort(**ordenar).with_columns(n_variantes=pl.len().over("nome_pt", "plantio"))
    if colapsar_variantes:
        res = res.group_by("nome_pt", "plantio", maintain_order=True).first()

    ordem = [
        "id_cultura", "nome_pt", "uso", "modo", "colheita", "plantio", "ciclo_dias",
        "score_t1", "score_t1_tipico", "apt_p20", "prob_apta", "prob_letal", "gate_t1", "fator_limitante",
        "s_temp_med", "s_chuva_med", "s_pegamento_med",
        "alerta_foto", "alerta_foto_tipo", "alerta_foto_mensagem", "dia_fase_indutiva_h", "alerta_ciclo_extremo",
        "indicada_zarc", "n_variantes", "n_anos", "n_anos_efetivos",
        "obrigatoria", "escala_cultivo", "ciclo_conhecido", "chuva_conhecida", "ktmp_origem", "foto_conhecido",
        "fonte_parametros", *extras_cult,
    ]
    res = res.select(ordem).sort(**ordenar)
    log.info("T1: %d candidatos (%d culturas × %d datas), %d passam no gate",
             res.height, res["nome_pt"].n_unique(), len(plantios), res["gate_t1"].sum())
    return res
