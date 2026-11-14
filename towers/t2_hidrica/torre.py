"""Componentes 5 e 6 da T2: métricas, agregação e orquestrador.

    avaliar_t2(lat, lon, data_plantio) → uma linha por (cultura × data de plantio candidata)

A T2 é independente das outras torres: escolhe o próprio ciclo, busca a própria água disponível do
solo (SoilGrids → PTF do ZARC/Embrapa) e o próprio estado inicial (GWETROOT).

Ciclos avaliados (grade do ECOCROP, restrita para evitar ciclos irreais, ex.: milho de 365 dias):
- cultura com duração típica da FAO-56: ciclos entre 70% e 130% dessa duração;
- demais: o ciclo típico da espécie e os vizinhos na grade.
``score_t2_tipico`` é o score no ciclo de referência (o mais próximo da duração FAO-56 ou o típico).

Estado inicial (``estado_inicial``):
- ``"atual"`` (padrão): umidade de hoje (último GWETROOT); plantios futuros simulam o solo nu até o
  plantio em cada ano análogo;
- ``"climatologico"``: cada ano análogo parte da própria umidade na data de plantio (comparável ao
  ZARC, que não depende do estado atual).

Por ano simulado:
    razao        = ΣETa / ΣETc no ciclo
    queda        = clip(Ky × (1 − razao), 0, 1)                (FAO-33)
    isna_critico = ETa/ETc na fase intermediária                (ISNA, critério do ZARC)
    irrigacao_mm = Σ(ETc − ETa)                                 (lâmina que faltou)
Entre anos, com peso de recência 0,5^(idade/meia_vida) (o mesmo da T1):
    score_t2 = 1 − queda média ponderada
    prob_perda20 = P(queda > 20%);  prob_isna_critico = P(isna_critico < 0,5)
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Iterable

import numpy as np
import polars as pl

from towers.data.culturas import carregar_culturas, culturas_exibiveis
from towers.data.ecocrop import expandir_ciclos
from towers.data.fao56 import curva_kc, parametros_t2
from towers.data.power import CHUVA, PARAMS_T2, clima_diario
from towers.data.ptf_zarc import agua_disponivel
from towers.data.soilgrids import textura
from towers.t1_aptidao.janelas import data_no_ano
from towers.utils.astronomia import dia_do_ano
from towers.utils.et0 import et0_hargreaves, et0_penman_monteith

from .balanco import KC_SOLO_NU, simular
from .estado_inicial import fracao_disponivel

log = logging.getLogger(__name__)

DESLOCAMENTOS_PADRAO = (-30, -20, -10, 0, 10, 20, 30)
MEIA_VIDA_PADRAO = 10.0
LIMIAR_PERDA = 0.20
LIMIAR_ISNA = 0.50
AD_PADRAO = {"ad_mm_cm": 1.10, "classe_ad": "AD 4 (1,10)", "origem": "padrao"}   # classe mais comum
DIAS_ANO = 365
FAIXA_DURACAO_FAO = (0.7, 1.3)
# Teto da profundidade efetiva de raiz (m) no cálculo da água disponível. None = raiz máxima da FAO-56.
# Calibrado contra o ZARC (validacao.py, 42 municípios): T1∧T2 = 0,708 com 0,4 m (= 0,6 m) contra 0,701 sem teto;
# T2 sozinha 0,605 contra 0,589. 0,4 m é também a profundidade efetiva usada pelo próprio ZARC.
RAIZ_MAX_PADRAO: float | None = 0.4


# --- clima com ET0 -----------------------------------------------------------------------------

def adicionar_et0(clima: pl.DataFrame, lat: float) -> pl.DataFrame:
    """ET0 Penman-Monteith onde há todos os insumos; Hargreaves onde falta (ex.: radiação recente)."""
    j = dia_do_ano(clima["data"].to_list())
    cols = {c: clima[c].to_numpy().astype(float) for c in ("T2M_MAX", "T2M_MIN", "RH2M", "WS2M", "ALLSKY_SFC_SW_DWN", "PS")}
    pm = et0_penman_monteith(cols["T2M_MAX"], cols["T2M_MIN"], cols["RH2M"], cols["WS2M"],
                             cols["ALLSKY_SFC_SW_DWN"], lat, j, cols["PS"])
    hg = et0_hargreaves(cols["T2M_MAX"], cols["T2M_MIN"], lat, j)
    usa_pm = ~np.isnan(pm)
    return clima.with_columns(
        ET0=pl.Series(np.where(usa_pm, pm, hg)),
        et0_pm=pl.Series(usa_pm),
    )


# --- solo --------------------------------------------------------------------------------------

def solo_do_local(lat: float, lon: float) -> dict:
    """AD do solo pela PTF do ZARC a partir da textura do SoilGrids (ou o padrão AD4, sinalizado)."""
    try:
        t = textura(lat, lon)
    except Exception as e:  # rede/API: a torre continua com o padrão, sinalizado
        log.warning("T2: SoilGrids indisponível (%s); usando AD padrão", e)
        t = None
    if not t:
        return dict(AD_PADRAO)
    return agua_disponivel(t["areia"], t["silte"], t["argila"]) | {"origem": "soilgrids+ptf_zarc", **t}


# --- simulação ---------------------------------------------------------------------------------

def _janelas_validas(datas: list[date], validos: np.ndarray, inicio_md: date, T: int, anos: Iterable[int]):
    idx = {d: i for i, d in enumerate(datas)}
    cs = np.concatenate([[0], np.cumsum(validos)])
    for ano in anos:
        i0 = idx.get(data_no_ano(ano, inicio_md.month, inicio_md.day))
        if i0 is not None and i0 + T <= len(datas) and cs[i0 + T] - cs[i0] == T:
            yield ano, i0


def simular_candidatos(clima: pl.DataFrame, cand: pl.DataFrame, plantios: list[date], ad_mm_cm: float,
                       data_estado: date, frac_estado: float, frac_por_plantio: dict[date, float],
                       irrigado: bool = False, frac_serie: np.ndarray | None = None) -> pl.DataFrame:
    """Uma linha por (cultura × ciclo × plantio × ano) com eta/etc totais e na fase crítica."""
    clima = clima.sort("data")
    datas = clima["data"].to_list()
    P = clima[CHUVA].to_numpy().astype(float)
    E = clima["ET0"].to_numpy().astype(float)
    validos = (~np.isnan(P) & ~np.isnan(E)).astype(int)
    anos = range(datas[0].year, datas[-1].year + 1)

    linhas = []
    for plantio in plantios:
        # plantio já passou (≤ último GWETROOT): estado observado no próprio dia, sem pré-plantio.
        # plantio futuro: parte do estado de hoje e simula o solo nu até o plantio em cada ano análogo.
        if frac_serie is not None:          # climatológico: cada ano parte da própria umidade
            inicio, pre, frac0 = plantio, 0, None
        elif plantio <= data_estado:
            inicio, pre, frac0 = plantio, 0, frac_por_plantio[plantio]
        else:
            inicio, pre, frac0 = data_estado, (plantio - data_estado).days, frac_estado
        for dur, grupo in cand.group_by("ciclo_dias"):
            dur = int(dur[0])
            T = pre + dur
            janelas = list(_janelas_validas(datas, validos, inicio, T, anos))
            if not janelas:
                continue
            ny, nc = len(janelas), grupo.height
            # clima dos anos análogos: [anos, T] → repetido para cada cultura: [culturas × anos, T]
            Py = np.stack([P[i0:i0 + T] for _, i0 in janelas])
            Ey = np.stack([E[i0:i0 + T] for _, i0 in janelas])
            kcs, crit = [], []
            for r in grupo.iter_rows(named=True):
                kc, (c0, c1) = curva_kc(r["kc_ini"], r["kc_mid"], r["kc_end"],
                                        (r["frac_ini"], r["frac_dev"], r["frac_mid"], r["frac_late"]), dur)
                kcs.append(np.concatenate([np.full(pre, KC_SOLO_NU), kc]))
                crit.append((c0, c1))
            kc_m = np.repeat(np.stack(kcs), ny, axis=0)
            taw = np.repeat(grupo["raiz_m"].to_numpy() * 100 * ad_mm_cm, ny)
            p = np.repeat(grupo["p"].to_numpy(), ny)
            frac_sim = (np.tile(np.array([frac_serie[i0] for _, i0 in janelas]), nc)
                        if frac0 is None else frac0)
            dr0 = (1 - frac_sim) * taw
            res = simular(np.tile(Py, (nc, 1)), np.tile(Ey, (nc, 1)), kc_m, taw, p, dr0, pre,
                          np.repeat(np.array(crit), ny, axis=0))
            if irrigado:  # irrigação plena: sem déficit, mas a lâmina necessária continua informada
                res["eta_irrigado"] = res["etc"]
            linhas.append(pl.DataFrame({
                "id_cultura": np.repeat(grupo["id_cultura"].to_numpy(), ny),
                "ciclo_dias": dur, "plantio": plantio,
                "ano": np.tile([a for a, _ in janelas], nc),
                "ky": np.repeat(grupo["ky"].to_numpy(), ny),
                **{k: v for k, v in res.items()},
            }))
    return pl.concat(linhas) if linhas else pl.DataFrame()


def agregar(sim: pl.DataFrame, ano_referencia: int, meia_vida: float, irrigado: bool = False) -> pl.DataFrame:
    eta = pl.col("eta_irrigado") if irrigado else pl.col("eta")
    w = pl.col("_w")
    tot = w.sum()
    return (
        sim.with_columns(
            razao=(eta / pl.col("etc")).fill_nan(1.0),
            isna_critico=pl.when(pl.col("etc_crit") > 0).then(pl.col("eta_crit") / pl.col("etc_crit")).otherwise(1.0),
            irrigacao_mm=pl.col("etc") - pl.col("eta"),
            _w=pl.lit(0.5) ** ((ano_referencia - pl.col("ano")) / meia_vida),
        )
        .with_columns(queda=(pl.col("ky") * (1 - pl.col("razao"))).clip(0.0, 1.0))
        .group_by("id_cultura", "plantio", "ciclo_dias")
        .agg(
            queda_media=(w * pl.col("queda")).sum() / tot,
            prob_perda20=(w * (pl.col("queda") > LIMIAR_PERDA)).sum() / tot,
            isna_critico_med=(w * pl.col("isna_critico")).sum() / tot,
            prob_isna_critico=(w * (pl.col("isna_critico") < LIMIAR_ISNA)).sum() / tot,
            irrigacao_mm_med=(w * pl.col("irrigacao_mm")).sum() / tot,
            n_anos=pl.len(),
        )
        .with_columns(score_t2=1 - pl.col("queda_media"))
    )


def restringir_ciclos(safra: pl.DataFrame) -> pl.DataFrame:
    """Mantém só ciclos plausíveis e marca o ``ciclo_referencia`` de cada cultura."""
    d = pl.col("duracao_fao")
    safra = safra.with_columns(_pos=pl.col("ciclo_dias").rank("ordinal").over("id_cultura").cast(pl.Int64))
    pos = pl.col("_pos")
    pos_tipico = pos.filter(pl.col("ciclo_tipico")).first().over("id_cultura")
    dist_fao = (pl.col("ciclo_dias") - d).abs()
    df = safra.with_columns(
        ciclo_referencia=pl.when(d.is_not_null())
        .then(dist_fao == dist_fao.min().over("id_cultura"))
        .otherwise(pl.col("ciclo_tipico")),
        _permitido=pl.when(d.is_not_null())
        .then(pl.col("ciclo_dias").is_between(FAIXA_DURACAO_FAO[0] * d, FAIXA_DURACAO_FAO[1] * d))
        .otherwise((pos - pos_tipico).abs() <= 1),
    )
    # empate na distância à duração FAO: fica o menor ciclo como referência
    df = df.with_columns(ciclo_referencia=pl.col("ciclo_referencia") & (
        pl.col("ciclo_dias") == pl.col("ciclo_dias").filter(pl.col("ciclo_referencia")).min().over("id_cultura")))
    return df.filter(pl.col("_permitido") | pl.col("ciclo_referencia")).drop("_permitido", "_pos")


def serie_fracao(clima: pl.DataFrame) -> np.ndarray:
    """Fração de água disponível dia a dia (GWETROOT normalizado pelo histórico local), alinhada a ``clima``."""
    g = clima["GWETROOT"]
    lo, hi = float(g.drop_nulls().quantile(0.02)), float(g.drop_nulls().quantile(0.98))
    return np.clip((g.fill_null(strategy="forward").fill_null(0.5).to_numpy() - lo) / max(hi - lo, 1e-9), 0.0, 1.0)


def avaliar_t2(lat: float, lon: float, data_plantio: date,
               deslocamentos: Iterable[int] = DESLOCAMENTOS_PADRAO,
               culturas: pl.DataFrame | None = None, clima: pl.DataFrame | None = None,
               solo: dict | None = None, irrigado: bool = False, estado_inicial: str = "atual",
               raiz_max_m: float | None = RAIZ_MAX_PADRAO,
               meia_vida: float = MEIA_VIDA_PADRAO, ano_referencia: int | None = None,
               incluir_silvicultura: bool = True, colapsar_variantes: bool = True) -> pl.DataFrame:
    """Score da T2 (água) para todas as culturas exibíveis × datas candidatas, ordenado."""
    if culturas is None:
        culturas = culturas_exibiveis(carregar_culturas(), incluir_silvicultura=incluir_silvicultura)
    if clima is None:
        clima = clima_diario(lat, lon, params=PARAMS_T2)
    solo = solo or solo_do_local(lat, lon)
    ano_referencia = ano_referencia or date.today().year
    plantios = [data_plantio + timedelta(days=d) for d in deslocamentos]

    if estado_inicial not in ("atual", "climatologico"):
        raise ValueError("estado_inicial deve ser 'atual' ou 'climatologico'")
    clima = adicionar_et0(clima.sort("data"), lat)
    data_estado, frac_estado = fracao_disponivel(clima)
    frac_por_plantio = {p: fracao_disponivel(clima, p)[1] for p in plantios if p <= data_estado}
    frac_serie = serie_fracao(clima) if estado_inicial == "climatologico" else None

    # candidatos: ciclos da grade (safra) + 365 dias (perenes), com parâmetros FAO-56
    par = parametros_t2(culturas)
    if raiz_max_m is not None:
        par = par.with_columns(raiz_m=pl.col("raiz_m").clip(upper_bound=raiz_max_m))
    safra = restringir_ciclos(expandir_ciclos(par, chave="id_cultura"))
    perenes = par.filter(pl.col("modo") == "implantacao").with_columns(
        ciclo_dias=pl.lit(DIAS_ANO, pl.Int64), ciclo_tipico=pl.lit(True), ciclo_referencia=pl.lit(True))
    cand = pl.concat([safra, perenes], how="diagonal_relaxed")

    sim = simular_candidatos(clima, cand, plantios, solo["ad_mm_cm"], data_estado, frac_estado,
                             frac_por_plantio, irrigado=irrigado, frac_serie=frac_serie)
    if sim.is_empty():
        raise ValueError("Nenhuma janela completa para a simulação hídrica.")
    agg = agregar(sim, ano_referencia, meia_vida, irrigado=irrigado)

    # melhor ciclo próprio da T2 (empate: ciclo de referência, depois o mais curto) + score no ciclo de referência
    agg = agg.join(cand.select("id_cultura", "ciclo_dias", "ciclo_referencia"), on=["id_cultura", "ciclo_dias"], how="left")
    referencia = agg.filter(pl.col("ciclo_referencia").fill_null(False)).select(
        "id_cultura", "plantio", score_t2_tipico=pl.col("score_t2"))
    melhor = (agg.sort(["score_t2", "ciclo_referencia", "ciclo_dias"], descending=[True, True, False], nulls_last=True)
              .group_by("id_cultura", "plantio", maintain_order=True).first().drop("ciclo_referencia")
              .join(referencia, on=["id_cultura", "plantio"], how="left"))

    res = melhor.join(
        par.select("id_cultura", "nome_pt", "uso", "modo", "colheita", "obrigatoria", "escala_cultivo",
                   "grupo_fao", "parametros_t2_origem"),
        on="id_cultura", how="left",
    ).with_columns(
        ciclo_dias=pl.when(pl.col("modo") == "safra").then(pl.col("ciclo_dias")),
        agua_solo_hoje=pl.lit(round(frac_estado, 3)),
        data_estado_solo=pl.lit(data_estado),
        ad_mm_cm=pl.lit(solo["ad_mm_cm"]),
        classe_ad=pl.lit(solo.get("classe_ad")),
        solo_origem=pl.lit(solo.get("origem", "informado")),
        irrigado=pl.lit(irrigado),
        estado_inicial=pl.lit(estado_inicial),
    )

    ordenar = dict(by=["score_t2", "prob_perda20", "escala_cultivo", "nome_pt", "plantio"],
                   descending=[True, False, False, False, False])
    res = res.sort(**ordenar).with_columns(n_variantes=pl.len().over("nome_pt", "plantio"))
    if colapsar_variantes:
        res = res.group_by("nome_pt", "plantio", maintain_order=True).first()
    ordem = [
        "id_cultura", "nome_pt", "uso", "modo", "colheita", "plantio", "ciclo_dias",
        "score_t2", "score_t2_tipico", "queda_media", "prob_perda20", "isna_critico_med", "prob_isna_critico", "irrigacao_mm_med",
        "agua_solo_hoje", "data_estado_solo", "estado_inicial", "ad_mm_cm", "classe_ad", "solo_origem", "irrigado",
        "grupo_fao", "parametros_t2_origem", "n_variantes", "n_anos", "obrigatoria", "escala_cultivo",
    ]
    res = res.select(ordem).sort(**ordenar)
    log.info("T2: %d candidatos; solo %s (%.2f mm/cm); água no solo hoje (%s) = %.0f%%",
             res.height, solo.get("classe_ad"), solo["ad_mm_cm"], data_estado, 100 * frac_estado)
    return res
