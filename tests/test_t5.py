"""Testes da Torre 5 (rotação), com catálogo sintético."""
import polars as pl
import pytest

from towers.t5_rotacao import avaliar_t5
from towers.t5_rotacao.regras import BASE, REGRAS
from towers.t5_rotacao.torre import ajustes_rotacao, familia, resolver_cultura

LEG = "Magnoliopsida:Rosidae:Fabales:Leguminosae"
GRA = "Liliopsida:Commelinidae:Cyperales:Gramineae"
AST = "Magnoliopsida:Asteridae:Asterales:Compositae"


def c(id_c, nome, especie, fam, modo="safra", uso="agricultura", alt=None):
    return {"id_cultura": id_c, "nome_pt": nome, "especie": especie, "familia": fam, "modo": modo, "uso": uso,
            "obrigatoria": True, "escala_cultivo": 0, "nomes_pt_alternativos": alt or []}


CAT = pl.DataFrame([
    c("soja", "Soja", "Glycine max", LEG),
    c("feijao", "Feijão", "Phaseolus vulgaris", LEG),
    c("milho", "Milho", "Zea mays", GRA, alt=["Milho-grão"]),
    c("trigo", "Trigo", "Triticum aestivum", GRA),
    c("girassol", "Girassol", "Helianthus annuus", AST),
    c("aveia-preta", "Aveia-preta", "Avena strigosa", GRA),
    c("cafe", "Café", "Coffea arabica", "Magnoliopsida:Asteridae:Rubiales:Rubiaceae", modo="implantacao"),
    c("eucalipto", "Eucalipto", "Eucalyptus grandis", "x:Myrtaceae", modo="implantacao", uso="silvicultura"),
])


def score(atual, ultimo=None, penultimo=None):
    r = avaliar_t5(ultimo, penultimo, culturas=CAT, colapsar_variantes=False)
    return r.filter(pl.col("id_cultura") == atual).row(0, named=True)


def test_familia_normalizada():
    assert familia(LEG) == "Fabaceae" and familia(GRA) == "Poaceae" and familia(None) is None


def test_resolver_por_id_nome_e_alternativo():
    assert resolver_cultura("milho", CAT)["id_cultura"] == "milho"
    assert resolver_cultura("FEIJAO", CAT)["id_cultura"] == "feijao"          # sem acento e maiúsculas
    assert resolver_cultura("Milho-grão", CAT)["id_cultura"] == "milho"
    assert resolver_cultura("pousio", CAT)["id_cultura"] == "pousio"
    with pytest.raises(ValueError):
        resolver_cultura("Couve-de-marte", CAT)


def test_milho_apos_soja_e_bonificado():
    r = score("milho", ultimo="Soja")
    assert r["regras_rotacao"] == ["leguminosa_graminea"]
    assert r["score_t5"] == pytest.approx(BASE + REGRAS["leguminosa_graminea"][0])


def test_soja_apos_soja_apos_soja_e_penalizada():
    r = score("soja", ultimo="Soja", penultimo="Soja")
    assert set(r["regras_rotacao"]) == {"monocultura", "monocultura_2"}
    assert r["score_t5"] == pytest.approx(BASE - 0.25 - 0.20)


def test_feijao_apos_soja_mesma_familia_e_mofo_branco():
    r = score("feijao", ultimo="Soja")
    assert set(r["regras_rotacao"]) == {"mesma_familia", "mofo_branco"}
    assert r["score_t5"] < BASE


def test_girassol_apos_soja_mofo_branco_mas_recebe_nitrogenio():
    r = score("girassol", ultimo="Soja")
    assert set(r["regras_rotacao"]) == {"leguminosa_outra", "mofo_branco"}


def test_soja_apos_milho_palhada_e_apos_cobertura():
    assert score("soja", ultimo="Milho")["regras_rotacao"] == ["apos_graminea"]
    assert set(score("soja", ultimo="Aveia-preta")["regras_rotacao"]) == {"apos_graminea", "cobertura"}


def test_trigo_apos_milho_mesma_familia():
    assert score("trigo", ultimo="Milho")["regras_rotacao"] == ["mesma_familia"]


def test_pousio_e_sem_historico():
    assert score("soja", ultimo="pousio")["regras_rotacao"] == ["pousio"]
    sem = score("soja")
    assert sem["score_t5"] is None and not sem["rotacao_aplicavel"]


def test_perenes_e_silvicultura_nao_se_aplicam():
    assert score("cafe", ultimo="Soja")["score_t5"] is None
    assert score("eucalipto", ultimo="Soja")["score_t5"] is None


def test_score_limitado_e_explicado():
    r = avaliar_t5("Soja", "Soja", culturas=CAT, colapsar_variantes=False)
    assert r["score_t5"].drop_nulls().is_between(0, 1).all()
    soja = r.filter(pl.col("id_cultura") == "soja").row(0, named=True)
    assert len(soja["explicacao_rotacao"]) == 2 and soja["historico"] == "Soja → Soja"
    assert r["score_t5"].tail(2).null_count() == 2          # nulos por último
