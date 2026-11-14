"""El Niño / La Niña como condicionante da probabilidade.

O ENSO não é um evento: é um estado do oceano Pacífico que pode mudar a chance de chuva
extrema ou de frio no Brasil. A ideia é comparar a probabilidade em todos os anos (``p_clim``)
com a probabilidade só nos anos da mesma fase de agora (``p_enso``).

Em 21 safras sobram poucos anos para cada fase, então ``p_enso`` é muito incerta. Por isso:

- testamos se a diferença entre os anos da fase e os demais é real (Fisher e permutação);
- misturamos as duas: ``p_final = (n·p_enso + k·p_clim) / (n + k)``, em que ``n`` é o número
  de anos da fase. Com poucos anos, ``p_final`` fica perto de ``p_clim``; com muitos, perto de
  ``p_enso``. ``k`` diz quantos anos "vale" a climatologia.

Os dados de clima não trazem as fases do ENSO. Elas vêm de uma tabela externa ``ano → fase``
(índice da NOAA, como o ONI ou o RONI); sem ela, o resultado é ``"nao_calculado"``.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from .probabilidade import probabilidade_bootstrap

FASES = ("El Niño", "La Niña", "Neutro")
NAO_CALCULADO = {"enso": "nao_calculado"}


def ler_tabela_fases(caminho: str | Path, fases_validas=FASES) -> pd.Series:
    """Lê um CSV com colunas ``ano`` e ``fase`` e devolve a série ``ano → fase``.

    ``ano`` é o ano de início da safra (o mesmo ``ano_safra`` dos indicadores).
    """
    tab = pd.read_csv(caminho)
    faltando = {"ano", "fase"} - set(tab.columns)
    if faltando:
        raise ValueError(f"Tabela de fases sem as colunas {sorted(faltando)}")
    return validar_fases(tab.set_index("ano")["fase"], fases_validas)


def validar_fases(fases: pd.Series, fases_validas=FASES) -> pd.Series:
    """Confere anos únicos e nomes de fase conhecidos."""
    if fases.index.duplicated().any():
        raise ValueError("Ano repetido na tabela de fases")
    invalidas = set(fases.dropna().unique()) - set(fases_validas)
    if invalidas:
        raise ValueError(f"Fases desconhecidas: {sorted(invalidas)} (use {list(fases_validas)})")
    return fases.astype(object)


def teste_permutacao(eventos: np.ndarray, na_fase: np.ndarray, repeticoes: int = 10_000,
                     semente: int = 42) -> float:
    """p-valor bilateral para "a frequência na fase difere da frequência fora dela".

    Embaralha quais anos são da fase e vê com que frequência a diferença sorteada é tão
    grande quanto a observada.
    """
    eventos, na_fase = np.asarray(eventos, float), np.asarray(na_fase, bool)
    if na_fase.all() or not na_fase.any():
        return np.nan
    obs = abs(eventos[na_fase].mean() - eventos[~na_fase].mean())
    rng = np.random.default_rng(semente)
    n_fase = int(na_fase.sum())
    maiores = 0
    for _ in range(repeticoes):
        perm = rng.permutation(len(eventos))
        f = np.zeros(len(eventos), bool)
        f[perm[:n_fase]] = True
        maiores += abs(eventos[f].mean() - eventos[~f].mean()) >= obs - 1e-12
    return (maiores + 1) / (repeticoes + 1)


def p_final(p_enso: float, n_anos_fase: int, p_clim: float, k: float) -> float:
    """Mistura ``(n·p_enso + k·p_clim) / (n + k)``; sem anos da fase, devolve ``p_clim``."""
    if n_anos_fase == 0 or np.isnan(p_enso):
        return float(p_clim)
    return float((n_anos_fase * p_enso + k * p_clim) / (n_anos_fase + k))


def probabilidade_enso(indicadores: pd.Series, fases: pd.Series | None, fase_atual: str | None,
                       k: float = 10.0, repeticoes: int = 1000, semente: int = 42, nivel: float = 0.95,
                       repeticoes_permutacao: int = 10_000, fases_validas=FASES) -> dict:
    """Bloco ``enso`` da saída da torre para um ponto e um evento.

    ``indicadores``: série ``ano_safra → 1/0/NaN``. ``fases``: série ``ano → fase`` (ou None).
    Só entram anos com indicador e com fase. Devolve ``p_clim``, ``p_enso`` (com IC),
    ``n_anos``, ``n_anos_fase``, p-valores de Fisher e de permutação e ``p_final``.
    """
    if fases is None or fase_atual is None:
        return dict(NAO_CALCULADO)
    fases = validar_fases(fases, fases_validas)
    if fase_atual not in fases_validas:
        raise ValueError(f"fase_atual={fase_atual!r} desconhecida")

    base = pd.DataFrame({"ev": indicadores, "fase": fases}).dropna()
    ev = base["ev"].to_numpy(float)
    na_fase = (base["fase"] == fase_atual).to_numpy()
    n, n_fase = len(ev), int(na_fase.sum())

    clim = probabilidade_bootstrap(ev, repeticoes, semente, nivel)
    out = {
        "fase_atual": fase_atual, "n_anos": n, "n_anos_fase": n_fase,
        "p_clim": float(clim["p"][0]), "p_clim_ic": (float(clim["ic_inf"][0]), float(clim["ic_sup"][0])),
        "p_enso": np.nan, "p_enso_ic": (np.nan, np.nan), "p_fisher": np.nan, "p_permutacao": np.nan, "k": k,
    }
    if n_fase:
        fa = probabilidade_bootstrap(ev[na_fase], repeticoes, semente, nivel)
        out["p_enso"] = float(fa["p"][0])
        out["p_enso_ic"] = (float(fa["ic_inf"][0]), float(fa["ic_sup"][0]))
    if 0 < n_fase < n:
        # tabela 2x2: linhas = na fase / fora; colunas = com evento / sem evento
        t = [[ev[na_fase].sum(), n_fase - ev[na_fase].sum()],
             [ev[~na_fase].sum(), (n - n_fase) - ev[~na_fase].sum()]]
        out["p_fisher"] = float(stats.fisher_exact(np.array(t, dtype=int))[1])
        out["p_permutacao"] = float(teste_permutacao(ev, na_fase, repeticoes_permutacao, semente))
    out["p_final"] = p_final(out["p_enso"], n_fase, out["p_clim"], k)
    return out
