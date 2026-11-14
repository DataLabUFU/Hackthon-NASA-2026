"""Definições diárias dos eventos (briefing §3). Todas as funções são puras.

Convenções:

- O ``df`` vem de ``dados.ler_dados_unificados`` (ordenado por ponto e data, sem lacunas).
- Toda janela móvel termina no dia ``t`` e só usa dias anteriores ou iguais a ``t``.
- Os primeiros dias de cada ponto, sem histórico suficiente, ficam NaN (não viram zero).
- Indicadores de evento são float: 1.0 (houve), 0.0 (não houve), NaN (sem dado).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _por_ponto(df: pd.DataFrame, coluna: str, func) -> pd.Series:
    """Aplica ``func`` à série de cada ponto separadamente (janelas nunca cruzam pontos)."""
    return df.groupby("PONTO", sort=False)[coluna].transform(func)


# ----------------------------------------------------------------------------- chuva extrema
def chuva_acumulada(df: pd.DataFrame, dias: int = 3) -> pd.Series:
    """Soma móvel da chuva (``PRECTOTCORR``, mm) nos dias ``t−dias+1 … t`` (§3.1)."""
    return _por_ponto(df, "PRECTOTCORR", lambda s: s.rolling(dias, min_periods=dias).sum())


# ----------------------------------------------------------------- oscilação de temperatura
def queda_temperatura(df: pd.DataFrame, dias: int = 2, absoluto: bool = False) -> pd.Series:
    """``T2M(t−dias) − T2M(t)`` em °C (§3.2). Positivo = resfriamento.

    Com ``absoluto=True`` devolve o módulo da variação (inclui aquecimento brusco).
    """
    q = _por_ponto(df, "T2M", lambda s: s.shift(dias) - s)
    return q.abs() if absoluto else q


def indicador_evento(valores: pd.Series, limiar: float, inclusivo: bool = True) -> pd.Series:
    """1.0 se ``valor >= limiar`` (ou ``>`` com ``inclusivo=False``), 0.0 se não, NaN se ausente."""
    acima = valores >= limiar if inclusivo else valores > limiar
    return acima.astype(float).where(valores.notna())


# ------------------------------------------------------------------- indicador de estiagem
def amplitude_termica(df: pd.DataFrame) -> pd.Series:
    """Amplitude térmica diária ``DTR = T2M_MAX − T2M_MIN`` (°C) (§3.3)."""
    return df["T2M_MAX"] - df["T2M_MIN"]


def dia_do_ano_365(datas) -> np.ndarray:
    """Dia do ano num calendário de 365 dias.

    Nos anos bissextos, 29/02 é tratado como 28/02 (dia 59) e os dias seguintes recuam 1,
    para que a mesma data do calendário caia sempre no mesmo dia da climatologia.
    """
    d = pd.DatetimeIndex(datas)
    doy = d.day_of_year.to_numpy()
    return np.where(d.is_leap_year & (doy >= 60), doy - 1, doy)


def climatologia_dtr(df_ref: pd.DataFrame, janela: int = 31) -> pd.DataFrame:
    """Média da amplitude térmica por ponto e dia do ano, suavizada em janela circular.

    ``df_ref`` deve conter só os anos de referência (use ``dados.filtrar_referencia``).
    A suavização é a média de todos os dias que caem na janela centrada de ``janela`` dias,
    tratando o ano como circular (31/12 é vizinho de 01/01). Devolve ``PONTO, doy, dtr_clim``.
    """
    if janela % 2 == 0:
        raise ValueError("janela deve ser ímpar")
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
    """Amplitude térmica do dia menos a climatologia do mesmo ponto e dia do ano."""
    chave = pd.DataFrame({"PONTO": df["PONTO"].to_numpy(), "doy": dia_do_ano_365(df["data"])})
    ref = chave.merge(clim, on=["PONTO", "doy"], how="left")["dtr_clim"].to_numpy()
    return pd.Series(amplitude_termica(df).to_numpy() - ref, index=df.index, name="anomalia_dtr")


def indicador_estiagem(df: pd.DataFrame, clim: pd.DataFrame, n_dias: int = 10,
                       limiar_alta: float | None = None) -> pd.DataFrame:
    """Indicador de condição seca (§3.3). Informativo: NÃO entra em ``p_algum``.

    - ``anomalia_media``: média da anomalia da amplitude térmica nos últimos ``n_dias`` (t inclusive);
    - ``frac_dias_alta``: fração desses dias com anomalia ``>= limiar_alta`` (só se o limiar for dado).

    É um sintoma de tempo seco e claro, não um aviso antecipado (sem poder preditivo no teste
    do briefing).
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
