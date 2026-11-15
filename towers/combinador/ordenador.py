"""Ordenador: melhor data por cultura, ranking e setores (melhores, intermediárias, piores).

- Para cada cultura (nome exibido), fica a melhor combinação de variante × data de plantio.
- Ranking: score_final ↓, depois mais torres com score (confiança) ↓, depois escala de cultivo ↑.
- Setores (``top_n`` cada, padrão 3):
  * ``melhores``: as primeiras entre as não eliminadas;
  * ``intermediarias``: as ``top_n`` em torno da mediana das não eliminadas;
  * ``piores``: as últimas de todo o ranking (inclui eliminadas, com o motivo).
  Os setores não se sobrepõem; com poucas culturas, os intermediários podem ficar menores.
- A cultura desejada pelo produtor sempre é reportada, com posição e setor.
"""
from __future__ import annotations

import polars as pl

LIMIAR_FORTE, LIMIAR_FRACO = 0.8, 0.5
NOMES_TORRES = {"t1": "clima", "t2": "água", "t3": "solo", "t4": "zoneamento (ZARC)", "t5": "rotação",
                "t7": "extremos climáticos"}


def melhor_por_cultura(comb: pl.DataFrame) -> pl.DataFrame:
    return (
        comb.sort(["score_final", "torres_com_score", "escala_cultivo"], descending=[True, True, False], nulls_last=True)
        .group_by("nome_pt", maintain_order=True)
        .agg(pl.all().first(), datas_avaliadas=pl.col("plantio").n_unique(),
             outras_datas_boas=pl.col("plantio").filter(
                 (pl.col("score_final") >= pl.col("score_final").max() - 0.05) & ~pl.col("eliminada")).sort().slice(0, 5))
    )


def _explicar(df: pl.DataFrame) -> pl.DataFrame:
    torres = [t for t in NOMES_TORRES if f"s_{t}" in df.columns]
    fortes = [pl.when(pl.col(f"s_{t}") >= LIMIAR_FORTE).then(pl.lit(NOMES_TORRES[t])) for t in torres]
    fracos = [pl.when(pl.col(f"s_{t}") <= LIMIAR_FRACO).then(pl.lit(NOMES_TORRES[t])) for t in torres]
    return df.with_columns(
        pontos_fortes=pl.concat_list(fortes).list.drop_nulls(),
        pontos_fracos=pl.concat_list(fracos).list.drop_nulls(),
    )


def ordenar(comb: pl.DataFrame) -> pl.DataFrame:
    """Ranking completo, uma linha por cultura, com posição e explicação."""
    r = melhor_por_cultura(comb).sort(
        ["eliminada", "score_final", "torres_com_score", "escala_cultivo"],
        descending=[False, True, True, False], nulls_last=True,
    ).with_row_index("posicao", offset=1)
    return _explicar(r)


def setores(ranking: pl.DataFrame, top_n: int = 3, universo_piores: pl.Expr | None = None) -> dict[str, pl.DataFrame]:
    """``universo_piores``: restringe os piores a culturas relevantes (ex.: ``pl.col("obrigatoria")``), para não
    listar espécies exóticas que o produtor nunca consideraria."""
    viaveis = ranking.filter(~pl.col("eliminada"))
    melhores = viaveis.head(top_n)
    usados = set(melhores["nome_pt"])
    base_piores = ranking if universo_piores is None else ranking.filter(universo_piores)
    piores = base_piores.filter(~pl.col("nome_pt").is_in(list(usados))).tail(top_n).reverse()
    usados |= set(piores["nome_pt"])
    meio = viaveis.filter(~pl.col("nome_pt").is_in(list(usados)))
    if meio.height:
        c = meio.height // 2
        ini = max(0, min(c - top_n // 2, meio.height - top_n))
        intermediarias = meio.slice(ini, top_n)
    else:
        intermediarias = meio
    return {"melhores": melhores, "intermediarias": intermediarias, "piores": piores}


def localizar(ranking: pl.DataFrame, nome_pt: str, setores_: dict[str, pl.DataFrame]) -> dict | None:
    linha = ranking.filter(pl.col("nome_pt") == nome_pt)
    if linha.is_empty():
        return None
    r = linha.row(0, named=True)
    setor = next((s for s, df in setores_.items() if nome_pt in df["nome_pt"].to_list()), None)
    if setor is None:
        setor = "eliminada" if r["eliminada"] else "fora_dos_setores"
    return r | {"setor": setor, "total_culturas": ranking.height}
