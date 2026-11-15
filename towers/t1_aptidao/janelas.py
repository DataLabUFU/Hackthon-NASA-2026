"""Componente 4: janelas climáticas da Torre 1.

Uma janela = (ano histórico × data de plantio × duração). As janelas **não dependem da espécie**:
são calculadas uma vez e depois cruzadas com todas as culturas (componente 5).

Para cada janela:

- ``chuva``: soma da chuva (IMERG) na janela (mm);
- ``chuva_365``: soma nos 365 dias a partir do plantio (para o modo de chuva "anual");
- ``t_mes_frio`` / ``t_mes_quente``: menor e maior média móvel de 30 dias de T2M na janela.
  Os limites do ECOCROP foram calibrados com médias **mensais**; comparar com a temperatura
  diária seria rígido demais. Como o trapézio é monótono de cada lado, o pior mês é sempre
  um dos dois extremos;
- ``tmin_inicial`` / ``tmin_resto``: menor mínima diária (T2M_MIN) na fase inicial (primeiros
  ``dias_fase_inicial`` dias) e no restante da janela. A geada é avaliada por fase: o ECOCROP
  dá a temperatura letal da fase inicial (KTMP) e a da planta estabelecida (KTMPR);
- ``tmin_floracao``: menor mínima na floração/enchimento (fração ``fase_floracao`` do ciclo), onde
  a geada mata o grão/fruto mesmo em culturas resistentes no estádio vegetativo (ex.: trigo);
- ``tmin_abs``: menor mínima diária da janela inteira (diagnóstico);
- ``chuva_pegamento`` / ``t_pegamento``: chuva e temperatura média nos primeiros 90 dias
  (fator de pegamento das perenes).

Janelas com **qualquer dia sem dado** são descartadas: nulo nunca é tratado como "não choveu"
(o IMERG chega com ~2 meses de atraso, então as janelas mais recentes ficam incompletas).
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Iterable

import numpy as np
import polars as pl

from towers.data.power import CHUVA

log = logging.getLogger(__name__)

DIAS_MES = 30
DIAS_PEGAMENTO = 90
DIAS_ANO = 365
DIAS_FASE_INICIAL_PADRAO = 15   # calibrado contra o ZARC (ver calibracao.py)
# Floração/enchimento como fração do ciclo (geada aqui mata grão/fruto); None desliga.
# Desligada por padrão: na calibração contra o ZARC (42 municípios) não melhorou a concordância
# (geral 0,641 → 0,644, ruído) e piorou o trigo (0,549 → 0,489). O erro dos cereais de inverno
# não vem da geada; ver calibracao.py.
FASE_FLORACAO_PADRAO: tuple[float, float] | None = None


def data_no_ano(ano: int, mes: int, dia: int) -> date:
    """Mesmo dia e mês em outro ano (29/02 → 28/02 em anos não bissextos)."""
    try:
        return date(ano, mes, dia)
    except ValueError:
        return date(ano, mes, 28)


def _acumulada(x: np.ndarray) -> np.ndarray:
    return np.concatenate([[0.0], np.cumsum(np.nan_to_num(x))])


def _extremos_mensais(cs: np.ndarray, i0: int, n: int) -> tuple[float, float]:
    """(menor, maior) média móvel de 30 dias em [i0, i0+n). Janelas < 30 dias: a média da janela."""
    if n <= DIAS_MES:
        m = (cs[i0 + n] - cs[i0]) / n
        return m, m
    k = np.arange(i0, i0 + n - DIAS_MES + 1)
    medias = (cs[k + DIAS_MES] - cs[k]) / DIAS_MES
    return float(medias.min()), float(medias.max())


def janelas_climaticas(clima: pl.DataFrame, plantios: Iterable[date], duracoes: Iterable[int],
                       anos: Iterable[int] | None = None, chuva: str = CHUVA,
                       dias_fase_inicial: int = DIAS_FASE_INICIAL_PADRAO,
                       fase_floracao: tuple[float, float] | None = FASE_FLORACAO_PADRAO) -> pl.DataFrame:
    """Tabela de janelas completas. ``plantio`` identifica a data candidata (dia/mês aplicados a cada ano)."""
    clima = clima.sort("data")
    datas = clima["data"].to_list()
    idx = {d: i for i, d in enumerate(datas)}
    n = len(datas)

    t = clima["T2M"].to_numpy().astype(float)
    tmin = clima["T2M_MIN"].to_numpy().astype(float)
    p = clima[chuva].to_numpy().astype(float)
    valido = ~(np.isnan(t) | np.isnan(tmin) | np.isnan(p))
    cs_t, cs_p, cs_ok = _acumulada(t), _acumulada(p), _acumulada(valido.astype(float))

    def completa(i0: int, dur: int) -> bool:
        return i0 + dur <= n and cs_ok[i0 + dur] - cs_ok[i0] == dur

    anos = list(anos) if anos is not None else list(range(datas[0].year, datas[-1].year + 1))
    duracoes = sorted(set(duracoes))
    linhas, descartadas = [], 0
    for plantio in plantios:
        for ano in anos:
            i0 = idx.get(data_no_ano(ano, plantio.month, plantio.day))
            if i0 is None:
                continue
            chuva_365 = cs_p[i0 + DIAS_ANO] - cs_p[i0] if completa(i0, DIAS_ANO) else None
            for dur in duracoes:
                if not completa(i0, dur):
                    descartadas += 1
                    continue
                fim = i0 + dur
                frio, quente = _extremos_mensais(cs_t, i0, dur)
                peg = min(dur, DIAS_PEGAMENTO)
                ini = min(dur, dias_fase_inicial)
                if fase_floracao:
                    f0 = i0 + int(fase_floracao[0] * dur)
                    f1 = max(i0 + int(fase_floracao[1] * dur), f0 + 1)
                    tmin_flor = float(tmin[f0:f1].min())
                else:
                    tmin_flor = None
                linhas.append({
                    "plantio": plantio, "ano": ano, "ciclo_dias": dur,
                    "chuva": cs_p[fim] - cs_p[i0],
                    "chuva_365": chuva_365,
                    "t_mes_frio": frio, "t_mes_quente": quente,
                    "tmin_abs": float(tmin[i0:fim].min()),
                    "tmin_inicial": float(tmin[i0:i0 + ini].min()),
                    "tmin_resto": float(tmin[i0 + ini:fim].min()) if dur > ini else None,
                    "tmin_floracao": tmin_flor,
                    "chuva_pegamento": cs_p[i0 + peg] - cs_p[i0],
                    "t_pegamento": (cs_t[i0 + peg] - cs_t[i0]) / peg,
                })
    if descartadas:
        log.info("T1: %d janelas descartadas por dados incompletos (ex.: IMERG ainda não publicado)", descartadas)

    schema = {"plantio": pl.Date, "ano": pl.Int32, "ciclo_dias": pl.Int64, "chuva": pl.Float64,
              "chuva_365": pl.Float64, "t_mes_frio": pl.Float64, "t_mes_quente": pl.Float64,
              "tmin_abs": pl.Float64, "tmin_inicial": pl.Float64, "tmin_resto": pl.Float64, "tmin_floracao": pl.Float64,
              "chuva_pegamento": pl.Float64, "t_pegamento": pl.Float64}
    return pl.DataFrame(linhas, schema=schema)
