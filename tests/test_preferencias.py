"""Aderência ao produtor (objetivos, problemas e cultura desejada) e justificativas dos cartões."""
from datetime import date

import polars as pl
import pytest

import motor as mt
from towers.combinador import combinar, ordenar
from towers.combinador.preferencias import BONUS_DESEJADA, PESO_ADERENCIA, aderencia

LEG = "Magnoliopsida:Rosidae:Fabales:Leguminosae"
GRA = "Liliopsida:Commelinidae:Cyperales:Gramineae"
SOL = "Magnoliopsida:Asteridae:Solanales:Solanaceae"
D = date(2026, 11, 20)


def cult(id_c, nome, fam, tipo="graos", modo="safra", uso="agricultura"):
    return {"id_cultura": id_c, "nome_pt": nome, "familia": fam, "tipo_cultura": tipo, "modo": modo, "uso": uso}


CAT = pl.DataFrame([
    cult("soja", "Soja", LEG), cult("crotalaria", "Crotalária", LEG, "forrageiras"),
    cult("milho", "Milho", GRA), cult("milheto", "Milheto", GRA, "forrageiras"),
    cult("tomate", "Tomate", SOL, "hortalicas"),
])


def ader(pedidos, historico=()):
    return {r["id_cultura"]: r for r in aderencia(CAT, pedidos, list(historico)).iter_rows(named=True)}


def test_nitrogenio_favorece_leguminosas():
    a = ader({"fixar_nitrogenio": 1})
    assert a["crotalaria"]["aderencia"] == 1.0 and a["soja"]["aderencia"] == 0.7
    assert a["milho"]["aderencia"] == 0.0 and a["milho"]["beneficios_nao_atendidos"] == ["fixar_nitrogenio"]


def test_compactacao_favorece_raizes_agressivas():
    a = ader({"descompactar": 1})
    assert a["milheto"]["aderencia"] == 1.0 > a["milho"]["aderencia"] == 0.5 > a["tomate"]["aderencia"]
    assert a["milho"]["beneficios_parciais"] == ["descompactar"]


def test_doencas_dependem_do_historico():
    soja = CAT.row(0, named=True)
    a = ader({"controlar_doencas": 1}, [soja, soja])
    assert a["soja"]["aderencia"] == 0.0 and a["crotalaria"]["aderencia"] == 0.0   # mesma família
    assert a["milho"]["aderencia"] == 1.0
    assert ader({"controlar_doencas": 1})["milho"]["aderencia"] == 0.5              # sem histórico: neutro


def test_pedidos_ponderados_e_invalidos():
    a = ader({"fixar_nitrogenio": 2, "controlar_daninhas": 1})
    assert a["crotalaria"]["aderencia"] == pytest.approx(1.0)
    assert a["milheto"]["aderencia"] == pytest.approx(1 / 3)
    with pytest.raises(ValueError):
        ader({"ficar_rico": 1})


def t1_(nomes_scores):
    return pl.DataFrame([{"id_cultura": i, "nome_pt": n, "plantio": D, "score_t1": s, "apt_p20": s, "gate_t1": g,
                          "uso": "agricultura", "modo": "safra", "colheita": "reprodutiva", "obrigatoria": True,
                          "escala_cultivo": 0, "fator_limitante": "chuva", "ciclo_dias": 120,
                          "alerta_foto_mensagem": None, "alerta_ciclo_extremo": False}
                         for i, n, s, g in nomes_scores])


def test_aderencia_e_desejada_mudam_o_ranking():
    t1 = t1_([("milho", "Milho", 0.9, True), ("crotalaria", "Crotalária", 0.75, True),
              ("tomate", "Tomate", 0.7, True), ("soja", "Soja", 0.3, False)])
    sem = ordenar(combinar(t1, peso_evidencia=0))
    assert sem["nome_pt"].to_list()[:2] == ["Milho", "Crotalária"]

    a = aderencia(CAT, {"fixar_nitrogenio": 1})
    com = combinar(t1, peso_evidencia=0, aderencia=a)
    r = {x["id_cultura"]: x for x in com.iter_rows(named=True)}
    assert r["milho"]["score_final"] == pytest.approx(0.9 * (1 - PESO_ADERENCIA))
    assert r["crotalaria"]["score_final"] == pytest.approx(0.75) and r["milho"]["score_agronomico"] == pytest.approx(0.9)
    assert ordenar(com)["nome_pt"][0] == "Crotalária"

    com = combinar(t1, peso_evidencia=0, desejada="Tomate")
    r = {x["id_cultura"]: x for x in com.iter_rows(named=True)}
    assert r["tomate"]["score_final"] == pytest.approx(0.7 + BONUS_DESEJADA * 0.3) and r["tomate"]["desejada"]
    com = combinar(t1, peso_evidencia=0, desejada="Soja")                 # eliminada: sem bônus
    assert com.filter(pl.col("id_cultura") == "soja")["score_final"][0] == 0.0


def test_beneficios_da_entrada():
    e = mt.Entrada(objetivos=["Aumentar nitrogênio", "Aumentar produtividade"],
                   problemas=["Deficiência de nitrogênio", "Plantas daninhas"])
    assert mt.beneficios_da_entrada(e) == {"fixar_nitrogenio": 2.0, "controlar_daninhas": 1.0}
    assert set(mt.OBJETIVO_PARA_BENEFICIO) <= set(mt.OBJETIVOS)
    assert set(mt.PROBLEMA_PARA_BENEFICIO) == set(mt.PROBLEMAS)


def test_cartao_responde_a_cada_informacao_do_produtor():
    e = mt.Entrada(penultimo="Milho", ultimo="Soja", uf="GO", cidade="Rio Verde", data_plantio=D,
                   objetivos=["Aumentar nitrogênio", "Reduzir compactação", "Acesso a crédito e seguro"],
                   problemas=["Presença de pragas"], cultura_desejada="Soja")
    linha = dict(id_cultura="soja", nome_pt="Soja", plantio=date(2026, 11, 30), ciclo_dias=120, score_final=0.8,
                 tipo_cultura="graos", eliminada=False, desejada=True, s_t1=0.9, s_t2=0.9, s_t3=0.9, s_t5=0.55,
                 beneficios_atendidos=["fixar_nitrogenio"], beneficios_parciais=["descompactar"],
                 beneficios_nao_atendidos=["controlar_pragas"], alertas_solo=[],
                 explicacao_rotacao=["Mesma cultura da safra anterior (-0.25): acúmulo de pragas"],
                 status_elegibilidade="elegivel", portaria_zarc="Port.1", zarc_status="indicado", risco_zarc_pct=20)
    m = mt._recomendacao_de_linha(linha, {}, e).motivos
    assert m[0] == "Sua cultura desejada (Soja): ganhou prioridade no ranking e é viável no local."
    assert m[1] == "Seu objetivo “aumentar nitrogênio”: atende, fixa nitrogênio no solo."
    assert m[2].startswith("Seu objetivo “reduzir compactação”: atende em parte")
    assert m[3].startswith("Seu objetivo “manter acesso a crédito e seguro”: dentro do zoneamento oficial")
    assert m[4] == ("Problema informado “presença de pragas”: não ajuda; para isso, prefira crotalária ou mucuna "
                    "(reduzem nematoides) ou uma cultura de outra família.")
    assert m[5] == "Seu histórico (Milho → Soja): Soja entra como mesma cultura da safra anterior (acúmulo de pragas)."
    assert m[6].startswith("Na data que você informou (20/11): o melhor plantio é em 30/11, 10 dias depois; "
                           "clima muito favorável")
    assert m[7] == "Em Rio Verde-GO: solo adequado para Soja."
    assert not any(x.startswith("Crédito e seguro") for x in m)      # já respondido no objetivo


def test_outras_culturas_comparadas_com_a_desejada():
    e = mt.Entrada(cultura_desejada="Soja", data_plantio=D)
    desejada = {"nome_pt": "Soja", "score_final": 0.6, "eliminada": False, "pontos_fracos": ["água"]}
    linha = dict(id_cultura="milho", nome_pt="Milho", plantio=D, score_final=0.85, eliminada=False)
    m = mt._recomendacao_de_linha(linha, {}, e, {"desejada": desejada}).motivos
    assert m[0] == "Sua cultura desejada (Soja): nota 60 contra 85 de Milho; Soja perde em água."
