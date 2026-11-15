"""Torre 7 no recomendador: eventos da T7 sobre a série do NASA POWER, por cultura e data de plantio."""
from datetime import date, timedelta

import polars as pl
import pytest

from towers.combinador import OBJETIVOS, combinar
from towers.t7_extremos.torre import avaliar_t7, fases_da_cultura

D = date(2026, 11, 20)


def clima(chuva_extrema_em=(2, 10), anos=range(2001, 2026), frio_em=None):
    """Série diária calma; todo ano, 90 mm em 3 dias a partir de ``chuva_extrema_em`` (mês, dia)."""
    dias = [date(anos[0], 1, 1) + timedelta(days=i) for i in range((date(anos[-1], 12, 31) - date(anos[0], 1, 1)).days + 1)]
    chuva, temp = [], []
    for d in dias:
        ini = date(d.year, *chuva_extrema_em)
        chuva.append(30.0 if 0 <= (d - ini).days < 3 else 2.0)
        frio = frio_em and date(d.year, *frio_em) <= d < date(d.year, *frio_em) + timedelta(days=3)
        temp.append(17.0 if frio else 25.0)
    return pl.DataFrame({"data": dias, "PRECTOTCORR": chuva, "T2M": temp})


def culturas(*linhas):
    return pl.DataFrame([{"id_cultura": i, "nome_pt": n, "uso": "agricultura", "modo": m, "obrigatoria": True,
                          "escala_cultivo": 0, "ciclo_min": c, "ciclo_max": c} for i, n, m, c in linhas])


def test_fases_genericas():
    f = fases_da_cultura(100, "safra", "agricultura")
    assert [x["nome"] for x in f] == ["estabelecimento", "floracao", "colheita"]
    assert (f[1]["inicio"], f[1]["fim"], f[2]["inicio"], f[2]["fim"]) == (40, 65, 80, 100)
    assert [x["nome"] for x in fases_da_cultura(100, "implantacao", "agricultura")] == ["estabelecimento"]


def test_chuva_na_colheita_conta_so_para_quem_colhe_nela():
    # a soma de 3 dias passa de 80 mm em 12/02. Plantio 20/11: ciclo de 84 dias colhe de 23/01 a 12/02 (pega);
    # ciclo de 60 dias, não
    cult = culturas(("longa", "Longa", "safra", 84), ("curta", "Curta", "safra", 60), ("perene", "Perene", "implantacao", 300))
    r = avaliar_t7(-17.8, -50.9, D, deslocamentos=(0,), culturas=cult, clima=clima(), colapsar_variantes=False)
    v = {x["id_cultura"]: x for x in r.iter_rows(named=True)}
    assert v["longa"]["p_chuva_extrema"] == 1.0 and v["longa"]["score_t7"] == 0.0
    assert v["curta"]["p_algum"] == 0.0 and v["curta"]["score_t7"] == 1.0
    assert v["perene"]["p_algum"] == 0.0                     # só o estabelecimento conta
    assert v["longa"]["n_anos_t7"] == 24                      # o último ano não fecha o ciclo e sai


def test_queda_brusca_na_floracao():
    cult = culturas(("a", "A", "safra", 100))
    # floração de 40 a 65 dias após 20/11 → 30/12 a 24/01; esfria 8 °C em 05/01
    r = avaliar_t7(-17.8, -50.9, D, deslocamentos=(0,), culturas=cult, clima=clima((6, 1), frio_em=(1, 5)),
                   colapsar_variantes=False).row(0, named=True)
    assert r["p_queda_brusca"] == 1.0 and r["p_chuva_extrema"] == 0.0 and r["p_algum"] == 1.0
    assert r["p_algum_ic_inf"] <= r["p_algum"] <= r["p_algum_ic_sup"]


def test_t7_entra_no_combinador_com_peso_por_objetivo():
    t1 = pl.DataFrame([{"id_cultura": "a", "nome_pt": "A", "plantio": D, "score_t1": 0.8, "apt_p20": 0.8,
                        "gate_t1": True, "uso": "agricultura", "modo": "safra", "colheita": "reprodutiva",
                        "obrigatoria": True, "escala_cultivo": 0, "fator_limitante": "chuva", "ciclo_dias": 100,
                        "alerta_foto_mensagem": None, "alerta_ciclo_extremo": False}])
    t7 = pl.DataFrame({"id_cultura": ["a"], "plantio": [D], "score_t7": [0.5], "p_algum": [0.5],
                       "p_chuva_extrema": [0.3], "p_queda_brusca": [0.3], "n_anos_t7": [25]})
    r = combinar(t1, t7=t7, peso_evidencia=0).row(0, named=True)
    w = OBJETIVOS["equilibrado"]["pesos"]
    assert r["s_t7"] == 0.5 and r["p_extremo"] == 0.5
    assert r["score_final"] == pytest.approx(0.8 ** (w["t1"] / (w["t1"] + w["t7"])) * 0.5 ** (w["t7"] / (w["t1"] + w["t7"])))
    assert all("t7" in o["pesos"] for o in OBJETIVOS.values())
    assert OBJETIVOS["estabilidade"]["pesos"]["t7"] == max(o["pesos"]["t7"] for o in OBJETIVOS.values())
