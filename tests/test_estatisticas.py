"""Painel de estatísticas: frases e cálculos com séries sintéticas (sem rede)."""
from datetime import date, timedelta

import polars as pl
import pytest

import estatisticas as es


def serie(chuva_por_mes, gwet_hoje=0.3):
    dias = [date(2001, 1, 1) + timedelta(days=i) for i in range((date(2026, 11, 13) - date(2001, 1, 1)).days + 1)]
    return pl.DataFrame({
        "data": dias,
        "IMERG_PRECTOT": [chuva_por_mes[d.month - 1] / 30 for d in dias],
        "T2M": [20.0 + (5 if d.month in (10, 11) else 0) for d in dias],
        "T2M_MIN": [15.0] * len(dias), "T2M_MAX": [30.0] * len(dias),
        "GWETROOT": [gwet_hoje if d.year == 2026 and d.month == 11 else 0.6 for d in dias],
    })


@pytest.fixture
def clima_falso(monkeypatch):
    from towers.data import power
    chuva = [300, 250, 200, 90, 30, 10, 5, 10, 40, 120, 210, 260]
    monkeypatch.setattr(power, "clima_diario", lambda lat, lon, **k: serie(chuva))
    return chuva


def test_formato_brasileiro():
    assert es._mm(1540.4) == "1.540" and es._lista_meses([5, 6, 7]) == "maio, junho e julho"


def test_clima_explica_estacao_seca_e_ciclo(clima_falso):
    c = es.clima(-17.8, -50.9, {"cultura": "Soja", "plantio": date(2026, 11, 20), "ciclo_dias": 120})
    texto = " ".join(c["leitura"])
    assert c["meses_secos"] == 5 and "maio, junho, julho, agosto e setembro" in texto
    assert "O ciclo de Soja (plantio em 20/11, cerca de 120 dias) passa por novembro, dezembro, janeiro, " \
           "fevereiro e março" in texto
    assert sum(m["no_ciclo"] for m in c["mensal"]) == 5
    assert "30/11." not in texto                                 # milhar com ponto não estraga a frase


def test_agua_no_solo_compara_com_a_epoca(clima_falso):
    a = es.agua_no_solo(-17.8, -50.9)
    assert a["situacao"] == "mais seco que o normal" and "o mais seco para a época desde 2001" in a["leitura"][0]
    assert "espere chuvas" in a["leitura"][1]


def test_painel_sem_municipio():
    import motor as mt
    assert "erro" in es.painel(mt.Entrada())
