"""Dos dias aos anos: probabilidade, intervalo de confiança e suavização.

Passo a passo
-------------
1. **Dias → anos.** O indicador diário (1/0/NaN, vindo de ``eventos``) vira um indicador por
   ano: "houve pelo menos um evento neste ano, neste período?". O período pode ser um
   decêndio, um mês ou uma janela de safra (por exemplo, outubro a março).
2. **Probabilidade.** É a fração de anos com evento: ``p = anos com evento / anos com dado``.
3. **Intervalo de confiança (bootstrap de anos).** Com 22 anos, um único ano a mais ou a
   menos com evento muda ``p`` em cerca de 0,05. Para medir essa incerteza, imaginamos
   "outros históricos possíveis": sorteamos 22 anos do histórico **com reposição** (um ano
   pode sair duas vezes, outro nenhuma) e recalculamos ``p``. Repetindo isso 1.000 vezes,
   os valores de ``p`` que ficam entre os 2,5% mais baixos e os 2,5% mais altos formam o
   intervalo de 95%.

   O sorteio é sempre de **anos inteiros**, nunca de dias soltos. Dias vizinhos são
   parecidos entre si (um período chuvoso dura vários dias); sortear dias quebraria essa
   ligação e daria um intervalo estreito demais, passando uma falsa precisão.

4. **Suavização (opcional).** Com poucos anos, a probabilidade de um decêndio para o
   seguinte oscila por acaso. A versão suavizada é a média de cada decêndio com os dois
   vizinhos; o calendário é circular (o decêndio 36, fim de dezembro, é vizinho do 1).

Probabilidade de "pelo menos um dos eventos" (``p_algum``)
----------------------------------------------------------
É calculada direto dos anos: um ano conta se teve chuva extrema **ou** queda brusca.
Não se pode calcular por ``1 − (1 − p_chuva)(1 − p_queda)``, porque essa fórmula supõe que
os dois eventos são independentes, e eles não são: muitas quedas de temperatura acontecem
junto com frentes frias que também trazem chuva.
"""
from __future__ import annotations

import zlib

import numpy as np
import pandas as pd


# ------------------------------------------------------------------------ indicadores anuais
def indicador_anual_por_unidade(df: pd.DataFrame, evento: pd.Series, unidade: str = "decendio") -> pd.DataFrame:
    """Para cada ponto, ano e unidade (ex.: decêndio): houve evento? (1.0, 0.0 ou NaN).

    O evento conta no dia em que a janela termina: uma chuva de 3 dias somada até 11/01
    conta no 2º decêndio, mesmo começando no 1º.

    Uma unidade só vale naquele ano se todos os seus dias tiverem indicador. Se faltar algum
    dia, o ano fica ``NaN`` e não entra na contagem, porque "não vimos evento" não é o mesmo
    que "não houve evento". Ex.: no 1º decêndio de 2000 a chuva de 3 dias só existe a partir
    de 03/01, então esse decêndio de 2000 fica de fora.

    Devolve as colunas ``PONTO, YEAR, <unidade>, evento``.
    """
    base = pd.DataFrame({
        "PONTO": df["PONTO"].to_numpy(),
        "YEAR": df["data"].dt.year.to_numpy(),
        unidade: df[unidade].to_numpy(),
        "ev": np.asarray(evento, dtype=float),
    })
    g = base.groupby(["PONTO", "YEAR", unidade], sort=True)["ev"]
    out = g.max().to_frame("evento")  # máximo de 0/1 = "houve pelo menos um"
    out.loc[g.count() < g.size(), "evento"] = np.nan  # algum dia sem indicador
    return out.reset_index()


def indicador_por_safra(df: pd.DataFrame, evento: pd.Series, inicio: tuple[int, int] = (10, 1),
                        fim: tuple[int, int] = (3, 31)) -> pd.DataFrame:
    """Para cada ponto e safra: houve evento entre ``inicio`` e ``fim``? (1.0, 0.0 ou NaN).

    ``inicio`` e ``fim`` são (mês, dia). A janela pode virar o ano: de (10, 1) a (3, 31) vai
    de 1º de outubro a 31 de março do ano seguinte. A safra é identificada pelo ano em que
    começa (``ano_safra`` 2020 = outubro de 2020 a março de 2021).

    Só valem safras com todos os dias disponíveis. Com a referência até 2021, a safra 2021/22
    fica de fora (precisaria de janeiro a março de 2022), assim como a 1999/2000.

    Devolve as colunas ``PONTO, ano_safra, evento``.
    """
    d = df["data"]
    md = d.dt.month * 100 + d.dt.day  # ex.: 15 de março → 315, para comparar datas sem o ano
    ini, fi = inicio[0] * 100 + inicio[1], fim[0] * 100 + fim[1]
    cruza = ini > fi  # a janela atravessa a virada do ano?
    dentro = ((md >= ini) | (md <= fi)) if cruza else ((md >= ini) & (md <= fi))
    ano_safra = d.dt.year - ((md <= fi) & cruza).astype(int)

    base = pd.DataFrame({
        "PONTO": df["PONTO"].to_numpy(),
        "ano_safra": ano_safra.to_numpy(),
        "ev": np.asarray(evento, dtype=float),
    })[dentro.to_numpy()]
    g = base.groupby(["PONTO", "ano_safra"], sort=True)["ev"]
    out = g.max().to_frame("evento")

    # quantos dias cada safra deveria ter (conta 29/02 quando existe)
    anos = out.index.get_level_values("ano_safra")
    comeco = pd.to_datetime({"year": anos, "month": inicio[0], "day": inicio[1]})
    final = pd.to_datetime({"year": anos + int(cruza), "month": fim[0], "day": fim[1]})
    esperados = ((final - comeco).dt.days + 1).to_numpy()
    out.loc[g.count().to_numpy() < esperados, "evento"] = np.nan
    return out.reset_index()


def combinar_algum(*indicadores: pd.Series) -> pd.Series:
    """Ano a ano: houve pelo menos um dos eventos? (o "ou" lógico).

    Se algum indicador do ano for ``NaN``, o resultado também é ``NaN``.
    """
    tab = pd.concat(indicadores, axis=1)
    return tab.max(axis=1).where(tab.notna().all(axis=1))


# --------------------------------------------------------------- probabilidade e bootstrap
def suavizar_circular(p: np.ndarray) -> np.ndarray:
    """Média de cada unidade com as duas vizinhas, dando a volta no calendário.

    Ex.: decêndio 1 suavizado = (p₃₆ + p₁ + p₂) / 3. Funciona no último eixo, então aceita
    um vetor (unidades) ou uma matriz (repetições do bootstrap × unidades).
    """
    p = np.asarray(p, dtype=float)
    return (np.roll(p, 1, axis=-1) + p + np.roll(p, -1, axis=-1)) / 3.0


def _media_ignorando_nan(x: np.ndarray, eixo: int) -> np.ndarray:
    """Média que pula os NaN (anos sem dado); NaN se não sobrar nenhum valor."""
    n = np.sum(~np.isnan(x), axis=eixo)
    soma = np.nansum(x, axis=eixo)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(n > 0, soma / n, np.nan)


def probabilidade_bootstrap(matriz: np.ndarray, repeticoes: int = 1000, semente: int | np.random.SeedSequence = 42,
                            nivel: float = 0.95, suavizar: bool = False) -> dict[str, np.ndarray]:
    """Probabilidade e intervalo de confiança por bootstrap de anos.

    ``matriz``: uma linha por ano e uma coluna por unidade (decêndio, mês...), com 1, 0 ou
    NaN. Um vetor simples é tratado como uma única unidade.

    Cada repetição sorteia linhas (anos inteiros) com reposição e recalcula a fração de anos
    com evento. A ``semente`` fixa o sorteio, para o resultado ser sempre o mesmo.

    Devolve ``p``, ``ic_inf``, ``ic_sup`` e ``n_anos`` (anos com dado). Com ``suavizar=True``,
    também ``p_suav``, ``ic_inf_suav`` e ``ic_sup_suav``; a suavização é aplicada dentro de
    cada repetição, para o intervalo refletir a versão suavizada.
    """
    m = np.atleast_2d(np.asarray(matriz, dtype=float))
    if m.shape[0] == 1 and np.ndim(matriz) == 1:
        m = m.T  # vetor de anos → matriz com uma coluna
    n_anos_total = m.shape[0]
    rng = np.random.default_rng(semente)
    idx = rng.integers(0, n_anos_total, size=(repeticoes, n_anos_total))  # anos sorteados
    replicas = _media_ignorando_nan(m[idx], eixo=1)  # forma: (repetições, unidades)

    alfa = (1 - nivel) / 2
    q = [100 * alfa, 100 * (1 - alfa)]  # para 95%: percentis 2,5 e 97,5
    p = _media_ignorando_nan(m, eixo=0)
    out = {"p": p, "n_anos": np.sum(~np.isnan(m), axis=0)}
    out["ic_inf"], out["ic_sup"] = np.nanpercentile(replicas, q, axis=0)
    if suavizar:
        out["p_suav"] = suavizar_circular(p)
        out["ic_inf_suav"], out["ic_sup_suav"] = np.nanpercentile(suavizar_circular(replicas), q, axis=0)
    return out


def semente_do_ponto(semente: int, ponto: str) -> np.random.SeedSequence:
    """Semente própria de cada ponto, derivada do nome (``P01``...).

    Assim cada ponto tem um sorteio diferente, e o resultado de um ponto não muda se a lista
    de pontos mudar de ordem ou de tamanho.
    """
    return np.random.SeedSequence([semente, zlib.crc32(ponto.encode("utf-8"))])


def tabela_por_unidade(indicadores: pd.DataFrame, unidade: str = "decendio", repeticoes: int = 1000,
                       semente: int = 42, nivel: float = 0.95, suavizar: bool = True,
                       n_unidades: int | None = 36) -> pd.DataFrame:
    """Tabela ``PONTO × unidade`` a partir de ``indicador_anual_por_unidade``.

    Colunas: ``p_clim`` (probabilidade histórica), ``ic_inf`` e ``ic_sup`` (intervalo),
    as versões suavizadas, ``n_anos`` e ``flag_p_extremo``.

    ``flag_p_extremo`` marca ``p_clim`` igual a 0 ou 1. Nesses casos todo sorteio dá o mesmo
    valor e o intervalo fica com largura zero, o que não quer dizer certeza: só que, em
    22 anos, o evento nunca (ou sempre) aconteceu.
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
