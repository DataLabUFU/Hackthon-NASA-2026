"""Probabilidade empírica por ano, IC por bootstrap de anos e suavização (briefing §4.3 e §5).

Fluxo:

1. Um indicador diário de evento (1/0/NaN, de ``eventos``) vira um indicador **anual**: houve
   pelo menos um evento naquele ano, naquela unidade (decêndio, mês ou janela de safra)?
2. ``p̂ = (1/n) Σ 1{evento no ano i}`` sobre os ``n`` anos com dado completo.
3. IC: sorteia ``n`` anos com reposição, recalcula ``p̂``, repete ``B`` vezes e usa os
   percentis. Nunca se sorteiam dias, porque os dias de um mesmo ano não são independentes.

``p_algum`` (pelo menos um dos dois eventos) sai direto dos anos: o indicador anual de cada
evento é combinado ano a ano antes de calcular a frequência. Nunca multiplicando probabilidades.
"""
from __future__ import annotations

import zlib

import numpy as np
import pandas as pd


# ------------------------------------------------------------------------ indicadores anuais
def indicador_anual_por_unidade(df: pd.DataFrame, evento: pd.Series, unidade: str = "decendio") -> pd.DataFrame:
    """Indicador anual por ponto, ano civil e unidade (coluna de ``df``, ex.: ``decendio``).

    O evento é atribuído ao dia em que a janela móvel termina. Uma unidade-ano só é válida se
    todos os seus dias tiverem indicador (sem NaN); senão fica NaN e não entra na contagem de
    anos. Ex.: o 1º decêndio de 2000 fica NaN para a chuva de 3 dias, que só começa em 03/01.
    Devolve ``PONTO, YEAR, <unidade>, evento``.
    """
    base = pd.DataFrame({
        "PONTO": df["PONTO"].to_numpy(),
        "YEAR": df["data"].dt.year.to_numpy(),
        unidade: df[unidade].to_numpy(),
        "ev": np.asarray(evento, dtype=float),
    })
    g = base.groupby(["PONTO", "YEAR", unidade], sort=True)["ev"]
    out = g.max().to_frame("evento")
    out.loc[g.count() < g.size(), "evento"] = np.nan
    return out.reset_index()


def indicador_por_safra(df: pd.DataFrame, evento: pd.Series, inicio: tuple[int, int] = (10, 1),
                        fim: tuple[int, int] = (3, 31)) -> pd.DataFrame:
    """Indicador por ponto e safra numa janela do calendário (mês, dia) → (mês, dia).

    A janela pode atravessar o ano (ex.: out–mar); a safra é identificada pelo ano em que começa
    (``ano_safra``). Só valem safras com todos os dias presentes e com indicador: com a
    referência até 2021, a safra 2021/22 (que usa jan–mar de 2022) fica de fora, assim como
    a 1999/2000. Devolve ``PONTO, ano_safra, evento``.
    """
    d = df["data"]
    md = d.dt.month * 100 + d.dt.day
    ini, fi = inicio[0] * 100 + inicio[1], fim[0] * 100 + fim[1]
    cruza = ini > fi
    dentro = ((md >= ini) | (md <= fi)) if cruza else ((md >= ini) & (md <= fi))
    ano_safra = d.dt.year - ((md <= fi) & cruza).astype(int)

    base = pd.DataFrame({
        "PONTO": df["PONTO"].to_numpy(),
        "ano_safra": ano_safra.to_numpy(),
        "ev": np.asarray(evento, dtype=float),
    })[dentro.to_numpy()]
    g = base.groupby(["PONTO", "ano_safra"], sort=True)["ev"]
    out = g.max().to_frame("evento")

    # dias esperados em cada safra (conta 29/02 quando existe)
    anos = out.index.get_level_values("ano_safra")
    comeco = pd.to_datetime({"year": anos, "month": inicio[0], "day": inicio[1]})
    final = pd.to_datetime({"year": anos + int(cruza), "month": fim[0], "day": fim[1]})
    esperados = ((final - comeco).dt.days + 1).to_numpy()
    out.loc[g.count().to_numpy() < esperados, "evento"] = np.nan
    return out.reset_index()


def combinar_algum(*indicadores: pd.Series) -> pd.Series:
    """Pelo menos um evento no ano: máximo ano a ano (OR). NaN se qualquer indicador for NaN."""
    tab = pd.concat(indicadores, axis=1)
    return tab.max(axis=1).where(tab.notna().all(axis=1))


# --------------------------------------------------------------- probabilidade e bootstrap
def suavizar_circular(p: np.ndarray) -> np.ndarray:
    """Média de cada unidade com as duas vizinhas, de forma circular (dec. 1 é vizinho do 36).

    Funciona no último eixo, então aceita um vetor (unidades) ou uma matriz (réplicas × unidades).
    """
    p = np.asarray(p, dtype=float)
    return (np.roll(p, 1, axis=-1) + p + np.roll(p, -1, axis=-1)) / 3.0


def _media_ignorando_nan(x: np.ndarray, eixo: int) -> np.ndarray:
    n = np.sum(~np.isnan(x), axis=eixo)
    soma = np.nansum(x, axis=eixo)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(n > 0, soma / n, np.nan)


def probabilidade_bootstrap(matriz: np.ndarray, repeticoes: int = 1000, semente: int | np.random.SeedSequence = 42,
                            nivel: float = 0.95, suavizar: bool = False) -> dict[str, np.ndarray]:
    """``p̂`` e IC por bootstrap de anos.

    ``matriz``: anos × unidades, com 1/0/NaN (NaN = ano sem dado completo naquela unidade).
    Cada réplica sorteia linhas (anos) com reposição. Com ``suavizar=True`` também devolve
    a versão suavizada (circular entre unidades) e o IC dela, suavizando réplica a réplica.
    """
    m = np.atleast_2d(np.asarray(matriz, dtype=float))
    if m.shape[0] == 1 and np.ndim(matriz) == 1:
        m = m.T  # vetor de anos → uma unidade
    n_anos_total = m.shape[0]
    rng = np.random.default_rng(semente)
    idx = rng.integers(0, n_anos_total, size=(repeticoes, n_anos_total))
    replicas = _media_ignorando_nan(m[idx], eixo=1)  # (réplicas, unidades)

    alfa = (1 - nivel) / 2
    q = [100 * alfa, 100 * (1 - alfa)]
    p = _media_ignorando_nan(m, eixo=0)
    out = {"p": p, "n_anos": np.sum(~np.isnan(m), axis=0)}
    out["ic_inf"], out["ic_sup"] = np.nanpercentile(replicas, q, axis=0)
    if suavizar:
        out["p_suav"] = suavizar_circular(p)
        out["ic_inf_suav"], out["ic_sup_suav"] = np.nanpercentile(suavizar_circular(replicas), q, axis=0)
    return out


def semente_do_ponto(semente: int, ponto: str) -> np.random.SeedSequence:
    """Semente reprodutível e diferente para cada ponto (não depende da ordem dos pontos)."""
    return np.random.SeedSequence([semente, zlib.crc32(ponto.encode("utf-8"))])


def tabela_por_unidade(indicadores: pd.DataFrame, unidade: str = "decendio", repeticoes: int = 1000,
                       semente: int = 42, nivel: float = 0.95, suavizar: bool = True,
                       n_unidades: int | None = 36) -> pd.DataFrame:
    """Tabela de referência ``PONTO × unidade`` a partir de ``indicador_anual_por_unidade``.

    Colunas: ``p_clim``, ``ic_inf``, ``ic_sup``, (``p_clim_suav``, ``ic_inf_suav``,
    ``ic_sup_suav``), ``n_anos`` e ``flag_p_extremo`` (p̂ = 0 ou 1: o IC por bootstrap colapsa
    e não informa a incerteza real).
    """
    linhas = []
    for ponto, sub in indicadores.groupby("PONTO", sort=True):
        mat = sub.pivot(index="YEAR", columns=unidade, values="evento")
        if n_unidades is not None:
            mat = mat.reindex(columns=range(1, n_unidades + 1))
        r = probabilidade_bootstrap(mat.to_numpy(), repeticoes, semente_do_ponto(semente, ponto), nivel, suavizar)
        tab = pd.DataFrame({"PONTO": ponto, unidade: mat.columns.to_numpy(), "p_clim": r["p"],
                            "ic_inf": r["ic_inf"], "ic_sup": r["ic_sup"]})
        if suavizar:
            tab["p_clim_suav"], tab["ic_inf_suav"], tab["ic_sup_suav"] = r["p_suav"], r["ic_inf_suav"], r["ic_sup_suav"]
        tab["n_anos"] = r["n_anos"]
        tab["flag_p_extremo"] = (tab["p_clim"] == 0) | (tab["p_clim"] == 1)
        linhas.append(tab)
    return pd.concat(linhas, ignore_index=True)


def tabela_por_safra(indicadores: pd.DataFrame, repeticoes: int = 1000, semente: int = 42,
                     nivel: float = 0.95) -> pd.DataFrame:
    """Probabilidade por ponto numa janela de safra, a partir de ``indicador_por_safra``."""
    linhas = []
    for ponto, sub in indicadores.groupby("PONTO", sort=True):
        r = probabilidade_bootstrap(sub["evento"].to_numpy(), repeticoes, semente_do_ponto(semente, ponto), nivel)
        p = float(r["p"][0])
        linhas.append({"PONTO": ponto, "p_clim": p, "ic_inf": float(r["ic_inf"][0]),
                       "ic_sup": float(r["ic_sup"][0]), "n_anos": int(r["n_anos"][0]),
                       "flag_p_extremo": p in (0.0, 1.0)})
    return pd.DataFrame(linhas)
