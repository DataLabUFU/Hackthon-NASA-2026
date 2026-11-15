"""Dos dias aos anos: probabilidade, intervalo de confiança e suavização.

1. **Dias → anos:** para cada ano, houve pelo menos um evento no período (decêndio, mês ou
   safra)?
2. **Probabilidade:** fração de anos com evento.
3. **Intervalo (bootstrap de anos):** sorteia os anos com reposição, recalcula a fração e
   repete 1.000 vezes; os percentis 2,5 e 97,5 formam o IC de 95%. Sorteamos anos inteiros,
   nunca dias: dias vizinhos são parecidos e sorteá-los daria uma precisão falsa.
4. **Suavização (opcional):** média de cada decêndio com os dois vizinhos (o 36 é vizinho
   do 1), para reduzir oscilações ao acaso.

``p_algum`` (chuva extrema ou queda brusca) é contado direto nos anos. Multiplicar as
probabilidades suporia eventos independentes, e eles não são (frentes frias trazem os dois).
"""
from __future__ import annotations

import zlib

import numpy as np
import pandas as pd


# ------------------------------------------------------------------------ indicadores anuais
def indicador_anual_por_unidade(df: pd.DataFrame, evento: pd.Series, unidade: str = "decendio") -> pd.DataFrame:
    """Houve evento em cada ponto, ano e unidade (ex.: decêndio)? 1.0, 0.0 ou NaN.

    O evento conta no dia em que a janela termina. Se faltar indicador em algum dia da
    unidade, o ano fica NaN (ex.: decêndio 1 de 2000, pois a chuva de 3 dias começa em 03/01).
    Devolve ``PONTO, YEAR, <unidade>, evento``.
    """
    base = pd.DataFrame({
        "PONTO": df["PONTO"].to_numpy(),
        "YEAR": df["data"].dt.year.to_numpy(),
        unidade: df[unidade].to_numpy(),
        "ev": np.asarray(evento, dtype=float),
    })
    g = base.groupby(["PONTO", "YEAR", unidade], sort=True)["ev"]
    out = g.max().to_frame("evento")  # máximo de 0/1 = "houve pelo menos um"
    out.loc[g.count() < g.size(), "evento"] = np.nan
    return out.reset_index()


def indicador_por_safra(df: pd.DataFrame, evento: pd.Series, inicio: tuple[int, int] = (10, 1),
                        fim: tuple[int, int] = (3, 31)) -> pd.DataFrame:
    """Houve evento em cada ponto e safra, entre ``inicio`` e ``fim`` (mês, dia)?

    A janela pode virar o ano; a safra leva o ano de início (2020 = out/2020 a mar/2021).
    Safras incompletas ficam NaN (com referência até 2021, a 2021/22 fica de fora).
    Devolve ``PONTO, ano_safra, evento``.
    """
    d = df["data"]
    md = d.dt.month * 100 + d.dt.day  # 15/03 → 315: compara datas sem o ano
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
    """Ano a ano, houve algum dos eventos? NaN se algum indicador for NaN."""
    tab = pd.concat(indicadores, axis=1)
    return tab.max(axis=1).where(tab.notna().all(axis=1))


# --------------------------------------------------------------- probabilidade e bootstrap
def suavizar_circular(p: np.ndarray) -> np.ndarray:
    """Média com os dois vizinhos no último eixo, circular (dec. 1 = (p₃₆ + p₁ + p₂) / 3)."""
    p = np.asarray(p, dtype=float)
    return (np.roll(p, 1, axis=-1) + p + np.roll(p, -1, axis=-1)) / 3.0


def _media_ignorando_nan(x: np.ndarray, eixo: int) -> np.ndarray:
    n = np.sum(~np.isnan(x), axis=eixo)
    soma = np.nansum(x, axis=eixo)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(n > 0, soma / n, np.nan)


def probabilidade_bootstrap(matriz: np.ndarray, repeticoes: int = 1000, semente: int | np.random.SeedSequence = 42,
                            nivel: float = 0.95, suavizar: bool = False) -> dict[str, np.ndarray]:
    """Probabilidade e IC por bootstrap de anos.

    ``matriz``: anos × unidades com 1/0/NaN (um vetor = uma unidade). A ``semente`` fixa o
    sorteio. Devolve ``p``, ``ic_inf``, ``ic_sup``, ``n_anos`` e, com ``suavizar=True``,
    ``p_suav``, ``ic_inf_suav`` e ``ic_sup_suav`` (suavizados em cada repetição).
    """
    m = np.atleast_2d(np.asarray(matriz, dtype=float))
    if m.shape[0] == 1 and np.ndim(matriz) == 1:
        m = m.T  # vetor de anos → uma coluna
    n_anos_total = m.shape[0]
    rng = np.random.default_rng(semente)
    idx = rng.integers(0, n_anos_total, size=(repeticoes, n_anos_total))  # anos sorteados
    replicas = _media_ignorando_nan(m[idx], eixo=1)  # (repetições, unidades)

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
    """Semente própria de cada ponto, derivada do nome (não depende da ordem dos pontos)."""
    return np.random.SeedSequence([semente, zlib.crc32(ponto.encode("utf-8"))])


def tabela_por_unidade(indicadores: pd.DataFrame, unidade: str = "decendio", repeticoes: int = 1000,
                       semente: int = 42, nivel: float = 0.95, suavizar: bool = True,
                       n_unidades: int | None = 36) -> pd.DataFrame:
    """Tabela ``PONTO × unidade`` com ``p_clim``, IC, versões suavizadas, ``n_anos`` e
    ``flag_p_extremo``.

    ``flag_p_extremo`` marca p = 0 ou 1: o IC fica com largura zero, mas isso não é certeza,
    só que o evento nunca (ou sempre) ocorreu nos anos disponíveis.
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
    """Probabilidade por ponto numa janela de safra (a partir de ``indicador_por_safra``)."""
    linhas = []
    for ponto, sub in indicadores.groupby("PONTO", sort=True):
        r = probabilidade_bootstrap(sub["evento"].to_numpy(), repeticoes, semente_do_ponto(semente, ponto), nivel)
        p = float(r["p"][0])
        linhas.append({"PONTO": ponto, "p_clim": p, "ic_inf": float(r["ic_inf"][0]),
                       "ic_sup": float(r["ic_sup"][0]), "n_anos": int(r["n_anos"][0]),
                       "flag_p_extremo": p in (0.0, 1.0)})
    return pd.DataFrame(linhas)
