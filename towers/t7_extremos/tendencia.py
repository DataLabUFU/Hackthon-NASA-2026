"""Tendência em séries anuais: Mann-Kendall, inclinação de Sen e correção de Holm.

- **Mann-Kendall** (tau de Kendall entre ano e valor): há tendência de subida ou descida?
  Não supõe reta nem distribuição normal; só olha se os valores tendem a crescer com o ano.
- **Inclinação de Sen**: quanto muda por ano. É a mediana das inclinações entre todos os
  pares de anos, por isso um ano muito atípico pesa pouco.
- **Holm**: ao testar várias séries de uma vez, alguma sai "significativa" por acaso. Holm
  ajusta os p-valores para controlar isso.
- **Autocorrelação dos resíduos (lag 1)**: se anos vizinhos são parecidos (ex.: dois anos
  secos seguidos), o teste fica otimista; um valor alto pede cautela.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.multitest import multipletests

from .eventos import chuva_acumulada

MESES_VERANICO = (1, 2, 3)  # janeiro a março
DIA_SECO_MM = 1.0           # dia com menos de 1 mm conta como seco


def maior_sequencia(seco: np.ndarray) -> int:
    """Tamanho da maior sequência de ``True`` seguidos."""
    maior = atual = 0
    for s in seco:
        atual = atual + 1 if s else 0
        maior = max(maior, atual)
    return maior


def series_anuais(df: pd.DataFrame, dias_chuva: int = 3) -> pd.DataFrame:
    """Séries anuais por ponto e ano civil.

    Colunas: ``chuva_total`` (mm), ``chuva_max_3d`` (maior chuva em ``dias_chuva`` dias, mm),
    ``veranico_jan_mar`` (maior sequência de dias com chuva < 1 mm entre janeiro e março),
    ``tmax_media``, ``tmax_max`` e ``tmin_media`` (°C).
    """
    d = df.assign(c3=chuva_acumulada(df, dias_chuva), ano=df["data"].dt.year, mes=df["data"].dt.month)
    g = d.groupby(["PONTO", "ano"])
    out = pd.DataFrame({
        "chuva_total": g["PRECTOTCORR"].sum(),
        "chuva_max_3d": g["c3"].max(),
        "tmax_media": g["T2M_MAX"].mean(),
        "tmax_max": g["T2M_MAX"].max(),
        "tmin_media": g["T2M_MIN"].mean(),
    })
    jm = d[d["mes"].isin(MESES_VERANICO)]
    out["veranico_jan_mar"] = jm.groupby(["PONTO", "ano"])["PRECTOTCORR"].apply(
        lambda s: maior_sequencia((s < DIA_SECO_MM).to_numpy()))
    cols = ["chuva_total", "chuva_max_3d", "veranico_jan_mar", "tmax_media", "tmax_max", "tmin_media"]
    return out[cols].reset_index()


def tendencia(anos, valores, nivel: float = 0.95) -> dict[str, float]:
    """Mann-Kendall + Sen numa série. Devolve tau, p-valor, inclinação (por ano), seu IC,
    variação total no período e autocorrelação lag 1 dos resíduos."""
    x = np.asarray(anos, dtype=float)
    y = np.asarray(valores, dtype=float)
    ok = ~np.isnan(y)
    x, y = x[ok], y[ok]
    tau, p = stats.kendalltau(x, y)
    sen = stats.theilslopes(y, x, alpha=nivel)
    resid = y - (sen.intercept + sen.slope * x)
    ac1 = float(np.corrcoef(resid[:-1], resid[1:])[0, 1]) if len(resid) > 2 else np.nan
    return {
        "n_anos": int(len(y)), "tau": float(tau), "p": float(p),
        "sen_por_ano": float(sen.slope), "sen_ic_inf": float(sen.low_slope), "sen_ic_sup": float(sen.high_slope),
        "variacao_periodo": float(sen.slope * (x.max() - x.min())), "media": float(y.mean()),
        "autocorr_resid": ac1,
    }


def tendencias_por_ponto(series: pd.DataFrame, colunas: list[str] | None = None, alfa: float = 0.05) -> pd.DataFrame:
    """Tendência de cada série em cada ponto, com p ajustado por Holm dentro de cada ponto
    (a família de testes são as séries daquele ponto)."""
    colunas = colunas or [c for c in series.columns if c not in ("PONTO", "ano")]
    linhas = []
    for ponto, sub in series.groupby("PONTO", sort=True):
        res = [{"PONTO": ponto, "serie": c, **tendencia(sub["ano"], sub[c])} for c in colunas]
        rej, p_holm, _, _ = multipletests([r["p"] for r in res], alpha=alfa, method="holm")
        for r, ph, rj in zip(res, p_holm, rej):
            r["p_holm"], r["significativo"] = float(ph), bool(rj)
        linhas.extend(res)
    return pd.DataFrame(linhas)
