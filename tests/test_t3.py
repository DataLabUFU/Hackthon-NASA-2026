"""Testes da Torre 3 (solo), sem rede: o SoilGrids é injetado."""
import polars as pl
import pytest

from towers.t3_solo import avaliar_t3
from towers.t3_solo.aptidao import aptidao_solo
from towers.t3_solo.perfil import classe_fertilidade, classe_textural, perfil_solo

LATOSSOLO_ACIDO = {
    "textura": {"areia": 19.0, "silte": 27.0, "argila": 54.0},
    "quimica": {"ph": 4.7, "ctc": 9.0, "carbono_organico": 20.0, "densidade": 1.2},
    "classe": {"wrb": "Ferralsols", "wrb_probabilidades": [["Ferralsols", 57]]},
}


def cultura(id_cultura="soja", **extra):
    base = dict(id_cultura=id_cultura, nome_pt=id_cultura.capitalize(), uso="agricultura", modo="safra",
                obrigatoria=True, escala_cultivo=0,
                PHMIN=4.5, PHOPMN=5.5, PHOPMX=6.5, PHMAX=8.0, TEXT="medium, organic", TEXTR="heavy, medium, light",
                DRA="well (dry spells)", DRAR="well (dry spells)", DEP="medium (50-150 cm)", DEPR="shallow (20-50 cm)",
                FER="high", FERR="moderate", SAL="low (<4 dS/m)", SALR="low (<4 dS/m)")
    return base | extra


def cat(*cs):
    return pl.DataFrame(list(cs))


# --- classes ------------------------------------------------------------------------------------

@pytest.mark.parametrize("areia, argila, classe", [(85, 8, "light"), (60, 20, "medium"), (19, 54, "heavy"),
                                                    (40, 35, "heavy"), (72, 15, "medium")])
def test_classe_textural(areia, argila, classe):
    assert classe_textural(areia, argila) == classe


def test_classe_fertilidade():
    assert [classe_fertilidade(v) for v in (3, 4.3, 6, 8.6, 12)] == ["low", "low", "moderate", "moderate", "high"]


# --- perfil -------------------------------------------------------------------------------------

def test_perfil_do_soilgrids():
    p = perfil_solo(0, 0, fontes=LATOSSOLO_ACIDO)
    assert (p["ph"], p["textura"], p["fertilidade"], p["drenagem"], p["profundidade"], p["salinidade"]) == \
        (4.7, "heavy", "high", "well", "deep", "low")
    assert p["estruturado"] and p["origem"]["ph"] == "soilgrids"


def test_produtor_prevalece_sobre_o_mapa():
    p = perfil_solo(0, 0, problemas=["encharcado", "arenoso", "compactado"], analise={"ph": 6.1, "ctc": 3.0},
                    fontes=LATOSSOLO_ACIDO)
    assert p["ph"] == 6.1 and p["origem"]["ph"] == "analise"
    assert p["textura"] == "light" and p["drenagem"] == "poorly" and p["fertilidade"] == "low" and p["compactado"]


def test_problema_acido_sem_analise():
    p = perfil_solo(0, 0, problemas=["acido"], fontes=LATOSSOLO_ACIDO | {"quimica": {**LATOSSOLO_ACIDO["quimica"], "ph": 6.0}})
    assert p["ph"] == 5.0


def test_problema_invalido():
    with pytest.raises(ValueError):
        perfil_solo(0, 0, problemas=["voador"], fontes=LATOSSOLO_ACIDO)


@pytest.mark.parametrize("wrb, drenagem, profundidade, salinidade", [
    ("Gleysols", "poorly", "medium", "low"), ("Leptosols", "well", "shallow", "low"),
    ("Arenosols", "excessive", "deep", "low"), ("Solonchaks", "well", "medium", "high"),
])
def test_atributos_pela_classe_wrb(wrb, drenagem, profundidade, salinidade):
    p = perfil_solo(0, 0, fontes=LATOSSOLO_ACIDO | {"classe": {"wrb": wrb}})
    assert (p["drenagem"], p["profundidade"], p["salinidade"]) == (drenagem, profundidade, salinidade)


def test_sem_dados_do_soilgrids_nao_quebra():
    p = perfil_solo(0, 0, fontes={"textura": None, "quimica": None, "classe": None})
    assert p["ph"] is None and p["textura"] is None and p["drenagem"] == "well" and p["origem"]["drenagem"] == "padrao"
    r = aptidao_solo(cat(cultura()), p).row(0, named=True)
    assert r["score_t3"] == 1.0 and set(r["requisitos_sem_dado"]) >= {"ph", "textura"}


# --- aptidão ------------------------------------------------------------------------------------

def test_acidez_e_corrigivel_com_alerta_de_calagem():
    r = aptidao_solo(cat(cultura()), perfil_solo(0, 0, fontes=LATOSSOLO_ACIDO)).row(0, named=True)
    assert r["s_ph"] == pytest.approx(0.8)          # trapézio daria 0,2; calagem garante o piso
    assert r["corrigivel"] and any("calagem" in a for a in r["alertas_solo"])


def test_alcalino_nao_tem_piso():
    fontes = LATOSSOLO_ACIDO | {"quimica": {**LATOSSOLO_ACIDO["quimica"], "ph": 7.7}}
    r = aptidao_solo(cat(cultura()), perfil_solo(0, 0, fontes=fontes)).row(0, named=True)
    assert r["s_ph"] == pytest.approx(0.2) and r["fator_limitante_solo"] == "ph" and not r["corrigivel"]


def test_latossolo_argiloso_conta_como_textura_media():
    r = aptidao_solo(cat(cultura()), perfil_solo(0, 0, fontes=LATOSSOLO_ACIDO)).row(0, named=True)
    assert r["s_textura"] == 1.0
    sem_estrutura = LATOSSOLO_ACIDO | {"classe": {"wrb": "Vertisols"}}
    r2 = aptidao_solo(cat(cultura()), perfil_solo(0, 0, fontes=sem_estrutura)).row(0, named=True)
    assert r2["s_textura"] == pytest.approx(0.6)


def test_encharcado_derruba_cultura_de_sequeiro_mas_nao_o_arroz():
    p = perfil_solo(0, 0, problemas=["encharcado"], fontes=LATOSSOLO_ACIDO)
    arroz = cultura("arroz", DRA="poorly (saturated >50% of year)", DRAR="poorly (saturated >50% of year), well (dry spells)")
    r = aptidao_solo(cat(cultura(), arroz), p)
    soja, arr = (r.filter(pl.col("id_cultura") == c).row(0, named=True) for c in ("soja", "arroz"))
    assert soja["s_drenagem"] == pytest.approx(0.2) and soja["fator_limitante_solo"] == "drenagem"
    assert arr["s_drenagem"] == 1.0


def test_solo_raso_e_salino():
    p = perfil_solo(0, 0, problemas=["raso", "salino"], fontes=LATOSSOLO_ACIDO)
    funda = cultura("funda", DEP="deep (>>150 cm)", DEPR="medium (50-150 cm)")
    r = aptidao_solo(cat(funda), p).row(0, named=True)
    assert r["s_profundidade"] == pytest.approx(0.2) and r["s_salinidade"] == pytest.approx(0.2)


def test_compactacao_e_fertilidade_sao_corrigiveis():
    p = perfil_solo(0, 0, problemas=["compactado", "pouco_fertil"],
                    fontes=LATOSSOLO_ACIDO | {"quimica": {**LATOSSOLO_ACIDO["quimica"], "ph": 6.0}})
    r = aptidao_solo(cat(cultura()), p).row(0, named=True)
    assert r["score_t3"] == pytest.approx(0.8) and r["corrigivel"]
    assert any("adubação" in a for a in r["alertas_solo"]) and any("compactado" in a for a in r["alertas_solo"])


def test_requisito_ausente_e_neutro():
    r = aptidao_solo(cat(cultura(TEXT=None, TEXTR=None)), perfil_solo(0, 0, fontes=LATOSSOLO_ACIDO)).row(0, named=True)
    assert r["s_textura"] is None and "textura" in r["requisitos_sem_dado"]


def test_avaliar_t3_ponta_a_ponta():
    culturas = cat(cultura("soja", nome_pt="Soja"), cultura("cafe", nome_pt="Café", PHMAX=7.0, PHOPMX=6.0),
                   cultura("arroz-inundado", nome_pt="Arroz inundado", DRA="poorly (saturated >50% of year)",
                           DRAR="poorly (saturated >50% of year)"))
    r = avaliar_t3(0, 0, culturas=culturas, perfil=perfil_solo(0, 0, fontes=LATOSSOLO_ACIDO))
    assert r.height == 3 and r["score_t3"].to_list() == sorted(r["score_t3"].to_list(), reverse=True)
    assert r.filter(pl.col("nome_pt") == "Arroz inundado")["fator_limitante_solo"].item() == "drenagem"
    assert r["solo_wrb"].unique().to_list() == ["Ferralsols"]


# --- benchmark contra a PAM --------------------------------------------------------------------

def test_auc_e_metricas_do_benchmark():
    from towers.t3_solo.validacao import _auc, metricas
    assert _auc(pl.Series([1.0, 0.8]), pl.Series([0.2, 0.2])) == 1.0
    assert _auc(pl.Series([0.5]), pl.Series([0.5])) == 0.5
    scores = pl.DataFrame({
        "geocodigo": ["1"] * 4, "nome_pt": ["Soja", "Milho", "Arroz", "Café"], "score_t3": [1.0, 0.8, 0.2, 0.2],
        "versao": ["T3"] * 4,
    })
    pam = pl.DataFrame({"geocodigo": ["1", "1", "1"], "nome_pt": ["Soja", "Milho", "Arroz"], "area_ha": [5000.0, 300.0, 50.0]})
    m = metricas(scores, pam).row(0, named=True)
    assert m["pares_cultivados"] == 2                     # arroz tem só 50 ha (< 100)
    assert m["eliminacao_indevida"] == 0.0 and m["score_alto"] == 1.0
    assert m["auc_medio"] == 1.0


def test_mapeamento_pam_aponta_para_culturas_do_catalogo():
    from towers.data.culturas import ler_obrigatorias
    from towers.t3_solo.validacao import PAM_PARA_NOME
    assert set(PAM_PARA_NOME.values()) <= set(ler_obrigatorias()["nome_pt"].to_list())



# --- correções do benchmark contra a PAM -------------------------------------------------------

def test_arroz_aceita_solo_bem_drenado_sequeiro():
    so_inundado = dict(DRA="poorly (saturated >50% of year)", DRAR="poorly (saturated >50% of year)")
    r = aptidao_solo(cat(cultura("arroz", **so_inundado), cultura("outro", **so_inundado)),
                     perfil_solo(0, 0, fontes=LATOSSOLO_ACIDO))
    assert r.filter(pl.col("id_cultura") == "arroz")["s_drenagem"].item() == 1.0
    assert r.filter(pl.col("id_cultura") == "outro")["s_drenagem"].item() == pytest.approx(0.2)


def test_fluvisols_nao_sao_mal_drenados_e_wrb_incerto_e_ignorado():
    p = perfil_solo(0, 0, fontes=LATOSSOLO_ACIDO | {"classe": {"wrb": "Fluvisols", "wrb_probabilidades": [["Fluvisols", 40]]}})
    assert p["drenagem"] == "well"
    incerto = perfil_solo(0, 0, fontes=LATOSSOLO_ACIDO | {"classe": {"wrb": "Gleysols", "wrb_probabilidades": [["Gleysols", 20]]}})
    assert incerto["drenagem"] == "well" and incerto["origem"]["drenagem"] == "padrao"
    certo = perfil_solo(0, 0, fontes=LATOSSOLO_ACIDO | {"classe": {"wrb": "Gleysols", "wrb_probabilidades": [["Gleysols", 45]]}})
    assert certo["drenagem"] == "poorly"


def test_textura_fora_da_faixa_penaliza_sem_eliminar():
    arenosa = cultura("x", TEXT="heavy", TEXTR="heavy")
    p = perfil_solo(0, 0, problemas=["arenoso"], fontes=LATOSSOLO_ACIDO)
    assert aptidao_solo(cat(arenosa), p)["s_textura"].item() == pytest.approx(0.5)
