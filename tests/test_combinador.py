"""Testes do combinador e do ordenador com saídas sintéticas das torres."""
import math
from datetime import date

import polars as pl
import pytest

from towers.combinador import OBJETIVOS, combinar, localizar, ordenar, setores
from towers.combinador.pesos import PISO_SCORE

D1, D2 = date(2026, 10, 15), date(2026, 10, 25)


def t1_(linhas):
    base = dict(uso="agricultura", modo="safra", colheita="reprodutiva", obrigatoria=True, escala_cultivo=0,
                fator_limitante="temperatura", ciclo_dias=120, alerta_foto_mensagem=None, alerta_ciclo_extremo=False)
    return pl.DataFrame([base | {"id_cultura": i, "nome_pt": n, "plantio": p, "score_t1": s, "apt_p20": p20,
                                 "gate_t1": g} for i, n, p, s, p20, g in linhas])


def por_data(nome, linhas, col):
    return pl.DataFrame([{"id_cultura": i, "plantio": p, col: s} for i, p, s in linhas])


def test_media_geometrica_ponderada_e_neutralidade():
    t1 = t1_([("a", "A", D1, 0.8, 0.8, True)])
    t2 = por_data("t2", [("a", D1, 0.5)], "score_t2").with_columns(prob_perda20=pl.lit(0.0), irrigacao_mm_med=pl.lit(0.0),
                                                                    ciclo_dias=pl.lit(120))
    t4 = por_data("t4", [("a", D1, None)], "score_t4").with_columns(
        score_t4=pl.col("score_t4").cast(pl.Float64), zarc_status=pl.lit("sem_zoneamento"), risco_pct=pl.lit(None, pl.Int64))
    r = combinar(t1, t2=t2, t4=t4, peso_evidencia=0).row(0, named=True)
    w = OBJETIVOS["equilibrado"]["pesos"]
    esperado = math.exp((w["t1"] * math.log(0.8) + w["t2"] * math.log(0.5)) / (w["t1"] + w["t2"]))  # T4 nulo = neutro
    assert r["score_final"] == pytest.approx(esperado) and r["torres_com_score"] == 2


def test_zero_penaliza_sem_anular():
    t1 = t1_([("a", "A", D1, 1.0, 1.0, True)])
    t3 = pl.DataFrame({"id_cultura": ["a"], "score_t3": [0.0], "alertas_solo": [[]], "fator_limitante_solo": ["ph"]})
    r = combinar(t1, t3=t3, peso_evidencia=0).row(0, named=True)
    w = OBJETIVOS["equilibrado"]["pesos"]
    assert r["score_final"] == pytest.approx(math.exp(w["t3"] * math.log(PISO_SCORE) / (w["t1"] + w["t3"])))
    assert 0 < r["score_final"] < 0.5


def test_gate_da_t1_elimina():
    r = combinar(t1_([("a", "A", D1, 0.3, 0.0, False)])).row(0, named=True)
    assert r["eliminada"] and r["score_final"] == 0.0 and "clima inapto" in r["motivo_eliminacao"]


def test_somente_financiaveis_e_objetivo_conservador():
    t1 = t1_([("a", "A", D1, 0.9, 0.4, True)])
    t6 = pl.DataFrame({"id_cultura": ["a"], "plantio": [D1], "status_elegibilidade": ["inelegivel"], "financiavel": [False],
                       "elegivel_proagro": [False], "portaria_zarc": [None], "motivos": [["fora da janela"]]})
    assert not combinar(t1, t6=t6)["eliminada"].item()
    assert combinar(t1, t6=t6, somente_financiaveis=True)["eliminada"].item()
    assert combinar(t1, t6=t6, objetivo="financiamento")["eliminada"].item()        # padrão do objetivo
    assert combinar(t1, objetivo="estabilidade", peso_evidencia=0)["score_final"].item() == pytest.approx(0.4)  # P20
    with pytest.raises(ValueError):
        combinar(t1, objetivo="lucro_maximo")


def test_torre_extra_plugavel():
    t1 = t1_([("a", "A", D1, 1.0, 1.0, True)])
    extremos = pl.DataFrame({"id_cultura": ["a"], "plantio": [D1], "score_extremos": [0.5]})
    r = combinar(t1, extras={"extremos": (extremos, 0.25)}, peso_evidencia=0).row(0, named=True)
    assert r["score_final"] == pytest.approx(math.exp(0.25 * math.log(0.5) / (0.25 + 0.25)))


# --- ordenador ---------------------------------------------------------------------------------

def ranking_sintetico(n=12, eliminadas=2):
    linhas = []
    for k in range(n):
        s = round(1 - k / n, 3)
        gate = k < n - eliminadas
        linhas += [(f"c{k}", f"Cultura {k:02d}", D1, s, s, gate), (f"c{k}", f"Cultura {k:02d}", D2, s - 0.1, s, gate)]
    return ordenar(combinar(t1_(linhas)))


def test_melhor_data_por_cultura():
    r = ranking_sintetico()
    assert r.height == 12 and (r["plantio"] == D1).all()
    assert r["posicao"].to_list() == list(range(1, 13))


def test_setores_padrao_de_3_sem_sobreposicao():
    r = ranking_sintetico()
    s = setores(r)
    assert [df.height for df in s.values()] == [3, 3, 3]
    assert s["melhores"]["nome_pt"].to_list() == ["Cultura 00", "Cultura 01", "Cultura 02"]
    assert s["piores"]["nome_pt"].to_list()[0] == "Cultura 11"                   # pior primeiro
    assert s["piores"]["eliminada"].any()                                        # inclui eliminadas
    todos = sum((df["nome_pt"].to_list() for df in s.values()), [])
    assert len(todos) == len(set(todos))
    meio = s["intermediarias"]["posicao"].to_list()
    assert min(meio) > 3 and max(meio) < 10


def test_top_n_configuravel_e_poucas_culturas():
    r = ranking_sintetico(n=5, eliminadas=0)
    s = setores(r, top_n=2)
    assert s["melhores"].height == 2 and s["piores"].height == 2 and s["intermediarias"].height == 1


def test_localizar_cultura_desejada():
    r = ranking_sintetico()
    s = setores(r)
    assert localizar(r, "Cultura 01", s)["setor"] == "melhores"
    assert localizar(r, "Cultura 11", s)["setor"] == "piores"
    assert localizar(r, "Cultura 04", s)["setor"] in ("intermediarias", "fora_dos_setores")
    assert localizar(r, "Inexistente", s) is None


def test_explicacao_pontos_fortes_e_fracos():
    t1 = t1_([("a", "A", D1, 0.9, 0.9, True)])
    t3 = pl.DataFrame({"id_cultura": ["a"], "score_t3": [0.3], "alertas_solo": [[]], "fator_limitante_solo": ["drenagem"]})
    r = ordenar(combinar(t1, t3=t3)).row(0, named=True)
    assert r["pontos_fortes"] == ["clima"] and r["pontos_fracos"] == ["solo"]



# --- peso da evidência e tipo de cultura -------------------------------------------------------

def test_fator_de_confianca_favorece_o_mais_verificado():
    t1 = t1_([("capim", "Capim", D1, 0.95, 0.95, True), ("milho", "Milho", D1, 0.90, 0.90, True)])
    t4 = pl.DataFrame({"id_cultura": ["capim", "milho"], "plantio": [D1, D1], "score_t4": [None, 1.0],
                       "zarc_status": ["sem_zoneamento", "indicado"], "risco_pct": [None, 20]},
                      schema_overrides={"score_t4": pl.Float64, "risco_pct": pl.Int64})
    sem = ordenar(combinar(t1, t4=t4, peso_evidencia=0))
    com = ordenar(combinar(t1, t4=t4))
    assert sem["nome_pt"].to_list()[0] == "Capim"            # sem o fator, a falta do ZARC favorece o capim
    assert com["nome_pt"].to_list()[0] == "Milho"            # com o fator, o mais verificado passa à frente
    capim = com.filter(pl.col("nome_pt") == "Capim").row(0, named=True)
    assert 0.9 <= capim["fator_confianca"] < 1.0
    assert com.filter(pl.col("nome_pt") == "Milho")["fator_confianca"].item() == pytest.approx(1.0)


def test_qualidade_dos_parametros_entra_na_evidencia():
    t1 = t1_([("a", "A", D1, 1.0, 1.0, True)]).with_columns(fonte_parametros=pl.lit("Aproximação: copiado de X"))
    r = combinar(t1).row(0, named=True)
    assert r["fator_confianca"] < 1.0 and r["score_final"] < 1.0
