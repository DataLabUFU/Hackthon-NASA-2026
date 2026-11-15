"""Consulta da Torre 7: probabilidades para um ponto, uma data de plantio e as fases do ciclo.

Uso::

    from datetime import date
    from towers.t7_extremos.consulta import preparar_base, consultar

    base = preparar_base()                      # lê o CSV e calcula os eventos uma vez
    fases = [
        {"nome": "plantio",  "inicio": 0,   "fim": 20,  "eventos": ["chuva_extrema", "queda_brusca"]},
        {"nome": "floracao", "inicio": 50,  "fim": 80,  "eventos": ["queda_brusca"]},
        {"nome": "colheita", "inicio": 110, "fim": 130, "eventos": ["chuva_extrema"]},
    ]
    r = consultar(base, "P06", date(2026, 10, 20), fases)

``inicio`` e ``fim`` são dias depois do plantio (inclusive). Cada fase diz quais eventos
contam nela. Para cada ano de referência, a mesma data de plantio é repetida (20/10/2000,
20/10/2001...) e verificamos se houve evento nas janelas. As probabilidades saem da fração
de anos com evento, com IC por bootstrap de anos; ``p_algum`` é contado direto nos anos.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from omegaconf import DictConfig

from . import config as cfg_mod
from . import dados, enso, eventos, referencia
from .probabilidade import probabilidade_bootstrap, semente_do_ponto

EVENTOS_FASE = ("chuva_extrema", "queda_brusca")


@dataclass
class BaseT7:
    """Dados preparados uma vez e reaproveitados em todas as consultas."""
    cfg: DictConfig
    diarios: pd.DataFrame      # PONTO, data, chuva_extrema, queda_brusca (só anos de referência)
    completo: pd.DataFrame     # série inteira (inclui 2022+), só para o indicador de estiagem
    clim_dtr: pd.DataFrame     # amplitude térmica normal (anos de referência)
    pontos: pd.DataFrame       # PONTO, LAT, LON


def preparar_base(cfg: DictConfig | None = None, caminho: str | Path | None = None) -> BaseT7:
    """Lê o CSV, recorta a referência e calcula os indicadores diários com os limiares da config."""
    cfg = cfg or cfg_mod.carregar_config()
    caminho = Path(caminho) if caminho else cfg_mod.ROOT / cfg.referencia.arquivo
    completo = dados.ler_dados_unificados(caminho)
    ref = dados.filtrar_referencia(completo, cfg.referencia.ano_inicio, cfg.referencia.ano_fim)
    ind = referencia.indicadores_diarios(ref, cfg)
    diarios = pd.DataFrame({"PONTO": ref["PONTO"], "data": ref["data"],
                            "chuva_extrema": ind["chuva_extrema"], "queda_brusca": ind["queda_brusca"]})
    clim = eventos.climatologia_dtr(ref, cfg.limiares.estiagem.janela_climatologia_dias)
    return BaseT7(cfg, diarios, completo, clim, dados.ler_pontos())


def _data_no_ano(data_plantio: date, ano: int) -> date:
    """Mesma data em outro ano (29/02 vira 28/02 em ano não bissexto)."""
    try:
        return data_plantio.replace(year=ano)
    except ValueError:
        return date(ano, 2, 28)


def _validar_fases(fases: list[dict]) -> None:
    if not fases:
        raise ValueError("Informe ao menos uma fase")
    for f in fases:
        if f["inicio"] < 0 or f["fim"] < f["inicio"]:
            raise ValueError(f"Fase {f.get('nome')!r}: precisa 0 <= inicio <= fim")
        desconhecidos = set(f["eventos"]) - set(EVENTOS_FASE)
        if desconhecidos:
            raise ValueError(f"Fase {f.get('nome')!r}: eventos desconhecidos {sorted(desconhecidos)}")


def indicadores_por_ano(base: BaseT7, ponto: str, data_plantio: date, fases: list[dict]) -> pd.DataFrame:
    """Para cada ano de referência: houve chuva extrema, queda brusca ou algum, nas fases?

    O ano só vale se todos os dias de todas as janelas existirem e tiverem indicador; senão
    fica NaN para todos os eventos (assim as três probabilidades usam os mesmos anos).
    Devolve ``ano, chuva_extrema, queda_brusca, algum``.
    """
    _validar_fases(fases)
    serie = base.diarios[base.diarios["PONTO"] == ponto].set_index("data")
    if serie.empty:
        raise KeyError(f"Ponto {ponto!r} não encontrado")
    anos = range(base.cfg.referencia.ano_inicio, base.cfg.referencia.ano_fim + 1)
    linhas = []
    for ano in anos:
        p0 = _data_no_ano(data_plantio, ano)
        linha = {"ano": ano}
        for ev in EVENTOS_FASE:
            janelas = [(p0 + timedelta(days=f["inicio"]), p0 + timedelta(days=f["fim"]))
                       for f in fases if ev in f["eventos"]]
            if not janelas:
                linha[ev] = np.nan
                continue
            vals = []
            for a, z in janelas:
                trecho = serie.loc[pd.Timestamp(a):pd.Timestamp(z), ev]
                vals.append(trecho if len(trecho) == (z - a).days + 1 else None)
            if any(v is None or v.isna().any() for v in vals):
                linha[ev] = np.nan  # janela fora da referência ou com dia sem indicador
            else:
                linha[ev] = float(max(v.max() for v in vals))
        linhas.append(linha)
    tab = pd.DataFrame(linhas)
    usados = [ev for ev in EVENTOS_FASE if any(ev in f["eventos"] for f in fases)]
    # os três resultados usam os mesmos anos: se um evento não tem dado no ano, o ano sai de todos
    completo = tab[usados].notna().all(axis=1)
    tab.loc[~completo, usados] = np.nan
    tab["algum"] = tab[usados].max(axis=1).where(completo)
    return tab


def _resumo(valores: np.ndarray, cfg: DictConfig, ponto: str) -> dict:
    b = cfg.bootstrap
    valores = valores[~np.isnan(valores)]  # sorteia só entre os anos com dado
    if len(valores) == 0:
        return {"p": None, "ic_inf": None, "ic_sup": None, "n_anos": 0}
    r = probabilidade_bootstrap(valores, b.repeticoes, semente_do_ponto(b.semente, ponto), b.nivel_ic)
    return {"p": float(r["p"][0]), "ic_inf": float(r["ic_inf"][0]), "ic_sup": float(r["ic_sup"][0]),
            "n_anos": int(r["n_anos"][0])}


def _estiagem(base: BaseT7, ponto: str, data_plantio: date) -> dict:
    """Condição seca nos ``n_dias`` dias antes do plantio (informativo; não entra em p_algum)."""
    e = base.cfg.limiares.estiagem
    sub = base.completo[base.completo["PONTO"] == ponto]
    fim = pd.Timestamp(data_plantio) - pd.Timedelta(days=1)
    ini = fim - pd.Timedelta(days=e.n_dias - 1)
    trecho = sub[(sub["data"] >= ini) & (sub["data"] <= fim)]
    if len(trecho) < e.n_dias:
        return {"status": "sem_dado", "motivo": f"não há os {e.n_dias} dias antes de {data_plantio}"}
    anom = eventos.anomalia_dtr(trecho, base.clim_dtr)
    out = {"anomalia_media_c": float(anom.mean()), "n_dias": int(e.n_dias), "status_n_dias": e.n_dias_status}
    if e.limiar_amplitude_alta is not None:
        out["frac_dias_alta"] = float((anom >= e.limiar_amplitude_alta).mean())
    else:
        out["frac_dias_alta"] = None  # limiar de "amplitude alta" ainda não definido
    return out


def consultar(base: BaseT7, ponto: str, data_plantio: date, fases: list[dict],
              fases_enso: pd.Series | None = None, fase_enso_atual: str | None = None) -> dict:
    """Saída da Torre 7 para um ponto, uma data de plantio e as fases do ciclo.

    Devolve ``p_chuva_extrema``, ``p_oscilacao`` e ``p_algum`` (cada um com ``p``, IC e
    ``n_anos``), ``enso`` (``nao_calculado`` sem tabela de fases), ``indicador_estiagem``,
    ``n_anos``, ``confianca`` e os limiares usados. Não converte em score.
    """
    cfg = base.cfg
    tab = indicadores_por_ano(base, ponto, data_plantio, fases)
    algum = tab.set_index("ano")["algum"]
    e = cfg.enso
    bloco_enso = enso.probabilidade_enso(algum, fases_enso, fase_enso_atual, k=e.k,
                                         repeticoes=cfg.bootstrap.repeticoes, semente=cfg.bootstrap.semente,
                                         nivel=cfg.bootstrap.nivel_ic, repeticoes_permutacao=e.repeticoes_permutacao)
    p_algum = _resumo(tab["algum"].to_numpy(float), cfg, ponto)
    lc, lq = cfg.limiares.chuva_extrema, cfg.limiares.queda_temperatura
    coord = base.pontos.set_index("PONTO").loc[ponto]
    return {
        "ponto": ponto,
        "lat": float(coord["LAT"]),
        "lon": float(coord["LON"]),
        "data_plantio": data_plantio.isoformat(),
        "p_chuva_extrema": _resumo(tab["chuva_extrema"].to_numpy(float), cfg, ponto),
        "p_oscilacao": _resumo(tab["queda_brusca"].to_numpy(float), cfg, ponto),
        "p_algum": p_algum,
        "enso": bloco_enso,
        "indicador_estiagem": _estiagem(base, ponto, data_plantio),
        "n_anos": p_algum["n_anos"],
        "confianca": {
            "n_anos": p_algum["n_anos"],
            "largura_ic_p_algum": None if p_algum["p"] is None else p_algum["ic_sup"] - p_algum["ic_inf"],
            "limiares": "PROVISORIO" if "PROVISORIO" in (lc.status, lq.status) else "DEFINIDO",
        },
        "limiares": {
            "chuva_extrema": f"> {lc.valor} {lc.unidade} em {lc.janela_dias} dias ({lc.status})",
            "queda_brusca": f">= {lq.valor} {lq.unidade} em {lq.janela_dias} dias ({lq.status})",
        },
        "referencia": f"{cfg.referencia.ano_inicio}–{cfg.referencia.ano_fim}",
    }


def consultar_coordenada(base: BaseT7, lat: float, lon: float, data_plantio: date, fases: list[dict],
                         fases_enso: pd.Series | None = None, fase_enso_atual: str | None = None) -> dict:
    """Como ``consultar``, mas a partir de latitude e longitude.

    Usa o ponto cuja célula da grade (0,5° x 0,625°) contém a coordenada. Fora dos 20 pontos,
    devolve ``{"status": "fora_da_area"}`` em vez de usar um ponto vizinho.
    """
    ponto = dados.ponto_da_coordenada(lat, lon, base.pontos)
    if ponto is None:
        return {"status": "fora_da_area", "lat": lat, "lon": lon, "celula": dados.celula_grade(lat, lon)}
    return consultar(base, ponto, data_plantio, fases, fases_enso, fase_enso_atual)
