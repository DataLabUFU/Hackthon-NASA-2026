"""Torre 5: rotação de culturas (histórico das duas últimas safras).

    avaliar_t5(ultimo="Soja", penultimo="Milho") → uma linha por cultura

- Entradas: a cultura da última e da penúltima safra (nome em português, id do catálogo ou "pousio").
- Score = BASE (0,75) + ajustes das regras (``regras.py``), limitado a [0, 1].
- Não se aplica (score nulo, neutro no combinador): culturas perenes e silvicultura (a decisão não é de
  rotação) e quando o produtor não informa o histórico.
- Não depende da data de plantio nem das outras torres.
"""
from __future__ import annotations

import logging
import unicodedata

import polars as pl

from towers.data.culturas import carregar_culturas, culturas_exibiveis

from .regras import BASE, COBERTURAS, FAMILIA_ATUAL, HOSPEDEIROS_MOFO_BRANCO, POUSIO, REGRAS

log = logging.getLogger(__name__)


def _norm(t: str) -> str:
    return unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode().casefold().strip()


def familia(fam: str | None) -> str | None:
    if not fam:
        return None
    nome = fam.split(":")[-1].strip()
    return FAMILIA_ATUAL.get(nome, nome)


def resolver_cultura(nome: str | None, catalogo: pl.DataFrame) -> dict | None:
    """Acha a cultura informada pelo produtor (id, nome em português ou nome alternativo)."""
    if nome is None or not str(nome).strip():
        return None
    alvo = _norm(nome)
    if alvo in POUSIO:
        return {"id_cultura": "pousio", "nome_pt": "Pousio", "especie": None, "familia": None}
    for r in catalogo.iter_rows(named=True):
        nomes = [r["id_cultura"], r["nome_pt"] or "", *(r.get("nomes_pt_alternativos") or [])]
        if alvo in {_norm(n) for n in nomes if n}:
            return r
    raise ValueError(f"cultura do histórico não encontrada no catálogo: {nome!r}")


def ajustes_rotacao(atual: dict, ultimo: dict | None, penultimo: dict | None) -> list[str]:
    """Códigos das regras que se aplicam a plantar ``atual`` depois de ``ultimo`` e ``penultimo``."""
    if ultimo is None:
        return []
    if ultimo["id_cultura"] == "pousio":
        return ["pousio"]
    regras = []
    fa, fu = familia(atual.get("familia")), familia(ultimo.get("familia"))
    fp = familia(penultimo.get("familia")) if penultimo else None
    mesma = atual["especie"] == ultimo["especie"]
    if mesma:
        regras.append("monocultura")
        if penultimo and penultimo.get("especie") == atual["especie"]:
            regras.append("monocultura_2")
    elif fa and fa == fu:
        regras.append("mesma_familia")
    if penultimo and not mesma and penultimo.get("especie") != atual["especie"] and fa and fa == fp:
        regras.append("mesma_familia_2")
    if fu == "Fabaceae" and fa != "Fabaceae":
        regras.append("leguminosa_graminea" if fa == "Poaceae" else "leguminosa_outra")
    if fu == "Poaceae" and fa != "Poaceae":
        regras.append("apos_graminea")
    if ultimo["id_cultura"] in COBERTURAS and not mesma:
        regras.append("cobertura")
    if (not mesma and atual["id_cultura"] in HOSPEDEIROS_MOFO_BRANCO
            and ultimo["id_cultura"] in HOSPEDEIROS_MOFO_BRANCO):
        regras.append("mofo_branco")
    return regras


def avaliar_t5(ultimo: str | None = None, penultimo: str | None = None, culturas: pl.DataFrame | None = None,
               catalogo_historico: pl.DataFrame | None = None,
               incluir_silvicultura: bool = True, colapsar_variantes: bool = True) -> pl.DataFrame:
    """Score da T5 (rotação) para todas as culturas exibíveis, ordenado."""
    # ``culturas`` pode vir filtrada por tipo (o que se recomenda); o histórico (o que já se plantou) é procurado
    # em ``catalogo_historico`` ou, sem ele, no catálogo completo
    catalogo_completo = carregar_culturas().filter("exibivel") if culturas is None else culturas
    catalogo_historico = catalogo_historico if catalogo_historico is not None else (
        catalogo_completo if culturas is None else carregar_culturas().filter("exibivel"))
    if culturas is None:
        culturas = culturas_exibiveis(catalogo_completo, incluir_silvicultura=incluir_silvicultura)
    u = resolver_cultura(ultimo, catalogo_historico)
    pu = resolver_cultura(penultimo, catalogo_historico)

    linhas = []
    for r in culturas.iter_rows(named=True):
        aplicavel = u is not None and r["modo"] == "safra" and r["uso"] != "silvicultura"
        regras = ajustes_rotacao(r, u, pu) if aplicavel else []
        score = min(1.0, max(0.0, BASE + sum(REGRAS[c][0] for c in regras))) if aplicavel else None
        linhas.append({
            "id_cultura": r["id_cultura"], "score_t5": score, "rotacao_aplicavel": aplicavel,
            "regras_rotacao": regras,
            "explicacao_rotacao": [f"{REGRAS[c][1]} ({REGRAS[c][0]:+.2f}): {REGRAS[c][2]}" for c in regras],
        })
    res = pl.DataFrame(linhas, schema_overrides={"score_t5": pl.Float64}).join(
        culturas.select("id_cultura", "nome_pt", "uso", "modo", "familia", "obrigatoria", "escala_cultivo"),
        on="id_cultura",
    ).with_columns(
        familia=pl.col("familia").map_elements(familia, return_dtype=pl.String),
        historico=pl.lit(" → ".join(x["nome_pt"] for x in (pu, u) if x) or None, dtype=pl.String),
    )
    ordenar = dict(by=["score_t5", "escala_cultivo", "nome_pt"], descending=[True, False, False], nulls_last=True)
    res = res.sort(**ordenar).with_columns(n_variantes=pl.len().over("nome_pt"))
    if colapsar_variantes:
        res = res.group_by("nome_pt", maintain_order=True).first()
    ordem = ["id_cultura", "nome_pt", "uso", "modo", "familia", "score_t5", "rotacao_aplicavel", "regras_rotacao",
             "explicacao_rotacao", "historico", "n_variantes", "obrigatoria", "escala_cultivo"]
    return res.select(ordem).sort(**ordenar)
