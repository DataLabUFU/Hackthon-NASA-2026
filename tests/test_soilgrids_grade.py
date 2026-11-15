"""Grade pré-calculada do SoilGrids, com um bloco sintético."""
import io

import numpy as np
import polars as pl
import pytest

from towers.data import soilgrids, soilgrids_grade as sg


def bloco_sintetico():
    n = sg.TAM_BLOCO
    a = {c: np.full((n, n), -32768, np.int16) for c in ("areia", "silte", "argila", "ph", "ctc",
                                                         "carbono_organico", "densidade")}
    a |= {f"dist_{t}": np.full((n, n), 255, np.uint8) for t in ("textura", "quimica", "classe")}
    a |= {f"classe{k}": np.full((n, n), 255, np.uint8) for k in (1, 2, 3)}
    a |= {f"prob{k}": np.full((n, n), 255, np.uint8) for k in (1, 2, 3)}
    # pixel (i=25, j=50): ponto (-16.255, -49.495) no bloco lat_n=-16, lon_w=-50
    a["areia"][25, 50], a["silte"][25, 50], a["argila"][25, 50] = 301, 199, 500
    a["ph"][25, 50], a["ctc"][25, 50], a["carbono_organico"][25, 50], a["densidade"][25, 50] = 512, 87, 155, 121
    a["dist_textura"][25, 50] = a["dist_quimica"][25, 50] = 0
    a["dist_classe"][25, 50] = 3
    i = sg.CLASSES_WRB.index
    a["classe1"][25, 50], a["classe2"][25, 50], a["classe3"][25, 50] = i("Ferralsols"), i("Cambisols"), i("Arenosols")
    a["prob1"][25, 50], a["prob2"][25, 50], a["prob3"][25, 50] = 41, 22, 9
    buf = io.BytesIO()
    np.savez_compressed(buf, **a)
    return buf.getvalue()


@pytest.fixture
def grade(monkeypatch, tmp_path):
    caminho = tmp_path / "grade.parquet"
    pl.DataFrame({"lat_n": [-16], "lon_w": [-50], "bloco": [bloco_sintetico()]},
                 schema={"lat_n": pl.Int16, "lon_w": pl.Int16, "bloco": pl.Binary}).write_parquet(caminho)
    monkeypatch.setattr(sg, "CAMINHO_GRADE", caminho)
    sg.disponivel.cache_clear(); sg._bloco.cache_clear()
    yield
    sg.disponivel.cache_clear(); sg._bloco.cache_clear()


def test_indice():
    assert sg.indice(-16.255, -49.495) == (-16, -50, 25, 50)
    assert sg.indice(-16.0, -50.0) == (-16, -50, 0, 0)          # borda: o pixel ao sul/leste
    assert sg.indice(40.0, -50.0) is None and sg.indice(-16.0, 10.0) is None


def test_textura_quimica_classe(grade):
    assert sg.consultar("textura", -16.255, -49.495) == (True, {
        "areia": 30.1, "silte": 19.9, "argila": 50.0, "distancia_graus": 0.0, "fonte": "grade"})
    _, q = sg.consultar("quimica", -16.255, -49.495)
    assert (q["ph"], q["ctc"], q["carbono_organico"], q["densidade"]) == (5.12, 8.7, 15.5, 1.21)
    _, c = sg.consultar("classe", -16.255, -49.495)
    assert c["wrb"] == "Ferralsols" and c["distancia_graus"] == 0.03
    assert c["wrb_probabilidades"] == [["Ferralsols", 41], ["Cambisols", 22], ["Arenosols", 9]]


def test_sem_dado_e_fora_da_grade(grade):
    assert sg.consultar("textura", -16.5, -49.5) == (True, None)     # pixel sem dado no raio
    assert sg.consultar("textura", -20.5, -45.5) == (False, None)    # bloco inexistente → API


def test_soilgrids_usa_a_grade_antes_da_api(grade, monkeypatch, tmp_path):
    monkeypatch.setattr(soilgrids, "CACHE_PADRAO", tmp_path)
    monkeypatch.setitem(soilgrids._CONSULTA_PADRAO, "textura", api := lambda la, lo: pytest.fail("chamou a API"))
    assert soilgrids.textura(-16.255, -49.495, cache_dir=tmp_path, consulta=api)["argila"] == 50.0
    assert not list(tmp_path.glob("*.json"))                         # a grade não grava cache por ponto
