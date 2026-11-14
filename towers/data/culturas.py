"""Catálogo de culturas: ECOCROP + lista de culturas obrigatórias + nomes brasileiros.

É a entrada das torres. Uma linha por **cultura** (não por espécie): a mesma espécie pode virar
mais de uma cultura (ex.: sorgo granífero e sorgo forrageiro), com nome e tipo de colheita próprios.

Camadas de informação, da mais confiável para a menos:

1. ``culturas_obrigatorias.csv`` (curado, versionado): ~150 culturas que o Brasil planta.
   Garante nome, tipo de colheita, uso e modo; readmite espécies que o filtro de categoria
   descartaria e aponta as que não existem no ECOCROP.
2. ``culturas_extra.csv`` (curado): parâmetros climáticos de culturas ausentes do ECOCROP,
   com a fonte de cada valor (ou a espécie usada como aproximação).
3. Demais espécies do ECOCROP com nome popular brasileiro no GBIF (Flora e Funga do Brasil).

Regra de exibição (o usuário final nunca vê nome científico nem nome vazio):
``exibivel = nome_pt definido e colheita ∈ {reprodutiva, vegetativa}``.
"""
from __future__ import annotations

import logging
from pathlib import Path

import polars as pl

from .ecocrop import ler_ecocrop_bruto, carregar_ecocrop, separar_nome
from .taxonomia import CACHE_PADRAO as CACHE_GBIF, nomes_pt_brasil, slug

log = logging.getLogger(__name__)

AQUI = Path(__file__).resolve().parent
CAMINHO_OBRIGATORIAS = AQUI / "culturas_obrigatorias.csv"
CAMINHO_EXTRA = AQUI / "culturas_extra.csv"

PARAMS_EXTRA = ["TMIN", "TOPMN", "TOPMX", "TMAX", "KTMP", "RMIN", "ROPMN", "ROPMX", "RMAX", "GMIN", "GMAX"]
COLHEITAS_VALIDAS = ("reprodutiva", "vegetativa")


def ler_obrigatorias(caminho: Path | str = CAMINHO_OBRIGATORIAS) -> pl.DataFrame:
    df = pl.read_csv(caminho)
    erros = []
    if not df["nome_pt"].is_unique().all():
        erros.append(f"nome_pt repetido: {df.filter(pl.col('nome_pt').is_duplicated())['nome_pt'].to_list()}")
    if df["especie_ecocrop"].null_count():
        erros.append(f"sem especie_ecocrop: {df.filter(pl.col('especie_ecocrop').is_null())['nome_pt'].to_list()}")
    if invalidas := set(df["colheita"].unique()) - set(COLHEITAS_VALIDAS):
        erros.append(f"colheita inválida: {invalidas}")
    if invalidos := set(df["uso"].unique()) - {"agricultura", "silvicultura"}:
        erros.append(f"uso inválido: {invalidos}")
    if invalidos := set(df["modo"].drop_nulls().unique()) - {"safra", "implantacao"}:
        erros.append(f"modo inválido: {invalidos}")
    # a mesma espécie não pode ter dois modos forçados diferentes
    conflito = df.drop_nulls("modo").group_by("especie_ecocrop").agg(pl.col("modo").n_unique()).filter(pl.col("modo") > 1)
    if conflito.height:
        erros.append(f"modo conflitante para: {conflito['especie_ecocrop'].to_list()}")
    if erros:
        raise ValueError("culturas_obrigatorias.csv inválido:\n- " + "\n- ".join(erros))
    return df.with_columns(especie_ecocrop=pl.col("especie_ecocrop").map_elements(
        lambda n: separar_nome(n)[0], return_dtype=pl.String))


def linhas_extra(bruto: pl.DataFrame, caminho: Path | str = CAMINHO_EXTRA) -> pl.DataFrame:
    """Linhas no formato do CSV bruto do ECOCROP para as espécies de ``culturas_extra.csv``.

    Copia a espécie-base (``base_ecocrop``) e sobrescreve os parâmetros preenchidos.
    """
    extra = pl.read_csv(caminho, schema_overrides={c: pl.Int64 for c in PARAMS_EXTRA})
    linhas = []
    for i, r in enumerate(extra.iter_rows(named=True), start=1):
        base = bruto.filter(pl.col("ScientificName") == r["base_ecocrop"])
        if base.height != 1:
            raise ValueError(f"culturas_extra: base_ecocrop {r['base_ecocrop']!r} não encontrada no ECOCROP")
        nova = base.row(0, named=True) | {
            "EcoPortCode": -i, "ScientificName": r["especie"], "COMNAME": None, "SYNO": None, "AUTH": None,
            "fonte_parametros": r["fonte_parametros"],
        }
        nova |= {c: r[c] for c in PARAMS_EXTRA if r[c] is not None}
        linhas.append(nova)
    return pl.DataFrame(linhas, schema=bruto.schema | {"fonte_parametros": pl.String})


def carregar_culturas(usar_gbif: bool = True, cache_gbif: Path | str = CACHE_GBIF,
                      caminho_obrigatorias: Path | str = CAMINHO_OBRIGATORIAS,
                      caminho_extra: Path | str = CAMINHO_EXTRA) -> pl.DataFrame:
    """Catálogo completo (inclusive não exibíveis, com ``exibivel`` = False)."""
    obrig = ler_obrigatorias(caminho_obrigatorias)
    extras = linhas_extra(ler_ecocrop_bruto(), caminho_extra)
    modo_forcado = dict(obrig.drop_nulls("modo").select("especie_ecocrop", "modo").unique().iter_rows())

    eco = carregar_ecocrop(readmitir=obrig["especie_ecocrop"].to_list(), modo_forcado=modo_forcado, extras=extras)

    faltando = set(obrig["especie_ecocrop"]) - set(eco["especie"])
    if faltando:
        raise ValueError(f"culturas obrigatórias sem parâmetros válidos no ECOCROP/extra: {sorted(faltando)}")

    # 1) Culturas obrigatórias: dados curados sobrescrevem os derivados do ECOCROP.
    curadas = (
        obrig.select(
            "nome_pt", pl.col("especie_ecocrop").alias("especie"), pl.col("colheita").alias("_colheita"),
            pl.col("uso").alias("_uso"), pl.col("fonte").alias("fonte_inclusao"), "observacao",
        )
        .join(eco, on="especie", how="left")
        .with_columns(
            colheita=pl.col("_colheita"), uso=pl.col("_uso"),
            colheita_origem=pl.lit("curada"), nome_pt_origem=pl.lit("curado"), obrigatoria=pl.lit(True),
            nomes_pt_alternativos=pl.lit(None, dtype=pl.List(pl.String)),
        )
        .drop("_colheita", "_uso")
    )

    # 2) Demais espécies: nome brasileiro do GBIF.
    resto = eco.filter(~pl.col("especie").is_in(obrig["especie_ecocrop"].to_list())).with_columns(
        obrigatoria=pl.lit(False), fonte_inclusao=pl.lit("ECOCROP"), observacao=pl.lit(None, dtype=pl.String),
    )
    if usar_gbif:
        nomes = nomes_pt_brasil(resto["especie"].to_list(), cache=cache_gbif)
        resto = resto.join(nomes.select("especie", "nome_pt", "nomes_pt_alternativos"), on="especie", how="left")
    else:
        resto = resto.with_columns(nome_pt=pl.lit(None, dtype=pl.String),
                                   nomes_pt_alternativos=pl.lit(None, dtype=pl.List(pl.String)))
    resto = resto.with_columns(
        nome_pt_origem=pl.when(pl.col("nome_pt").is_not_null()).then(pl.lit("gbif_flora_brasil")),
    )

    # 3) Subespécies (ssp.) sem nome herdam o nome da cultura do binômio (ex.: raças de abacate → "Abacate").
    #    Variedades (var.) não herdam: costumam ser produtos diferentes (repolho × brócolis).
    nome_do_grupo = dict(
        curadas.group_by("especie").agg(pl.col("nome_pt"), pl.len())
        .filter(pl.col("len") == 1).select("especie", pl.col("nome_pt").list.first()).iter_rows()
    )
    resto = resto.with_columns(
        _herda=pl.col("nome_pt").is_null() & pl.col("variante").fill_null("").str.starts_with("ssp."),
    ).with_columns(
        nome_pt=pl.when("_herda").then(pl.col("binomio").replace_strict(nome_do_grupo, default=None, return_dtype=pl.String))
        .otherwise(pl.col("nome_pt")),
    ).with_columns(
        nome_pt_origem=pl.when(pl.col("_herda") & pl.col("nome_pt").is_not_null()).then(pl.lit("grupo"))
        .otherwise(pl.col("nome_pt_origem")),
    ).drop("_herda")

    # 4) Nomes repetidos: o usuário não pode ver duas culturas com o mesmo nome.
    resto = _resolver_conflitos_de_nome(resto, set(curadas["nome_pt"].to_list()))

    df = pl.concat([curadas, resto], how="diagonal_relaxed").with_columns(
        exibivel=pl.col("nome_pt").is_not_null() & pl.col("colheita").is_in(COLHEITAS_VALIDAS),
    )

    # Identificador estável da cultura: slug do nome; se repetido, acrescenta a espécie.
    base = [slug(n) if n else slug(e) for n, e in zip(df["nome_pt"].to_list(), df["especie"].to_list())]
    repetidos = {b for b in base if base.count(b) > 1}
    ids = [f"{b}--{slug(e)}" if b in repetidos else b for b, e in zip(base, df["especie"].to_list())]
    df = df.with_columns(id_cultura=pl.Series(ids)).select("id_cultura", pl.exclude("id_cultura"))

    log.info(
        "Culturas: %d no catálogo, %d exibíveis (%d obrigatórias, %d com nome do GBIF, %d herdados do grupo)",
        df.height, df["exibivel"].sum(), df["obrigatoria"].sum(),
        df.filter(pl.col("exibivel") & (pl.col("nome_pt_origem") == "gbif_flora_brasil")).height,
        df.filter(pl.col("exibivel") & (pl.col("nome_pt_origem") == "grupo")).height,
    )
    return df


def _resolver_conflitos_de_nome(resto: pl.DataFrame, nomes_curados: set[str]) -> pl.DataFrame:
    """Garante nomes únicos entre as culturas exibíveis.

    - Nome curado sempre vence. Subespécies que herdaram o nome do grupo podem repeti-lo (são
      agrupadas na interface como variantes da mesma cultura).
    - Espécie do GBIF em conflito usa o primeiro nome alternativo livre; sem alternativa, perde o
      nome (``conflito_nome`` = True) e sai da exibição.
    - Na disputa entre espécies do GBIF, a mais cultivada escolhe primeiro
      (larga escala → pequena escala → demais).
    """
    ocupados = {n.casefold() for n in nomes_curados}
    prioridade = (
        pl.when(pl.col("PLAT").fill_null("").str.contains("large scale")).then(0)
        .when(pl.col("PLAT").fill_null("").str.contains("small scale")).then(1).otherwise(2)
    )
    resto = resto.with_row_index("_i").with_columns(_prio=prioridade)
    candidatos = resto.filter(
        (pl.col("nome_pt_origem") == "gbif_flora_brasil") & pl.col("colheita").is_in(COLHEITAS_VALIDAS)
    ).sort("_prio", "especie")

    novo_nome, conflito = {}, set()
    for i, nome, alternativos in candidatos.select("_i", "nome_pt", "nomes_pt_alternativos").iter_rows():
        escolhido = next((n for n in [nome, *(alternativos or [])] if n.casefold() not in ocupados), None)
        if escolhido is None:
            conflito.add(i)
        else:
            ocupados.add(escolhido.casefold())
            if escolhido != nome:
                novo_nome[i] = escolhido

    return resto.with_columns(
        conflito_nome=pl.col("_i").is_in(list(conflito)),
        nome_pt=pl.when(pl.col("_i").is_in(list(conflito))).then(None)
        .otherwise(pl.col("_i").replace_strict(novo_nome, default=pl.col("nome_pt"), return_dtype=pl.String)),
    ).with_columns(
        nome_pt_origem=pl.when(pl.col("nome_pt").is_null()).then(None).otherwise(pl.col("nome_pt_origem")),
    ).drop("_i", "_prio")


def culturas_exibiveis(df: pl.DataFrame, incluir_silvicultura: bool = True) -> pl.DataFrame:
    """Culturas que podem aparecer para o usuário. Silvicultura ligada por padrão (filtro para desligar)."""
    out = df.filter("exibivel")
    if not incluir_silvicultura:
        out = out.filter(pl.col("uso") != "silvicultura")
    return out


def relatorio_excluidas(df: pl.DataFrame) -> pl.DataFrame:
    """Espécies fora da exibição e o motivo (para a equipe revisar e promover à lista obrigatória)."""
    return df.filter(~pl.col("exibivel")).select(
        "especie", "CAT", "PLAT",
        motivo=pl.when(pl.col("conflito_nome").fill_null(False)).then(pl.lit("nome repetido"))
        .when(pl.col("nome_pt").is_null() & ~pl.col("colheita").is_in(COLHEITAS_VALIDAS))
        .then(pl.lit("sem nome brasileiro e colheita indefinida"))
        .when(pl.col("nome_pt").is_null()).then(pl.lit("sem nome brasileiro"))
        .otherwise(pl.lit("colheita indefinida")),
    ).sort("motivo", "especie")
