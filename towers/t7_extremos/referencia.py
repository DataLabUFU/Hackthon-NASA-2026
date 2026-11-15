"""Montagem das tabelas de referência da Torre 7 (anos até 2021).

Três tabelas:

- ``indicadores``: por ponto, ano e decêndio, houve chuva extrema? queda brusca? algum dos
  dois? (1/0/NaN). Com ela dá para calcular a probabilidade de qualquer janela (ex.: a fase
  de plantio de uma cultura) direto dos anos.
- ``decendio``: probabilidade histórica por ponto e decêndio, com IC e versão suavizada.
- ``safra``: probabilidade por ponto na safra de outubro a março. Na chuva extrema, os pontos
  aprovados no teste de estabilidade usam a GPD (coluna ``metodo``); o resto é empírico.
"""
from __future__ import annotations

import pandas as pd
from omegaconf import DictConfig

from . import dados, eventos, probabilidade as prob
from .config import limiar_obrigatorio

EVENTOS = ("chuva_extrema", "queda_brusca", "algum")
SAFRA = ((10, 1), (3, 31))  # outubro a março


def com_coordenadas(tab: pd.DataFrame, pontos: pd.DataFrame | None = None) -> pd.DataFrame:
    """Acrescenta ``LAT`` e ``LON`` logo depois de ``PONTO``."""
    pontos = dados.ler_pontos() if pontos is None else pontos
    out = tab.merge(pontos, on="PONTO", how="left")
    cols = ["PONTO", "LAT", "LON"] + [c for c in tab.columns if c != "PONTO"]
    return out[cols]


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
        tab["metodo"] = "empirico"
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
        tab["metodo"] = "empirico"
        partes.append(tab)
    return pd.concat(partes, ignore_index=True)


def ler_resultado_gpd(caminho) -> pd.DataFrame:
    """Lê a saída de ``scripts.t7_gpd`` (``gpd_por_ponto.csv``)."""
    from pathlib import Path
    caminho = Path(caminho)
    if not caminho.exists():
        raise FileNotFoundError(f"{caminho} não existe: rode antes `python -m scripts.t7_gpd`")
    return pd.read_csv(caminho)


def aplicar_gpd_chuva(safra: pd.DataFrame, resultado_gpd: pd.DataFrame, limiar_mm: float,
                      exigir_concordancia: bool = True) -> pd.DataFrame:
    """Troca ``p_clim`` e IC da chuva extrema pela GPD onde ela é confiável.

    Usa a GPD num ponto se (1) ela passou no teste de estabilidade e (2), com
    ``exigir_concordancia``, o valor empírico cai dentro do IC da GPD. Se o valor observado
    fica fora, o modelo está mal ajustado justamente no nível entregue, e vale a contagem.

    Só a linha ``chuva_extrema`` da safra out–mar muda; queda e ``algum`` seguem empíricos
    (``algum`` não pode misturar GPD com contagem sem supor independência). Os valores
    empíricos ficam em ``p_empirico``, ``ic_inf_empirico`` e ``ic_sup_empirico``, e
    ``motivo_metodo`` explica a escolha.
    """
    g = resultado_gpd[resultado_gpd["variavel"] == "chuva_3d"].set_index("PONTO")
    if not (g["z_evento"] == limiar_mm).all():
        raise ValueError("A GPD foi rodada com outro limiar de chuva: rode `python -m scripts.t7_gpd` de novo")
    out = safra.copy()
    out["p_empirico"], out["ic_inf_empirico"], out["ic_sup_empirico"] = out["p_clim"], out["ic_inf"], out["ic_sup"]
    out["motivo_metodo"] = ""
    for i, linha in out[out["evento"] == "chuva_extrema"].iterrows():
        r = g.loc[linha["PONTO"]]
        concorda = r["p_gpd_ic_inf"] <= linha["p_clim"] <= r["p_gpd_ic_sup"]
        if not bool(r["gpd_aprovada"]):
            out.loc[i, "motivo_metodo"] = "GPD reprovada no teste de estabilidade"
        elif exigir_concordancia and not concorda:
            out.loc[i, "motivo_metodo"] = "valor empírico fora do IC da GPD"
        else:
            out.loc[i, ["p_clim", "ic_inf", "ic_sup"]] = [r["p_gpd"], r["p_gpd_ic_inf"], r["p_gpd_ic_sup"]]
            out.loc[i, "metodo"] = "gpd"
            out.loc[i, "flag_p_extremo"] = False
            out.loc[i, "motivo_metodo"] = "GPD estável e de acordo com o empírico"
    return out
