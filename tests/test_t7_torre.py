"""Torre 7 no recomendador: eventos e limiares por cultura sobre a série do NASA POWER, e ajuste pelo ENSO."""
from datetime import date, timedelta

import pandas as pd
import polars as pl
import pytest

from towers.combinador import OBJETIVOS, combinar
from towers.t7_extremos import enso as enso_mod
from towers.t7_extremos import torre as t7
from towers.t7_extremos.config import carregar_config
from towers.t7_extremos.torre import avaliar_t7, fases_da_cultura

D = date(2026, 11, 20)
CFG = carregar_config()


def clima(chuva_dias=(), tmin_frio=None, anos=range(2001, 2026)):
    """Série calma (2 mm/dia, 25 °C, mínima 18 °C). ``chuva_dias``: [(mês, dia, mm, n_dias)] todo ano;
    ``tmin_frio``: (mês, dia, tmin) por 3 dias todo ano."""
    dias = [date(anos[0], 1, 1) + timedelta(days=i)
            for i in range((date(anos[-1], 12, 31) - date(anos[0], 1, 1)).days + 1)]
    chuva, tmin = [], []
    for d in dias:
        mm = 2.0
        for mes, dia, valor, n in chuva_dias:
            if 0 <= (d - date(d.year, mes, dia)).days < n:
                mm = valor
        chuva.append(mm)
        frio = tmin_frio and 0 <= (d - date(d.year, tmin_frio[0], tmin_frio[1])).days < 3
        tmin.append(tmin_frio[2] if frio else 18.0)
    return pl.DataFrame({"data": dias, "PRECTOTCORR": chuva, "T2M": [25.0] * len(dias), "T2M_MIN": tmin})


def culturas(*linhas):
    return pl.DataFrame([{"id_cultura": i, "nome_pt": n, "uso": "agricultura", "modo": m, "obrigatoria": True,
                          "escala_cultivo": 0, "ciclo_min": c, "ciclo_max": c} for i, n, m, c in linhas])


def avaliar(cult, cl, **kw):
    r = avaliar_t7(-17.8, -50.9, D, deslocamentos=(0,), culturas=cult, clima=cl, cfg=CFG, usar_enso=False,
                   colapsar_variantes=False, **kw)
    return {x["id_cultura"]: x for x in r.iter_rows(named=True)}


def test_fases_por_cultura_e_padrao():
    f, meta = fases_da_cultura("feijao", 100, "safra", "agricultura", CFG)
    assert [x["nome"] for x in f] == ["estabelecimento", "floracao", "colheita"]
    assert f[1]["eventos"] == (("frio", 12.0),) and (f[1]["inicio"], f[1]["fim"]) == (40, 60)
    assert "12 °C" in meta["fonte"]
    f, _ = fases_da_cultura("arroz-irrigado", 120, "safra", "agricultura", CFG)
    assert f[1]["eventos"] == (("frio", 17.0),)                        # mesmo bloco do arroz
    f, meta = fases_da_cultura("girassol", 100, "safra", "agricultura", CFG)
    assert [x["eventos"] for x in f] == [(("chuva_dia", None),), (("queda_brusca", None),), (("chuva_extrema", None),)]
    assert "gerais" in meta["fonte"]
    f, _ = fases_da_cultura("cafe", 300, "implantacao", "agricultura", CFG)
    assert [x["nome"] for x in f] == ["estabelecimento"]


def test_chuva_forte_no_estabelecimento():
    # 60 mm em 25/11 (5 dias após o plantio de 20/11) todo ano
    v = avaliar(culturas(("girassol", "Girassol", "safra", 100)), clima([(11, 25, 60.0, 1)]))
    assert v["girassol"]["p_chuva"] == 1.0 and v["girassol"]["score_t7"] == 0.0
    v = avaliar(culturas(("girassol", "Girassol", "safra", 100)), clima([(11, 25, 40.0, 1)]))
    assert v["girassol"]["p_algum"] == 0.0


def test_frio_na_floracao_do_feijao_pela_minima():
    # floração do feijão (ciclo 90): 36 a 54 dias após 20/11 → 26/12 a 13/01; mínima de 10 °C em 01/01
    cult = culturas(("feijao", "Feijão", "safra", 90), ("girassol", "Girassol", "safra", 90))
    v = avaliar(cult, clima(tmin_frio=(1, 1, 10.0)))
    assert v["feijao"]["p_frio"] == 1.0 and v["feijao"]["p_algum"] == 1.0
    assert v["girassol"]["p_frio"] == 0.0              # sem limiar próprio: só queda brusca (T2M constante)
    v = avaliar(cult, clima(tmin_frio=(1, 1, 13.0)))
    assert v["feijao"]["p_frio"] == 0.0                # 13 °C não passa do limiar de 12 °C


def test_chuva_persistente_na_colheita_da_soja():
    # colheita da soja (ciclo 120): 96 a 120 dias → 24/02 a 20/03; 6 dias seguidos de 8 mm a partir de 01/03
    cult = culturas(("soja", "Soja", "safra", 120))
    assert avaliar(cult, clima([(3, 1, 8.0, 6)]))["soja"]["p_chuva"] == 1.0
    assert avaliar(cult, clima([(3, 1, 8.0, 4)]))["soja"]["p_chuva"] == 0.0     # 4 dias: não é persistente
    assert avaliar(cult, clima([(3, 1, 3.0, 6)]))["soja"]["p_chuva"] == 0.0     # chuva fraca
    assert avaliar(cult, clima([(3, 1, 8.0, 6)]))["soja"]["p_frio"] is None     # soja: sem evento de frio


def test_enso_mistura_fase_atual_com_a_climatologia(monkeypatch):
    # evento só nos anos de El Niño (anos ímpares); fase atual El Niño
    anos = range(2001, 2026)
    cl = clima([(11, 25, 60.0, 1)])
    cl = cl.with_columns(PRECTOTCORR=pl.when((pl.col("data").dt.year() % 2 == 0) & (pl.col("PRECTOTCORR") > 50))
                         .then(2.0).otherwise(pl.col("PRECTOTCORR")))
    indice = pd.DataFrame([{"mes_centro": 11, "ano": a, "anom": 1.2 if a % 2 or a == 2026 else -0.1}
                           for a in range(2001, 2027)])   # 2026: trimestre do plantio, El Niño
    monkeypatch.setattr(enso_mod, "ler_indice_noaa", lambda *a, **k: indice)
    r = avaliar_t7(-17.8, -50.9, D, deslocamentos=(0,), culturas=culturas(("girassol", "Girassol", "safra", 100)),
                   clima=cl, cfg=CFG, colapsar_variantes=False).row(0, named=True)
    n = 12                                              # anos ímpares de 2001 a 2023 (2025 não fecha o ciclo)
    p_clim = r["p_algum_clim"]
    assert r["enso_fase"] == "El Niño" and r["n_anos_fase_enso"] == n
    assert r["p_algum"] == pytest.approx((n * 1.0 + CFG.enso.k * p_clim) / (n + CFG.enso.k))
    assert r["p_algum"] > p_clim and r["score_t7"] == pytest.approx(1 - r["p_algum"])


def test_indice_noaa_e_fases(tmp_path):
    (tmp_path / "RONI.ascii.txt").write_text("SEAS   YR  ANOM\nDJF  1950 -1.19\nASO  2026  1.97\n", encoding="utf-8")
    idx = enso_mod.ler_indice_noaa("https://exemplo/RONI.ascii.txt", cache_dir=tmp_path, cache_dias=999)
    assert idx.to_dict("records") == [{"mes_centro": 1, "ano": 1950, "anom": -1.19},
                                      {"mes_centro": 9, "ano": 2026, "anom": 1.97}]
    assert [enso_mod.fase_do_indice(x) for x in (0.5, 0.49, -0.5, -0.49)] == ["El Niño", "Neutro", "La Niña", "Neutro"]


def test_t7_entra_no_combinador_com_peso_por_objetivo():
    t1 = pl.DataFrame([{"id_cultura": "a", "nome_pt": "A", "plantio": D, "score_t1": 0.8, "apt_p20": 0.8,
                        "gate_t1": True, "uso": "agricultura", "modo": "safra", "colheita": "reprodutiva",
                        "obrigatoria": True, "escala_cultivo": 0, "fator_limitante": "chuva", "ciclo_dias": 100,
                        "alerta_foto_mensagem": None, "alerta_ciclo_extremo": False}])
    saida = pl.DataFrame({"id_cultura": ["a"], "plantio": [D], "score_t7": [0.5], "p_algum": [0.5], "p_chuva": [0.3],
                          "p_frio": [0.3], "n_anos_t7": [25], "enso_fase": ["El Niño"], "eventos_t7": [["x"]]})
    r = combinar(t1, t7=saida, peso_evidencia=0).row(0, named=True)
    w = OBJETIVOS["equilibrado"]["pesos"]
    assert r["s_t7"] == 0.5 and r["p_extremo"] == 0.5 and r["enso_fase"] == "El Niño"
    assert r["score_final"] == pytest.approx(0.8 ** (w["t1"] / (w["t1"] + w["t7"])) * 0.5 ** (w["t7"] / (w["t1"] + w["t7"])))
    assert all("t7" in o["pesos"] for o in OBJETIVOS.values())
    assert OBJETIVOS["estabilidade"]["pesos"]["t7"] == max(o["pesos"]["t7"] for o in OBJETIVOS.values())


def test_sem_indice_fica_a_climatologia(monkeypatch):
    monkeypatch.setattr(enso_mod, "ler_indice_noaa", lambda *a, **k: None)
    r = avaliar_t7(-17.8, -50.9, D, deslocamentos=(0,), culturas=culturas(("soja", "Soja", "safra", 120)),
                   clima=clima(), cfg=CFG, colapsar_variantes=False).row(0, named=True)
    assert r["enso_fase"] == "nao_calculado" and r["p_algum"] == r["p_algum_clim"]
