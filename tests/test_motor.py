"""Testes da integração front ↔ recomendador (motor.py), sem rede: o recomendador é simulado."""
from datetime import date
from types import SimpleNamespace

import polars as pl
import pytest

import motor as mt
from towers.combinador.pesos import OBJETIVOS as PERFIS

D = date(2026, 11, 20)


# --- formulário → pesos e problemas de solo -----------------------------------------------------

def test_sem_objetivos_usa_perfil_equilibrado():
    pesos, so_fin = mt.pesos_da_entrada(mt.Entrada())
    assert pesos == pytest.approx(PERFIS["equilibrado"]["pesos"]) and not so_fin


def test_objetivos_viram_perfis_de_pesos():
    pesos, _ = mt.pesos_da_entrada(mt.Entrada(objetivos=["Reter água"]))
    assert pesos == pytest.approx(PERFIS["evitar_seca"]["pesos"])
    pesos, _ = mt.pesos_da_entrada(mt.Entrada(objetivos=["Reduzir erosão"]))       # objetivos de solo/rotação
    assert pesos == pytest.approx(PERFIS["saude_do_solo"]["pesos"])


def test_combinacao_de_objetivos_e_problemas():
    e = mt.Entrada(objetivos=["Reter água", "Aumentar produtividade"], problemas=["Presença de pragas"])
    pesos, _ = mt.pesos_da_entrada(e)
    esperado = {t: (PERFIS["evitar_seca"]["pesos"][t] + PERFIS["estabilidade"]["pesos"][t]
                    + mt.PESO_PROBLEMA * PERFIS["saude_do_solo"]["pesos"][t]) / (2 + mt.PESO_PROBLEMA)
                for t in esperado_torres()}
    assert pesos == pytest.approx(esperado)
    assert sum(pesos.values()) == pytest.approx(1.0)


def esperado_torres():
    return PERFIS["equilibrado"]["pesos"].keys()


def test_credito_liga_o_filtro_de_financiaveis():
    _, so_fin = mt.pesos_da_entrada(mt.Entrada(objetivos=["Acesso a crédito e seguro"]))
    assert so_fin


def test_problemas_de_solo_sao_mapeados_para_a_t3():
    assert set(mt.PROBLEMA_PARA_SOLO.values()) <= {"compactado", "arenoso", "pouco_fertil"}
    from towers.t3_solo.perfil import PROBLEMAS_VALIDOS
    assert set(mt.PROBLEMA_PARA_SOLO.values()) <= PROBLEMAS_VALIDOS
    assert set(mt.PROBLEMA_PARA_SOLO) <= set(mt.PROBLEMAS) and set(mt.PROBLEMA_PARA_PERFIL) <= set(mt.PROBLEMAS)
    assert set(mt.OBJETIVO_PARA_PERFIL) <= set(mt.OBJETIVOS)


def test_tipos_de_cultura_do_front_iguais_aos_do_catalogo():
    from towers.data.culturas import TIPOS_CULTURA
    assert set(mt.TIPOS_CULTURA) == set(TIPOS_CULTURA)


def test_validar_entrada():
    assert set(mt.validar_entrada(mt.Entrada())) == {"os dois últimos plantios", "a localização", "a data prevista"}
    assert mt.validar_entrada(mt.ENTRADA_DEMO) == []


# --- linha do ranking → card -------------------------------------------------------------------

def linha(**extra):
    base = dict(id_cultura="milho", nome_pt="Milho", plantio=D, ciclo_dias=150, score_final=0.89, tipo_cultura="graos",
                eliminada=False, motivo_eliminacao=None, s_t1=0.95, s_t2=0.7, s_t3=0.8, irrigacao_mm=73.0,
                fator_limitante="chuva", fator_limitante_solo=None, alertas_solo=["calagem: pH 5.2 abaixo do ideal"],
                zarc_status="indicado", risco_zarc_pct=20, explicacao_rotacao=["Gramínea após leguminosa (+0.15): N residual"],
                status_elegibilidade="elegivel", portaria_zarc="Port.344_de_06-08-2026", alerta_foto_mensagem=None,
                alerta_ciclo_extremo=False, outras_datas_boas=[D, date(2026, 11, 10)], prob_apta=1.0)
    return base | extra


CAT = {"milho": {"TOPMN": 18, "TOPMX": 33, "ROPMN": 600, "ROPMX": 1200}}


def test_card_de_cultura_recomendada():
    r = mt._recomendacao_de_linha(linha(), CAT)
    assert r.cultura == "Milho"
    assert "20/11/2026" in r.descricao and "150 dias" in r.descricao and "89/100" in r.descricao
    assert "Elegível a crédito" in r.descricao and "Grãos" in r.descricao
    texto = " | ".join(r.motivos)
    assert "No plantio em 20/11: clima muito favorável; faltam em média 73 mm de água no ciclo" in texto
    assert "indicada pelo zoneamento oficial (risco de até 20%)" in texto and "pH 5.2 abaixo do ideal, corrigível com calagem" in texto
    assert "Port.344 de 06-08-2026" in texto
    assert r.clima.temperatura == "18°C a 33°C (faixa ótima)" and r.clima.chuva == "600 a 1200 mm (faixa ótima)"
    assert r.clima.epoca == "20/11; também bom: 10/11" and r.clima.adaptacao == "Apta em 100% dos anos (NASA POWER)"


def test_card_de_cultura_eliminada_e_sem_dados():
    r = mt._recomendacao_de_linha(linha(eliminada=True, motivo_eliminacao="clima inapto (T1: geada)", s_t1=0.05,
                                        fator_limitante="geada", zarc_status="nao_indicado", prob_apta=None,
                                        status_elegibilidade="inelegivel", explicacao_rotacao=None, alertas_solo=None,
                                        ciclo_dias=None), {})
    assert r.motivos[0] == "Não indicada: clima inapto (T1: geada)."
    assert any("fora da janela do zoneamento oficial" in m for m in r.motivos)
    assert "ciclo" not in r.descricao and "Fora das regras de crédito" in r.descricao
    assert r.clima.temperatura == "—" and r.clima.adaptacao == "—"


# --- motor_modelo com o recomendador simulado ---------------------------------------------------

def setor(*nomes):
    return pl.DataFrame([linha(id_cultura=n.lower(), nome_pt=n) for n in nomes])


@pytest.fixture
def recomendador_falso(monkeypatch):
    chamadas = {}

    def recomendar(lat, lon, data_plantio, **kw):
        chamadas.update(lat=lat, lon=lon, data=data_plantio, **kw)
        t2 = pl.DataFrame({"data_estado_solo": [date(2026, 11, 12)], "agua_solo_hoje": [0.64], "classe_ad": ["AD 4 (1,10)"]})
        return SimpleNamespace(
            setores={"melhores": setor("Milho", "Sorgo", "Girassol"), "intermediarias": setor("Algodão"),
                     "piores": setor("Centeio")},
            desejada={"nome_pt": "Soja", "posicao": 7, "total_culturas": 38, "setor": "intermediarias",
                      "score_final": 0.76, "plantio": date(2026, 11, 30)},
            ranking=setor("Milho", "Sorgo", "Girassol", "Algodão", "Soja", "Centeio"),
            torres={"t2": t2},
        )

    import towers.combinador as comb
    import towers.data.culturas as culturas
    monkeypatch.setattr(comb, "recomendar", recomendar)
    monkeypatch.setattr(culturas, "carregar_culturas", lambda **_: pl.DataFrame(
        {"id_cultura": ["milho"], "TOPMN": [18], "TOPMX": [33], "ROPMN": [600], "ROPMX": [1200]}))
    monkeypatch.setattr(mt, "localizar_municipio",
                        lambda uf, cidade: {"geocodigo": "4113700", "nome": cidade, "uf": uf, "lat": -23.3, "lon": -51.16})
    return chamadas


def test_motor_modelo_traduz_entrada_e_saida(recomendador_falso):
    e = mt.Entrada(penultimo="Soja", ultimo="Soja", uf="PR", cidade="Londrina", data_plantio=D, cultura_desejada="Soja",
                   problemas=["Compactação do solo", "Presença de pragas"], objetivos=["Acesso a crédito e seguro"],
                   tipos_cultura=["graos"])
    res = mt.motor_modelo(e, {})
    c = recomendador_falso
    assert (c["lat"], c["lon"], c["data"], c["geocodigo"]) == (-23.3, -51.16, D, "4113700")
    assert c["cultura_desejada"] == "Soja" and c["ultimo"] == "Soja" and c["penultimo"] == "Soja"
    assert c["problemas_solo"] == ["compactado"] and c["somente_financiaveis"] and c["tipos_cultura"] == ["graos"]
    assert res.fonte == "modelo"
    assert [r.cultura for r in res.recomendadas] == ["Milho", "Sorgo", "Girassol"]
    assert [r.cultura for r in res.razoaveis] == ["Algodão"] and [r.cultura for r in res.nao_recomendadas] == ["Centeio"]
    assert "Soja, ficou em 7º de 38 (entre as alternativas razoáveis)" in res.observacoes[0]
    assert "64% da capacidade" in res.observacoes[1]


def test_sem_preferencia_e_sem_tipos(recomendador_falso):
    e = mt.Entrada(penultimo="Milho", ultimo="Soja", uf="PR", cidade="Londrina", data_plantio=D,
                   cultura_desejada="Sem preferência")
    mt.motor_modelo(e, {})
    assert recomendador_falso["cultura_desejada"] is None and recomendador_falso["tipos_cultura"] is None


def test_municipio_desconhecido(monkeypatch):
    monkeypatch.setattr(mt, "localizar_municipio", lambda uf, cidade: None)
    with pytest.raises(ValueError, match="Município"):
        mt.motor_modelo(mt.Entrada(uf="XX", cidade="Nenhuma", data_plantio=D), {})


# --- caminhos sem dados reais -------------------------------------------------------------------

def test_mock_continua_funcionando():
    r = mt.gerar_recomendacoes(mt.ENTRADA_DEMO, motor="mock")
    assert r.fonte == "mock" and len(r.recomendadas) == len(r.razoaveis) == len(r.nao_recomendadas) == 3
    with pytest.raises(ValueError):
        mt.gerar_recomendacoes(mt.ENTRADA_DEMO, motor="inexistente")


def test_estatisticas_sem_municipio_sao_ficticias():
    est = mt.obter_estatisticas(mt.Entrada())
    assert len(est["chuva_mm"]) == len(est["temp_c"]) == 12 and "fictícios" in est["aviso"]


def test_listas_do_formulario():
    assert mt.CULTURAS_HISTORICO and mt.CULTURAS_DESEJADAS[0] == "Sem preferência" and mt.ESTADOS
    if mt.DADOS_REAIS:
        assert "Pousio" in mt.CULTURAS_HISTORICO and len(mt.ESTADOS) == 27


def test_torres_fora_da_nota_vao_para_o_log_e_nao_para_a_tela(recomendador_falso, monkeypatch, caplog):
    import logging
    import towers.combinador as comb
    original = comb.recomendar

    def com_ausente(*a, **k):
        r = original(*a, **k)
        r.torres_ausentes = {"t3": "não respondeu em 30 s"}
        return r

    monkeypatch.setattr(comb, "recomendar", com_ausente)
    e = mt.Entrada(penultimo="Milho", ultimo="Soja", uf="PR", cidade="Londrina", data_plantio=D)
    with caplog.at_level(logging.WARNING, logger="motor"):
        res = mt.motor_modelo(e, {})
    assert not any("fora" in o for o in res.observacoes)
    assert any("torre t3 fora da nota" in r.getMessage() for r in caplog.records)
