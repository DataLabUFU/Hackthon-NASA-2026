"""Cálculo diário dos eventos.

Cada função devolve uma medida diária por ponto; ``indicador_evento`` a compara com um
limiar e devolve 1.0 (houve), 0.0 (não houve) ou NaN (sem dado).

Regras: as contas são feitas ponto a ponto; janelas de vários dias terminam no dia ``t`` e
só olham para trás; dias sem histórico suficiente ficam NaN (não zero).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _por_ponto(df: pd.DataFrame, coluna: str, func) -> pd.Series:
    """Aplica ``func`` à série de cada ponto separadamente."""
    return df.groupby("PONTO", sort=False)[coluna].transform(func)


# ----------------------------------------------------------------------------- chuva extrema
def chuva_acumulada(df: pd.DataFrame, dias: int = 3) -> pd.Series:
    """Chuva (mm) somada nos últimos ``dias`` dias, incluindo o dia (10/01 = 08 + 09 + 10/01)."""
    return _por_ponto(df, "PRECTOTCORR", lambda s: s.rolling(dias, min_periods=dias).sum())


# ----------------------------------------------------------------- oscilação de temperatura
def queda_temperatura(df: pd.DataFrame, dias: int = 2, absoluto: bool = False) -> pd.Series:
    """``T2M(t−dias) − T2M(t)`` em °C; positivo = esfriou.

    Com ``absoluto=True``, devolve a variação sem sinal (conta também aquecimento brusco).
    """
    q = _por_ponto(df, "T2M", lambda s: s.shift(dias) - s)
    return q.abs() if absoluto else q


def indicador_evento(valores: pd.Series, limiar: float, inclusivo: bool = True) -> pd.Series:
    """1.0 se ``valor >= limiar`` (``>`` se ``inclusivo=False``), 0.0 se não, NaN se ausente."""
    acima = valores >= limiar if inclusivo else valores > limiar
    return acima.astype(float).where(valores.notna())


# ------------------------------------------------------------------- indicador de estiagem
def amplitude_termica(df: pd.DataFrame) -> pd.Series:
    """``T2M_MAX − T2M_MIN`` (°C). Cresce em dias secos e de céu limpo."""
    return df["T2M_MAX"] - df["T2M_MIN"]


def dia_do_ano_365(datas) -> np.ndarray:
    """Dia do ano em calendário de 365 dias (29/02 vira 28/02; 01/03 é sempre o dia 60)."""
    d = pd.DatetimeIndex(datas)
    doy = d.day_of_year.to_numpy()
    return np.where(d.is_leap_year & (doy >= 60), doy - 1, doy)


def climatologia_dtr(df_ref: pd.DataFrame, janela: int = 31) -> pd.DataFrame:
    """Amplitude térmica normal de cada ponto e dia do ano.

    É a média de todos os dias da janela centrada no dia (31 dias por padrão), em todos os
    anos de referência. O ano é circular: dezembro é vizinho de janeiro.
    Devolve ``PONTO, doy, dtr_clim``. Passe só anos de referência.
    """
    if janela % 2 == 0:
        raise ValueError("janela deve ser ímpar (o dia fica no centro)")
    base = pd.DataFrame({
        "PONTO": df_ref["PONTO"].to_numpy(),
        "doy": dia_do_ano_365(df_ref["data"]),
        "dtr": amplitude_termica(df_ref).to_numpy(),
    })
    tab_soma = base.pivot_table(index="PONTO", columns="doy", values="dtr", aggfunc="sum").reindex(columns=range(1, 366))
    tab_cont = base.pivot_table(index="PONTO", columns="doy", values="dtr", aggfunc="count").reindex(index=tab_soma.index, columns=range(1, 366))
    pontos = tab_soma.index.to_list()
    soma, cont = tab_soma.fillna(0.0).to_numpy(), tab_cont.fillna(0).to_numpy()
    meia = janela // 2
    # np.roll "dá a volta" no ano, o que torna a janela circular
    soma_j = sum(np.roll(soma, k, axis=1) for k in range(-meia, meia + 1))
    cont_j = sum(np.roll(cont, k, axis=1) for k in range(-meia, meia + 1))
    with np.errstate(invalid="ignore", divide="ignore"):
        clim = np.where(cont_j > 0, soma_j / cont_j, np.nan)
    return pd.DataFrame({
        "PONTO": np.repeat(pontos, 365),
        "doy": np.tile(np.arange(1, 366), len(pontos)),
        "dtr_clim": clim.ravel(),
    })


def anomalia_dtr(df: pd.DataFrame, clim: pd.DataFrame) -> pd.Series:
    """Amplitude do dia menos a normal daquele dia (°C)."""
    chave = pd.DataFrame({"PONTO": df["PONTO"].to_numpy(), "doy": dia_do_ano_365(df["data"])})
    ref = chave.merge(clim, on=["PONTO", "doy"], how="left")["dtr_clim"].to_numpy()
    return pd.Series(amplitude_termica(df).to_numpy() - ref, index=df.index, name="anomalia_dtr")


def indicador_estiagem(df: pd.DataFrame, clim: pd.DataFrame, n_dias: int = 10,
                       limiar_alta: float | None = None) -> pd.DataFrame:
    """Indicador de tempo seco nos últimos ``n_dias`` dias.

    Colunas: ``anomalia_dtr`` (do dia), ``anomalia_media`` (média da janela) e, se houver
    limiar, ``frac_dias_alta`` (fração de dias com anomalia >= ``limiar_alta``).

    É um sintoma de tempo seco, não uma previsão; por isso não entra em ``p_algum``.
    """
    anom = anomalia_dtr(df, clim)
    tmp = pd.DataFrame({"PONTO": df["PONTO"].to_numpy(), "anom": anom.to_numpy()}, index=df.index)
    out = pd.DataFrame(index=df.index)
    out["anomalia_dtr"] = anom
    out["anomalia_media"] = _por_ponto(tmp, "anom", lambda s: s.rolling(n_dias, min_periods=n_dias).mean())
    if limiar_alta is not None:
        tmp["alta"] = indicador_evento(anom, limiar_alta)
        out["frac_dias_alta"] = _por_ponto(tmp, "alta", lambda s: s.rolling(n_dias, min_periods=n_dias).mean())
    return out
