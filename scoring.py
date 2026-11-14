"""Motor de pontuação: qual cultura entra a seguir na rotação?

Nota (0-100) = média ponderada de 7 critérios, cada um de 0 a 1.
Os pesos vêm do agrônomo. Nada de caixa-preta: cada nota tem explicação.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

CRITERIOS = {
    "descompactar": "Descompactar o solo",
    "cobertura_mo": "Cobertura e matéria orgânica",
    "fixacao_n": "Fixação de nitrogênio",
    "agua": "Balanço de água (chuva esperada)",
    "temperatura": "Temperatura e geada",
    "mercado": "Margem de mercado",
    "sequencia": "Sequência (anteriores, próxima cultura, calendário)",
}


@dataclass
class Perfil:
    mes_plantio: int                              # mês em que pretende plantar (1-12)
    culturas_anteriores: list                     # [mais recente, anterior]
    cultura_seguinte: Optional[str] = None        # cultura comercial que vem depois
    mes_cultura_seguinte: Optional[int] = None    # mês de plantio dela
    compactacao: float = 2.0                      # 0 (solto) a 5 (muito compactado), avaliado em campo
    argila_pct: float = 30.0
    mo_pct: float = 2.5                           # matéria orgânica (%)
    declividade_pct: float = 3.0
    pesos: dict = field(default_factory=dict)     # critério -> 0..10
    origem: dict = field(default_factory=dict)    # campo -> "api" | "manual"


def carregar(pasta=None):
    pasta = Path(pasta) if pasta else Path(__file__).parent
    return (pd.read_csv(pasta / "culturas.csv").set_index("nome"),
            pd.read_csv(pasta / "mercado.csv").set_index("nome"))


def sugerir_pesos(p: Perfil) -> dict:
    """Pesos iniciais a partir do que o solo está pedindo. O agrônomo pode mudar tudo."""
    w = dict(descompactar=3, cobertura_mo=3, fixacao_n=2, agua=4,
             temperatura=3, mercado=3, sequencia=3)
    if p.compactacao >= 3:
        w["descompactar"] = 9
    elif p.compactacao >= 2:
        w["descompactar"] = 6
    if p.mo_pct < 2 or p.declividade_pct > 8:
        w["cobertura_mo"] = 8
    if p.argila_pct < 15:
        w["agua"] = 6
    return w


def clima_sintetico(anos=10):
    """Clima de exemplo (tipo Cerrado) para testar sem internet."""
    idx = pd.date_range(f"{2026 - anos}-01-01", "2025-12-31")
    doy = idx.dayofyear.values
    rng = np.random.default_rng(1)
    t = 22.5 + 3 * np.cos(2 * np.pi * (doy - 15) / 365)
    p_chuva = 0.12 + 0.5 * (np.cos(2 * np.pi * (doy - 15) / 365) + 1) / 2
    chuva = np.where(rng.random(len(idx)) < p_chuva, rng.gamma(1.5, 8, len(idx)), 0.0)
    return pd.DataFrame({"T2M": t + rng.normal(0, 1, len(idx)), "T2M_MIN": t - 6 + rng.normal(0, 2, len(idx)),
                         "PRECTOTCORR": chuva, "GWETROOT": 0.5}, index=idx)


def janela_clima(clima, mes, dias):
    """Clima esperado no ciclo: mediana e ano seco (percentil 20) de todos os anos disponíveis."""
    tm, tmin, ch = [], [], []
    for ano in sorted(set(clima.index.year)):
        ini = pd.Timestamp(ano, mes, 1)
        j = clima.loc[ini: ini + pd.Timedelta(days=dias)]
        if len(j) < dias * 0.9:
            continue
        tm.append(j["T2M"].mean())
        tmin.append(j["T2M_MIN"].quantile(0.05))
        ch.append(j["PRECTOTCORR"].sum())
    if not ch:
        return None
    return dict(t_media=float(np.nanmedian(tm)), t_min=float(np.nanmedian(tmin)),
                chuva_med=float(np.nanmedian(ch)), chuva_seca=float(np.nanpercentile(ch, 20)), anos=len(ch))


def _agua(c, w, p, ajuste_chuva):
    # parte da chuva que o solo aproveita: solo arenoso e declive perdem mais
    efic = (0.65 + 0.25 * min(p.argila_pct, 50) / 50) * (1 - min(p.declividade_pct, 20) / 100)
    precisa = c.agua_mm * (1 - 0.06 * c.tol_seca)      # cultura tolerante à seca precisa de menos
    f = lambda ch: float(np.clip(ch * (1 + ajuste_chuva / 100) * efic / precisa, 0, 1))
    return 0.6 * f(w["chuva_med"]) + 0.4 * f(w["chuva_seca"]), precisa


def _temperatura(c, w, ajuste_temp):
    t = w["t_media"] + ajuste_temp
    desvio = max(c.t_ideal_min - t, t - c.t_ideal_max, 0)
    s = max(0.0, 1 - desvio / 8)
    frio = (w["t_min"] + ajuste_temp) < c.t_min_critica
    return (s * 0.5 if frio else s), t, frio


def _sequencia(c, cult, p):
    partes, pos, neg = [], [], []
    ant = [a for a in p.culturas_anteriores if a in cult.index]
    q = 1.0                                              # 1) quebra do ciclo de pragas/doenças
    if ant:
        if c.name == ant[0]:
            q = 0.1; neg.append("repete a cultura anterior (risco de pragas e doenças)")
        elif cult.loc[ant[0], "familia"] == c.familia:
            q = 0.5; neg.append(f"mesma família ({c.familia}) da cultura anterior")
        else:
            pos.append("muda de família botânica e ajuda a quebrar ciclos de pragas")
        if len(ant) > 1 and cult.loc[ant[1], "familia"] == c.familia:
            q *= 0.6
    partes.append(q)
    if p.cultura_seguinte in cult.index:                 # 2) preparo para a cultura seguinte
        s = cult.loc[p.cultura_seguinte]
        v = 0.3 if s.familia == c.familia else 0.6
        if s.familia == c.familia:
            neg.append(f"mesma família da cultura seguinte ({s.name})")
        bonus_n = c.fixa_n / 5 * s.demanda_n / 5 * 0.4
        if bonus_n >= 0.1:
            pos.append(f"deixa nitrogênio para {s.name}")
        v += bonus_n + (c.biomassa / 5 * 0.15 if s.comercial else 0)
        partes.append(min(v, 1.0))
    janela = [int(m) for m in str(c.meses_plantio).split(";")]   # 3) calendário
    cal = 1.0 if p.mes_plantio in janela else 0.3
    if cal < 1:
        neg.append("mês de plantio fora da janela recomendada")
    if p.mes_cultura_seguinte:
        folga = ((p.mes_cultura_seguinte - p.mes_plantio - 1) % 12) + 1
        falta = c.ciclo_dias / 30 - folga
        if falta > 0:
            cal *= max(0.0, 1 - falta / 2)
            neg.append(f"ciclo (~{int(c.ciclo_dias)} dias) invade o plantio da cultura seguinte")
        else:
            pos.append("termina a tempo da cultura seguinte")
    partes.append(cal)
    return float(np.mean(partes)), pos, neg


def pontuar(cult, mer, clima, p: Perfil, ajuste_chuva=0.0, ajuste_temp=0.0, candidatas=None):
    nomes = list(candidatas or cult.index)
    margem = (mer["receita_ha"] - mer["custo_ha"]).reindex(nomes)
    mn, mx = margem.min(), margem.max()
    pesos = {k: float(p.pesos.get(k, 0)) for k in CRITERIOS}
    total = sum(pesos.values()) or 1.0
    linhas = []
    for n in nomes:
        c = cult.loc[n]
        w = janela_clima(clima, p.mes_plantio, int(c.ciclo_dias))
        pos, neg, sub = [], [], {}
        sub["descompactar"] = c.descompacta / 5
        sub["cobertura_mo"] = c.biomassa / 5
        sub["fixacao_n"] = c.fixa_n / 5
        sub["mercado"] = float((margem[n] - mn) / (mx - mn)) if mx > mn else 0.5
        sub["sequencia"], p_seq, n_seq = _sequencia(c, cult, p)
        pos += p_seq; neg += n_seq
        if w is None:
            sub["agua"] = sub["temperatura"] = 0.5
            neg.append("sem dados de clima para o ciclo (nota neutra)")
        else:
            sub["agua"], precisa = _agua(c, w, p, ajuste_chuva)
            sub["temperatura"], t, frio = _temperatura(c, w, ajuste_temp)
            ch = w["chuva_med"] * (1 + ajuste_chuva / 100)
            (pos if sub["agua"] >= 0.8 else neg).append(
                f"chuva esperada ~{ch:.0f} mm no ciclo; a cultura precisa de ~{precisa:.0f} mm")
            if frio:
                neg.append(f"risco de frio: mínima ~{w['t_min'] + ajuste_temp:.0f} °C (limite {c.t_min_critica} °C)")
            elif sub["temperatura"] >= 0.8:
                pos.append(f"temperatura média ~{t:.1f} °C dentro da faixa ideal")
            else:
                neg.append(f"temperatura média ~{t:.1f} °C fora da faixa ({c.t_ideal_min}-{c.t_ideal_max} °C)")
        for k, txt in (("descompactar", f"raiz que ajuda a descompactar (nota {int(c.descompacta)}/5)"),
                       ("cobertura_mo", f"gera palhada e matéria orgânica (nota {int(c.biomassa)}/5)"),
                       ("fixacao_n", f"fixa nitrogênio (nota {int(c.fixa_n)}/5)")):
            if pesos[k] > 0 and sub[k] >= 0.7:
                pos.append(txt)
        if pesos["mercado"] > 0:
            (pos if sub["mercado"] >= 0.7 else neg if sub["mercado"] <= 0.3 else []).append(
                f"margem estimada {margem[n]:,.0f} por ha (ver mercado.csv)")
        nota = 100 * sum(sub[k] * pesos[k] for k in CRITERIOS) / total
        fora = p.mes_plantio not in [int(m) for m in str(c.meses_plantio).split(";")]
        if fora:                                   # plantar fora da época é risco agronômico real
            nota *= 0.85
        linha = {"cultura": n, "nota": round(nota, 1), "fora_janela": fora}
        linha.update({f"c_{k}": round(100 * sub[k] * pesos[k] / total, 1) for k in CRITERIOS})
        linha.update({f"s_{k}": round(sub[k], 2) for k in CRITERIOS})
        linha["positivos"], linha["riscos"] = pos, neg
        linhas.append(linha)
    return pd.DataFrame(linhas).sort_values("nota", ascending=False).reset_index(drop=True)


def lacunas(p: Perfil):
    """O que a ferramenta NÃO sabe: o agrônomo precisa validar."""
    out = [f"{k}: veio de base global/satélite (baixa resolução); confirmar com análise de solo no talhão"
           for k, v in p.origem.items() if v == "api"]
    out += ["Compactação: depende de avaliação em campo (penetrômetro, perfil cultural).",
            "Traços das culturas (culturas.csv) e preços (mercado.csv) são estimativas iniciais.",
            "Clima esperado = histórico de anos passados; não é previsão da safra.",
            "Pragas, doenças, equipamentos, sementes e crédito não entram na nota."]
    return out


if __name__ == "__main__":
    cult, mer = carregar()
    p = Perfil(mes_plantio=3, culturas_anteriores=["soja", "milho"], cultura_seguinte="soja",
               mes_cultura_seguinte=10, compactacao=4)
    p.pesos = sugerir_pesos(p)
    print("Pesos sugeridos:", p.pesos)
    r = pontuar(cult, mer, clima_sintetico(), p)
    print(r[["cultura", "nota"]].head(8).to_string(index=False))
    top = r.iloc[0]
    print("\nTop 1:", top.cultura)
    print(" + ", *top.positivos, sep="\n   ")
    print(" - ", *top.riscos, sep="\n   ")
