"""GPD (picos acima de um limiar) para a chuva em 3 dias e a queda de temperatura.

Análise complementar à frequência empírica: dá níveis de retorno e probabilidades para níveis
acima do observado. Antes de ajustar, os dados são tratados para cumprir as hipóteses da GPD
(Coles, 2001, cap. 4–6):

1. **Estacionariedade sazonal:** só dias da safra out–mar (a queda brusca, por exemplo, é
   muito mais comum no inverno; misturar estações misturaria distribuições diferentes).
2. **Excessos independentes (declustering, §5.3.2):** dias acima do limiar ``u`` separados por
   menos de ``r`` dias abaixo dele formam um grupo; só o pico de cada grupo entra no ajuste.
   A soma móvel de 3 dias, por exemplo, faz um único temporal passar do limiar em 2–3 dias
   seguidos. O índice extremal θ = grupos / excedências resume esse agrupamento.
3. **Limiar ``u``:** quantil alto da série da safra; a escolha é conferida pela estabilidade
   de ξ e da escala modificada σ* = σ − ξu em vários limiares (§4.3.1 e §4.3.4).
4. **Tendência (§6.1):** compara σ constante com σ(t) = exp(β₀ + β₁t) pela razão de
   verossimilhança (deviance).

Probabilidade na safra para um nível ``z > u`` (picos chegam como Poisson, λ por safra)::

    P(máximo da safra > z) = 1 − exp(−λ · [1 + ξ (z − u)/σ]^(−1/ξ))
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import optimize, stats

SAFRA = ((10, 1), (3, 31))


# ----------------------------------------------------------------------------- tratamento
def serie_safra(df: pd.DataFrame, medida: pd.Series, inicio=SAFRA[0], fim=SAFRA[1]) -> pd.DataFrame:
    """Valores diários dentro da safra, só de safras completas. Devolve ``PONTO, data, ano_safra, valor``."""
    d = df["data"]
    md = d.dt.month * 100 + d.dt.day
    ini, fi = inicio[0] * 100 + inicio[1], fim[0] * 100 + fim[1]
    dentro = (md >= ini) | (md <= fi)
    base = pd.DataFrame({"PONTO": df["PONTO"].to_numpy(), "data": d.to_numpy(),
                         "ano_safra": (d.dt.year - (md <= fi).astype(int)).to_numpy(),
                         "valor": np.asarray(medida, dtype=float)})[dentro.to_numpy()]
    # safra completa: todos os dias presentes e com valor
    comeco = pd.to_datetime({"year": base["ano_safra"], "month": inicio[0], "day": inicio[1]})
    final = pd.to_datetime({"year": base["ano_safra"] + 1, "month": fim[0], "day": fim[1]})
    base["esperados"] = ((final - comeco).dt.days + 1).to_numpy()
    g = base.groupby(["PONTO", "ano_safra"])
    ok = (g["valor"].transform("count") == base["esperados"])
    return base[ok].drop(columns="esperados").reset_index(drop=True)


def declusterizar(valores: np.ndarray, u: float, r: int) -> tuple[np.ndarray, int]:
    """Picos dos grupos de excedências (método de runs). Devolve (picos, nº de excedências).

    Um grupo começa no primeiro valor > ``u`` e termina quando aparecem ``r`` valores seguidos
    <= ``u``. ``valores`` deve ser uma sequência contínua de dias (uma safra).
    """
    picos, atual, abaixo, n_exc = [], None, 0, 0
    for v in valores:
        if v > u:
            n_exc += 1
            atual = v if atual is None else max(atual, v)
            abaixo = 0
        elif atual is not None:
            abaixo += 1
            if abaixo >= r:
                picos.append(atual)
                atual, abaixo = None, 0
    if atual is not None:
        picos.append(atual)
    return np.asarray(picos, dtype=float), n_exc


def picos_por_safra(serie_ponto: pd.DataFrame, u: float, r: int) -> pd.DataFrame:
    """Picos declusterizados de um ponto, safra a safra (grupos não atravessam safras).

    Devolve ``ano_safra, pico`` e, em ``attrs``, o nº de safras, de excedências e de grupos.
    """
    linhas, n_exc = [], 0
    for ano, sub in serie_ponto.sort_values("data").groupby("ano_safra"):
        picos, n = declusterizar(sub["valor"].to_numpy(), u, r)
        n_exc += n
        linhas += [{"ano_safra": ano, "pico": p} for p in picos]
    out = pd.DataFrame(linhas, columns=["ano_safra", "pico"])
    out.attrs.update(n_safras=int(serie_ponto["ano_safra"].nunique()), n_excedencias=n_exc, n_grupos=len(out))
    return out


# ----------------------------------------------------------------------------- ajuste
def _nll(sigma: np.ndarray | float, xi: float, y: np.ndarray) -> float:
    """Menos log-verossimilhança da GPD (Coles, eq. 4.10); σ pode variar por observação."""
    sigma = np.broadcast_to(np.asarray(sigma, float), y.shape)
    if np.any(sigma <= 0):
        return np.inf
    if abs(xi) < 1e-6:
        return float(np.sum(np.log(sigma) + y / sigma))
    t = 1 + xi * y / sigma
    if np.any(t <= 0):
        return np.inf
    return float(np.sum(np.log(sigma) + (1 + 1 / xi) * np.log(t)))


def ajustar_gpd(excessos: np.ndarray) -> dict:
    """Máxima verossimilhança de (σ, ξ) para os excessos ``y = pico − u`` (todos > 0).

    Devolve ``sigma, xi, nll, ok``. ``ok=False`` se o otimizador falhar, se ξ <= −0,5
    (região em que a máxima verossimilhança não tem as propriedades usuais, §4.3.2) ou se
    houver menos de 10 excessos.
    """
    y = np.asarray(excessos, float)
    if len(y) < 10:
        return {"sigma": np.nan, "xi": np.nan, "nll": np.nan, "ok": False}
    f = lambda th: _nll(np.exp(th[0]), th[1], y)
    melhor = None
    for xi0 in (0.1, -0.1, 0.3):  # alguns pontos de partida, fica o melhor
        r = optimize.minimize(f, [np.log(y.mean()), xi0], method="Nelder-Mead",
                              options={"xatol": 1e-6, "fatol": 1e-8, "maxiter": 2000})
        if np.isfinite(r.fun) and (melhor is None or r.fun < melhor.fun):
            melhor = r
    if melhor is None:
        return {"sigma": np.nan, "xi": np.nan, "nll": np.nan, "ok": False}
    sigma, xi = float(np.exp(melhor.x[0])), float(melhor.x[1])
    return {"sigma": sigma, "xi": xi, "nll": float(melhor.fun), "ok": bool(melhor.success and xi > -0.5)}


def ajustar_gpd_tendencia(excessos: np.ndarray, anos: np.ndarray) -> dict:
    """GPD com σ(t) = exp(β₀ + β₁ t), ξ constante; t = ano centrado. Devolve β₀, β₁, ξ e nll."""
    y, t = np.asarray(excessos, float), np.asarray(anos, float)
    t = t - t.mean()
    f = lambda th: _nll(np.exp(th[0] + th[1] * t), th[2], y)
    est = ajustar_gpd(y)
    x0 = [np.log(est["sigma"]) if est["ok"] else np.log(y.mean()), 0.0, est["xi"] if est["ok"] else 0.1]
    r = optimize.minimize(f, x0, method="Nelder-Mead", options={"xatol": 1e-6, "fatol": 1e-8, "maxiter": 4000})
    return {"b0": float(r.x[0]), "b1": float(r.x[1]), "xi": float(r.x[2]), "nll": float(r.fun),
            "ok": bool(r.success and np.isfinite(r.fun))}


def teste_tendencia_escala(excessos: np.ndarray, anos: np.ndarray) -> dict:
    """Razão de verossimilhança: σ constante × σ com tendência. D = 2(nll₀ − nll₁) ~ χ²₁ (§6.2.2)."""
    est, ten = ajustar_gpd(excessos), ajustar_gpd_tendencia(excessos, anos)
    if not (est["ok"] and ten["ok"]):
        return {"deviance": np.nan, "p": np.nan, "b1": np.nan}
    d = max(0.0, 2 * (est["nll"] - ten["nll"]))
    return {"deviance": d, "p": float(stats.chi2.sf(d, 1)), "b1": ten["b1"]}


# ------------------------------------------------------------------ probabilidade e retorno
def prob_safra(z: float, u: float, sigma: float, xi: float, lam: float) -> float:
    """P(máximo da safra > z), com picos Poisson (λ por safra) e excessos GPD. Vale para z >= u."""
    if z < u:
        raise ValueError("z precisa ser >= u (abaixo do limiar a GPD não descreve os dados)")
    sf = stats.genpareto.sf(z - u, xi, scale=sigma)
    return float(1 - np.exp(-lam * sf))


def nivel_retorno(T: float, u: float, sigma: float, xi: float, lam: float) -> float:
    """Nível z com P(máximo da safra > z) = 1/T (nível de retorno de T safras)."""
    sf = -np.log(1 - 1 / T) / lam
    if sf >= 1:
        return np.nan  # mais raro que o limiar não é: z ficaria abaixo de u
    return float(u + stats.genpareto.isf(sf, xi, scale=sigma))


def nivel_retorno_empirico(maximos_safra: np.ndarray, T: float) -> float:
    """Quantil empírico 1 − 1/T dos máximos por safra, posição de plotagem de Weibull i/(n+1)."""
    x = np.sort(np.asarray(maximos_safra, float))
    pos = np.arange(1, len(x) + 1) / (len(x) + 1)
    return float(np.interp(1 - 1 / T, pos, x))


# ------------------------------------------------------------------------- diagnósticos
def diagnostico(excessos: np.ndarray, sigma: float, xi: float) -> dict:
    """Gráfico de probabilidade em números (§4.3.5): correlação entre i/(k+1) e F̂(y_(i)), e o
    teste de Kolmogorov-Smirnov (aproximado, pois os parâmetros foram estimados nos mesmos dados)."""
    y = np.sort(np.asarray(excessos, float))
    emp = np.arange(1, len(y) + 1) / (len(y) + 1)
    mod = stats.genpareto.cdf(y, xi, scale=sigma)
    return {"corr_pp": float(np.corrcoef(emp, mod)[0, 1]),
            "ks_p": float(stats.kstest(y, "genpareto", args=(xi, 0, sigma)).pvalue)}


def estabilidade_limiar(serie_ponto: pd.DataFrame, quantis, r: int) -> pd.DataFrame:
    """ξ e σ* = σ − ξu para vários limiares (devem ficar estáveis acima do limiar certo)."""
    linhas = []
    for q in quantis:
        u = float(serie_ponto["valor"].quantile(q))
        pk = picos_por_safra(serie_ponto, u, r)
        aj = ajustar_gpd(pk["pico"].to_numpy() - u)
        linhas.append({"quantil": q, "u": u, "n_grupos": pk.attrs["n_grupos"],
                       "theta": pk.attrs["n_grupos"] / max(pk.attrs["n_excedencias"], 1),
                       "media_excesso": float((pk["pico"] - u).mean()) if len(pk) else np.nan,
                       "xi": aj["xi"], "sigma_mod": aj["sigma"] - aj["xi"] * u, "ok": aj["ok"]})
    return pd.DataFrame(linhas)


# ------------------------------------------------------------------- ajuste completo
def ajustar_ponto(serie_ponto: pd.DataFrame, quantil: float, r: int) -> dict:
    """Limiar, declustering e ajuste para um ponto. Devolve parâmetros, λ, θ e os picos."""
    u = float(serie_ponto["valor"].quantile(quantil))
    pk = picos_por_safra(serie_ponto, u, r)
    aj = ajustar_gpd(pk["pico"].to_numpy() - u)
    n_saf = pk.attrs["n_safras"]
    return {"u": u, "r": r, "quantil": quantil, "n_safras": n_saf, "n_excedencias": pk.attrs["n_excedencias"],
            "n_grupos": pk.attrs["n_grupos"], "theta": pk.attrs["n_grupos"] / max(pk.attrs["n_excedencias"], 1),
            "lam": pk.attrs["n_grupos"] / n_saf, **aj, "picos": pk}


def bootstrap_safras(serie_ponto: pd.DataFrame, quantil: float, r: int, z: float, T: float,
                     repeticoes: int = 200, semente=42, nivel: float = 0.95) -> dict:
    """IC por bootstrap de safras (refaz limiar, declustering e ajuste em cada réplica).

    Sorteia safras inteiras com reposição, como na parte empírica. Devolve os ICs de
    ``P(máximo > z)`` e do nível de retorno de ``T`` safras, e quantos ajustes falharam.
    """
    rng = np.random.default_rng(semente)
    anos = serie_ponto["ano_safra"].unique()
    grupos = {a: s for a, s in serie_ponto.groupby("ano_safra")}
    ps, zs, falhas = [], [], 0
    for _ in range(repeticoes):
        sorteio = rng.choice(anos, size=len(anos), replace=True)
        # cada safra sorteada vira uma "safra nova" (ano fictício i), para não fundir repetidas
        partes = [grupos[a].assign(ano_safra=i) for i, a in enumerate(sorteio)]
        a = ajustar_ponto(pd.concat(partes, ignore_index=True), quantil, r)
        if not a["ok"]:
            falhas += 1
            continue
        # se nesta réplica o limiar ficou acima de z, a GPD não descreve z: fica NaN
        ps.append(prob_safra(z, a["u"], a["sigma"], a["xi"], a["lam"]) if z >= a["u"] else np.nan)
        zs.append(nivel_retorno(T, a["u"], a["sigma"], a["xi"], a["lam"]))
    q = [100 * (1 - nivel) / 2, 100 * (1 + nivel) / 2]
    return {"p_ic": tuple(np.nanpercentile(ps, q)) if ps else (np.nan, np.nan),
            "z_ic": tuple(np.nanpercentile(zs, q)) if zs else (np.nan, np.nan), "falhas": falhas}


def estabilidade_gpd_empirico(serie_ponto: pd.DataFrame, quantil: float, r: int, T: float = 10,
                              repeticoes: int = 200, fracao: float = 0.85, semente=42) -> dict:
    """Teste de estabilidade: sorteia 85% das safras sem reposição e reestima o nível de retorno
    de T safras pela GPD e pelo quantil empírico dos máximos. Mede a oscilação relativa
    (P90 − P10)/mediana de cada um e o desvio-padrão de ξ."""
    rng = np.random.default_rng(semente)
    anos = serie_ponto["ano_safra"].unique()
    k = int(round(fracao * len(anos)))
    zg, ze, xis, falhas = [], [], [], 0
    maximos = serie_ponto.groupby("ano_safra")["valor"].max()
    for _ in range(repeticoes):
        sel = rng.choice(anos, size=k, replace=False)
        sub = serie_ponto[serie_ponto["ano_safra"].isin(sel)]
        ze.append(nivel_retorno_empirico(maximos.loc[sel].to_numpy(), T))
        a = ajustar_ponto(sub, quantil, r)
        if not a["ok"]:
            falhas += 1
            continue
        zg.append(nivel_retorno(T, a["u"], a["sigma"], a["xi"], a["lam"]))
        xis.append(a["xi"])
    osc = lambda v: float((np.nanpercentile(v, 90) - np.nanpercentile(v, 10)) / np.nanmedian(v)) if len(v) else np.nan
    og, oe = osc(zg), osc(ze)
    return {"osc_gpd": og, "osc_empirico": oe, "razao": og / oe if oe else np.nan,
            "dp_xi": float(np.std(xis)) if xis else np.nan, "falhas": falhas}
