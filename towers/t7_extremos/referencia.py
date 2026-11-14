"""Montagem das tabelas de referência da Torre 7 (anos até 2021).

Três tabelas:

- ``indicadores``: por ponto, ano e decêndio, houve chuva extrema? queda brusca? algum dos
  dois? (1/0/NaN). Com ela dá para calcular a probabilidade de qualquer janela (ex.: a fase
  de plantio de uma cultura) direto dos anos.
- ``decendio``: probabilidade histórica por ponto e decêndio, com IC e versão suavizada.
- ``safra``: probabilidade por ponto na safra de outubro a março.
"""
from __future__ import annotations

import pandas as pd
from omegaconf import DictConfig

from . import eventos, probabilidade as prob
from .config import limiar_obrigatorio

EVENTOS = ("chuva_extrema", "queda_brusca", "algum")
SAFRA = ((10, 1), (3, 31))  # outubro a março


def indicadores_diarios(ref: pd.DataFrame, cfg: DictConfig) -> dict[str, pd.Series]:
    """Indicador diário (1/0/NaN) de cada evento, com os limiares da config.

    Chuva: soma em ``janela_dias`` dias **acima** do limiar (>). Queda: **maior ou igual** (>=).
    """
    lc, lq = cfg.limiares.chuva_extrema, cfg.limiares.queda_temperatura
    chuva = eventos.chuva_acumulada(ref, lc.janela_dias)
    queda = eventos.queda_temperatura(ref, lq.janela_dias, lq.absoluto)
    return {
        "chuva_extrema": eventos.indicador_evento(chuva, limiar_obrigatorio(lc, "chuva_extrema"), inclusivo=False),
        "queda_brusca": eventos.indicador_evento(queda, limiar_obrigatorio(lq, "queda_temperatura"), inclusivo=True),
    }


def tabela_indicadores(ref: pd.DataFrame, diarios: dict[str, pd.Series]) -> pd.DataFrame:
    """Indicadores anuais por ponto, ano e decêndio, uma coluna por evento (inclui ``algum``)."""
    partes = [prob.indicador_anual_por_unidade(ref, ind, "decendio").set_index(["PONTO", "YEAR", "decendio"])["evento"]
              .rename(nome) for nome, ind in diarios.items()]
    tab = pd.concat(partes, axis=1)
    tab["algum"] = prob.combinar_algum(tab["chuva_extrema"], tab["queda_brusca"])
    return tab.reset_index()


def _info_limiar(cfg: DictConfig) -> dict[str, dict]:
    lc, lq = cfg.limiares.chuva_extrema, cfg.limiares.queda_temperatura
    return {
        "chuva_extrema": {"limiar": f"> {lc.valor} {lc.unidade} em {lc.janela_dias} dias", "status_limiar": lc.status},
        "queda_brusca": {"limiar": f">= {lq.valor} {lq.unidade} em {lq.janela_dias} dias", "status_limiar": lq.status},
        "algum": {"limiar": "chuva_extrema ou queda_brusca no mesmo ano", "status_limiar":
                  "PROVISORIO" if "PROVISORIO" in (lc.status, lq.status) else "DEFINIDO"},
    }


def tabela_decendio(indicadores: pd.DataFrame, cfg: DictConfig) -> pd.DataFrame:
    """Probabilidade por ponto, decêndio e evento (formato longo)."""
    b, info = cfg.bootstrap, _info_limiar(cfg)
    partes = []
    for ev in EVENTOS:
        ind = indicadores[["PONTO", "YEAR", "decendio", ev]].rename(columns={ev: "evento"})
        tab = prob.tabela_por_unidade(ind, "decendio", b.repeticoes, b.semente, b.nivel_ic, suavizar=True)
        tab.insert(2, "evento", ev)
        tab.insert(3, "limiar", info[ev]["limiar"])
        tab["status_limiar"] = info[ev]["status_limiar"]
        partes.append(tab)
    return pd.concat(partes, ignore_index=True)


def tabela_safra(ref: pd.DataFrame, diarios: dict[str, pd.Series], cfg: DictConfig) -> pd.DataFrame:
    """Probabilidade por ponto e evento na safra out–mar (``algum`` contado direto nos anos)."""
    b, info = cfg.bootstrap, _info_limiar(cfg)
    por_ano = {nome: prob.indicador_por_safra(ref, ind, *SAFRA).set_index(["PONTO", "ano_safra"])["evento"]
               for nome, ind in diarios.items()}
    por_ano["algum"] = prob.combinar_algum(por_ano["chuva_extrema"], por_ano["queda_brusca"])
    partes = []
    for ev in EVENTOS:
        ind = por_ano[ev].rename("evento").reset_index()
        tab = prob.tabela_por_safra(ind, b.repeticoes, b.semente, b.nivel_ic)
        tab.insert(1, "evento", ev)
        tab.insert(2, "limiar", info[ev]["limiar"])
        tab["janela"] = "01/10 a 31/03"
        tab["status_limiar"] = info[ev]["status_limiar"]
        partes.append(tab)
    return pd.concat(partes, ignore_index=True)
