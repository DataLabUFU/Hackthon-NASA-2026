"""Testes do recomendador: torres em paralelo com prazo; a que não responde fica fora da nota."""
import time
from datetime import date

import polars as pl
import pytest

import towers.combinador.recomendador as rc

D = date(2026, 11, 20)
CAT = pl.DataFrame([
    {"id_cultura": i, "nome_pt": n, "especie": n, "familia": None, "uso": "agricultura", "modo": "safra",
     "colheita": "reprodutiva", "obrigatoria": True, "escala_cultivo": 0, "tipo_cultura": "graos",
     "exibivel": True, "nomes_pt_alternativos": []}
    for i, n in [("milho", "Milho"), ("soja", "Soja")]
])


def t1_(**_):
    return pl.DataFrame([{
        "id_cultura": i, "nome_pt": n, "uso": "agricultura", "modo": "safra", "colheita": "reprodutiva",
        "obrigatoria": True, "escala_cultivo": 0, "plantio": D, "score_t1": s, "apt_p20": s, "gate_t1": True,
        "fator_limitante": "chuva", "ciclo_dias": 120, "alerta_foto_mensagem": None, "alerta_ciclo_extremo": False,
    } for i, n, s in [("milho", "Milho", 0.9), ("soja", "Soja", 0.6)]])


def t3_(**_):
    return pl.DataFrame({"id_cultura": ["milho", "soja"], "score_t3": [0.5, 1.0], "alertas_solo": [[], []],
                         "fator_limitante_solo": ["ph", None]})


def dormir(segundos, saida=None):
    def f(*a, **k):
        time.sleep(segundos)
        return saida() if saida else None
    return f


def falhar(*a, **k):
    raise ConnectionError("API fora do ar")


@pytest.fixture
def ambiente(monkeypatch):
    """Só T1 e T3 produzem score; T2, T4, T5 e T6 devolvem None (como torre sem dado)."""
    monkeypatch.setattr(rc, "carregar_culturas", lambda **_: CAT)
    monkeypatch.setattr(rc, "municipio_mais_proximo", lambda lat, lon: {"geocodigo": "4113700"})
    monkeypatch.setattr(rc, "solo_local", lambda lat, lon: {"classe_ad": "AD 4 (1,10)", "ad_mm_cm": 1.1, "argila": 50.0})
    monkeypatch.setattr(rc, "clima_diario", lambda *a, **k: pl.DataFrame())
    monkeypatch.setattr(rc, "avaliar_t1", lambda *a, **k: t1_())
    monkeypatch.setattr(rc, "avaliar_t3", lambda *a, **k: t3_())
    for nome in ("avaliar_t2", "avaliar_t4", "avaliar_t5", "avaliar_t6"):
        monkeypatch.setattr(rc, nome, lambda *a, **k: None)
    return monkeypatch


def test_todas_respondem(ambiente):
    rec = rc.recomendar(0, 0, D, timeout_torre_s=5)
    assert rec.torres_ausentes == {} and set(rec.torres) == {"t1", "t3"}
    assert rec.ranking["nome_pt"].to_list()[0] == "Soja"           # 0,6 de clima e 1,0 de solo vencem 0,9 e 0,5


def test_torre_lenta_fica_fora_da_nota(ambiente):
    ambiente.setattr(rc, "avaliar_t3", dormir(2.0, t3_))
    inicio = time.perf_counter()
    rec = rc.recomendar(0, 0, D, timeout_torre_s=0.5)
    assert time.perf_counter() - inicio < 1.8                       # não esperou a torre lenta
    assert "t3" in rec.torres_ausentes and "não respondeu" in rec.torres_ausentes["t3"]
    assert "t3" not in rec.torres and "s_t3" not in rec.ranking.columns
    assert rec.ranking["nome_pt"].to_list()[0] == "Milho"          # sem o solo, vale o clima


def test_torre_com_erro_fica_fora_da_nota(ambiente):
    ambiente.setattr(rc, "avaliar_t3", falhar)
    rec = rc.recomendar(0, 0, D, timeout_torre_s=5)
    assert rec.torres_ausentes["t3"].startswith("erro: API fora do ar")


def test_sem_t1_os_candidatos_seguem_com_clima_neutro(ambiente):
    ambiente.setattr(rc, "avaliar_t1", falhar)
    rec = rc.recomendar(0, 0, D, timeout_torre_s=5)
    assert "t1" in rec.torres_ausentes
    assert set(rec.ranking["nome_pt"]) == {"Milho", "Soja"} and not rec.ranking["eliminada"].any()
    assert rec.ranking["nome_pt"].to_list()[0] == "Soja"           # só o solo decide
    assert rec.ranking["s_t1"].null_count() == rec.ranking.height


def test_clima_lento_derruba_t1_e_t2(ambiente):
    ambiente.setattr(rc, "clima_diario", dormir(2.0, pl.DataFrame))
    ambiente.setattr(rc, "avaliar_t1", lambda *a, clima=None, **k: t1_())
    ambiente.setattr(rc, "avaliar_t2", lambda *a, clima=None, **k: None)
    rec = rc.recomendar(0, 0, D, timeout_torre_s=0.5)
    assert {"t1", "t2"} <= set(rec.torres_ausentes) and "t3" in rec.torres


def test_solo_lento_nao_derruba_t2_t4_t6(ambiente):
    """O solo compartilhado tem prazo próprio no SoilGrids; aqui ele falha e as torres usam o padrão."""
    recebidos = {}

    def t4_(*a, solo=None, **k):
        recebidos["t4"] = solo
        return None

    def t2_(*a, solo=None, clima=None, **k):
        recebidos["t2"] = solo
        return None

    ambiente.setattr(rc, "solo_local", falhar)
    ambiente.setattr(rc, "avaliar_t4", t4_)
    ambiente.setattr(rc, "avaliar_t2", t2_)
    rec = rc.recomendar(0, 0, D, timeout_torre_s=5)
    assert rec.torres_ausentes == {}
    assert recebidos["t4"] == {} and recebidos["t2"]["classe_ad"].startswith("AD 4")   # padrões de cada torre
