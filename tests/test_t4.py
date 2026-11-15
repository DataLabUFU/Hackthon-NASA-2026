"""Testes da Torre 4 (ZARC) com tábua sintética, sem rede."""
from datetime import date

import polars as pl
import pytest

from towers.data.zarc import DECENDIOS
from towers.t4_zarc import avaliar_t4
from towers.t4_zarc.torre import codigos_solo

GEO = "4100000"


def linha(cultura, solo, ciclo, decs: dict[int, int], safra=2026, manejo="Sequeiro", portaria="Port.1_de_2026"):
    return {"Nome_cultura": cultura, "SafraIni": safra, "geocodigo": GEO, "municipio": "Teste", "UF": "PR",
            "Cod_Solo": solo, "Cod_Ciclo": ciclo, "Nome_Outros_Manejos": manejo, "Portaria": portaria,
            **{d: decs.get(i + 1, 0) for i, d in enumerate(DECENDIOS)}}


@pytest.fixture
def tabua(tmp_path):
    linhas = [
        linha("Soja", "14", "21", {29: 30, 30: 20}),          # solo AD4: dec29 risco 30, dec30 risco 20
        linha("Soja", "14", "22", {29: 20}),                  # outro ciclo melhora o dec29
        linha("Soja", "11", "21", {31: 40}),                  # solo AD1 (arenoso): só dec31
        linha("Soja", "14", "21", {1: 20}, safra=2023),       # safra antiga: ignorada
        linha("Algodão Herbáceo", "3", "20", {33: 20}),       # sistema antigo: tipo 3 (argiloso)
        linha("Arroz", "14", "20", {29: 20}, manejo="Irrigado"),
    ]
    caminho = tmp_path / "zarc.parquet"
    pl.DataFrame(linhas, schema_overrides={d: pl.Int8 for d in DECENDIOS} | {"SafraIni": pl.Int16}).write_parquet(caminho)
    return caminho


def catalogo():
    return pl.DataFrame([
        {"id_cultura": c, "nome_pt": n, "uso": "agricultura", "modo": "safra", "obrigatoria": True, "escala_cultivo": 0}
        for c, n in [("soja", "Soja"), ("algodao-herbaceo", "Algodão herbáceo"), ("arroz", "Arroz"),
                     ("arroz-irrigado", "Arroz irrigado"), ("cacau", "Cacau")]
    ])


SOLO_AD4_ARGILOSO = {"classe_ad": "AD 4 (1,10)", "argila": 54.0}


def t4(tabua, **kw):
    args = dict(data_plantio=date(2026, 10, 15), deslocamentos=(0, 10, 20), culturas=catalogo(), geocodigo=GEO,
                solo=SOLO_AD4_ARGILOSO, caminho_zarc=tabua)
    return avaliar_t4(0, 0, **(args | kw), colapsar_variantes=False)


def item(df, id_c, plantio):
    return df.filter((pl.col("id_cultura") == id_c) & (pl.col("plantio") == plantio)).row(0, named=True)


def test_codigos_solo():
    assert codigos_solo(SOLO_AD4_ARGILOSO) == {"14", "3"}
    assert codigos_solo({"classe_ad": "AD 0", "argila": 10.0}) == {"11", "1"}
    assert codigos_solo(None) == set()


def test_melhor_ciclo_e_risco_no_solo_do_local(tabua):
    r = t4(tabua)
    d29 = item(r, "soja", date(2026, 10, 15))          # dec29: ciclo 22 tem risco 20 (melhor que 30)
    assert (d29["zarc_status"], d29["risco_pct"], d29["ciclo_zarc"]) == ("indicado", 20, "22")
    assert d29["score_t4"] == pytest.approx(1.0) and d29["portaria"] == "Port.1_de_2026"
    d31 = item(r, "soja", date(2026, 11, 4))           # dec31: só no solo AD1 → não indicado no AD4
    assert d31["zarc_status"] == "nao_indicado" and d31["score_t4"] == 0.0
    assert d31["indicado_melhor_solo"] and d31["risco_melhor_solo"] == 40


def test_sistema_antigo_de_solo(tabua):
    r = item(t4(tabua, data_plantio=date(2026, 11, 25), deslocamentos=(0,)), "algodao-herbaceo", date(2026, 11, 25))
    assert r["zarc_status"] == "indicado" and r["solo_zarc"] == "3"


def test_sem_zoneamento_e_nulo(tabua):
    cacau = item(t4(tabua), "cacau", date(2026, 10, 15))
    assert cacau["zarc_status"] == "sem_zoneamento" and cacau["score_t4"] is None


def test_irrigado_so_quando_pedido(tabua):
    # o ZARC irrigado do arroz vai para o "Arroz irrigado"; o "Arroz" (sequeiro) não recebe essas linhas
    assert item(t4(tabua), "arroz-irrigado", date(2026, 10, 15))["zarc_status"] == "sem_zoneamento"
    assert item(t4(tabua, irrigado=True), "arroz-irrigado", date(2026, 10, 15))["zarc_status"] == "indicado"
    assert item(t4(tabua, irrigado=True), "arroz", date(2026, 10, 15))["zarc_status"] == "sem_zoneamento"


def test_solo_desconhecido_usa_o_melhor_solo(tabua):
    r = item(t4(tabua, solo={}), "soja", date(2026, 11, 4))
    assert r["solo_usado"] == "melhor_solo" and r["zarc_status"] == "indicado" and r["risco_pct"] == 40


def test_ordenacao_com_nulos_por_ultimo(tabua):
    r = t4(tabua)
    assert r["score_t4"].tail(4).null_count() == 4
