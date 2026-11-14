"""Cálculo diário de cada evento.

Ideia geral: para cada ponto e cada dia, calculamos uma medida (por exemplo, a chuva dos
últimos 3 dias) e comparamos com um limiar. O resultado é um indicador diário:

- ``1.0``: o evento aconteceu naquele dia;
- ``0.0``: não aconteceu;
- ``NaN``: não dá para saber (falta histórico ou dado).

Regras usadas em todas as funções:

- As contas são feitas ponto a ponto; uma janela nunca mistura dois pontos.
- Uma janela de vários dias termina no próprio dia ``t`` e só olha para trás
  (``t−2``, ``t−1``, ``t``). Assim, o valor de um dia nunca usa informação do futuro.
- Os primeiros dias da série, que não têm dias anteriores suficientes, ficam ``NaN``
  em vez de zero, para não fingir que "não houve evento".
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _por_ponto(df: pd.DataFrame, coluna: str, func) -> pd.Series:
    """Aplica ``func`` à série de cada ponto separadamente."""
    return df.groupby("PONTO", sort=False)[coluna].transform(func)


# ----------------------------------------------------------------------------- chuva extrema
def chuva_acumulada(df: pd.DataFrame, dias: int = 3) -> pd.Series:
    """Chuva acumulada (mm) nos últimos ``dias`` dias, contando o próprio dia.

    Com ``dias=3``, o valor de 10/01 é a soma da chuva de 08, 09 e 10/01. Somar alguns dias
    captura tanto um temporal de um dia quanto chuvas fortes seguidas, que encharcam o solo.
    """
    return _por_ponto(df, "PRECTOTCORR", lambda s: s.rolling(dias, min_periods=dias).sum())


# ----------------------------------------------------------------- oscilação de temperatura
def queda_temperatura(df: pd.DataFrame, dias: int = 2, absoluto: bool = False) -> pd.Series:
    """Queda da temperatura média (°C) em ``dias`` dias: ``T2M(t−dias) − T2M(t)``.

    Valor positivo = esfriou. Ex.: 24 °C em 08/01 e 19 °C em 10/01 dão queda de 5 °C em 10/01.
    Com ``absoluto=True``, devolve o tamanho da variação sem sinal, para contar também
    aquecimentos bruscos.
    """
    q = _por_ponto(df, "T2M", lambda s: s.shift(dias) - s)
    return q.abs() if absoluto else q


def indicador_evento(valores: pd.Series, limiar: float, inclusivo: bool = True) -> pd.Series:
    """Transforma uma medida diária em "houve evento?" (1.0, 0.0 ou NaN).

    Com ``inclusivo=True`` o evento é ``valor >= limiar``; com ``False``, ``valor > limiar``.
    Dias sem medida continuam ``NaN``.
    """
    acima = valores >= limiar if inclusivo else valores > limiar
    return acima.astype(float).where(valores.notna())


# ------------------------------------------------------------------- indicador de estiagem
def amplitude_termica(df: pd.DataFrame) -> pd.Series:
    """Amplitude térmica do dia (°C): máxima menos mínima (``T2M_MAX − T2M_MIN``).

    Em dias secos e de céu limpo o sol esquenta mais de dia e o calor escapa mais à noite,
    então a amplitude cresce. Por isso ela serve como sinal de tempo seco.
    """
    return df["T2M_MAX"] - df["T2M_MIN"]


def dia_do_ano_365(datas) -> np.ndarray:
    """Dia do ano num calendário fixo de 365 dias.

    Em ano bissexto, 29/02 é tratado como 28/02 (dia 59) e os dias seguintes voltam uma
    posição. Assim, 01/03 é sempre o dia 60, em qualquer ano.
    """
    d = pd.DatetimeIndex(datas)
    doy = d.day_of_year.to_numpy()
    return np.where(d.is_leap_year & (doy >= 60), doy - 1, doy)


def climatologia_dtr(df_ref: pd.DataFrame, janela: int = 31) -> pd.DataFrame:
    """Amplitude térmica "normal" de cada ponto em cada dia do ano.

    Para o dia 10 de janeiro, por exemplo, é a média da amplitude de todos os dias entre
    26/12 e 25/01 (janela de 31 dias centrada no dia), em todos os anos de referência.
    Usar uma janela, em vez de só o próprio dia, deixa a curva mais estável. O ano é tratado
    como um círculo: o fim de dezembro é vizinho do começo de janeiro.

    ``df_ref`` deve conter só os anos de referência (use ``dados.filtrar_referencia``).
    Devolve as colunas ``PONTO, doy, dtr_clim``.
    """
    if janela % 2 == 0:
        raise ValueError("janela deve ser ímpar (o dia fica no centro)")
    base = pd.DataFrame({
        "PONTO": df_ref["PONTO"].to_numpy(),
        "doy": dia_do_ano_365(df_ref["data"]),
        "dtr": amplitude_termica(df_ref).to_numpy(),
    })
    # soma e contagem por ponto e dia do ano; a média da janela é soma/contagem dos 31 dias
    tab_soma = base.pivot_table(index="PONTO", columns="doy", values="dtr", aggfunc="sum").reindex(columns=range(1, 366))
    tab_cont = base.pivot_table(index="PONTO", columns="doy", values="dtr", aggfunc="count").reindex(index=tab_soma.index, columns=range(1, 366))
    pontos = tab_soma.index.to_list()
    soma, cont = tab_soma.fillna(0.0).to_numpy(), tab_cont.fillna(0).to_numpy()
    meia = janela // 2
    # np.roll desloca as colunas "dando a volta", o que faz a janela circular
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
    """Quanto a amplitude do dia ficou acima (+) ou abaixo (−) do normal daquele dia (°C)."""
    chave = pd.DataFrame({"PONTO": df["PONTO"].to_numpy(), "doy": dia_do_ano_365(df["data"])})
    ref = chave.merge(clim, on=["PONTO", "doy"], how="left")["dtr_clim"].to_numpy()
    return pd.Series(amplitude_termica(df).to_numpy() - ref, index=df.index, name="anomalia_dtr")


def indicador_estiagem(df: pd.DataFrame, clim: pd.DataFrame, n_dias: int = 10,
                       limiar_alta: float | None = None) -> pd.DataFrame:
    """Indicador de condição seca nos últimos ``n_dias`` dias (contando o dia ``t``).

    Devolve:

    - ``anomalia_dtr``: anomalia da amplitude no próprio dia;
    - ``anomalia_media``: média da anomalia nos últimos ``n_dias`` dias;
    - ``frac_dias_alta``: fração desses dias com anomalia ``>= limiar_alta`` (só se o
      limiar for informado).

    Atenção: a amplitude alta é um **sintoma** de que o tempo está seco, não um aviso de
    que vai ficar seco. Por isso o indicador é só informativo e não entra na probabilidade
    combinada de eventos (``p_algum``); a falta de chuva já é tratada pela torre de
    simulação hídrica.
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
