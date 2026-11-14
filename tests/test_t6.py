"""Testes da Torre 6 (elegibilidade) com tábua do ZARC sintética, sem rede."""
from datetime import date

import polars as pl
import pytest

from towers.data.zarc import DECENDIOS
from towers.t6_elegibilidade import avaliar_t6
from towers.t6_elegibilidade.torre import impedimentos_socioambientais

GEO = "4100000"


@pytest.fixture
def tabua(tmp_path):
    def linha(cultura, solo, decs):
        return {"Nome_cultura": cultura, "SafraIni": 2026, "geocodigo": GEO, "municipio": "Teste", "UF": "PR",
                "Cod_Solo": solo, "Cod_Ciclo": "21", "Nome_Outros_Manejos": "Sequeiro", "Portaria": "Port.9_de_2026",
                **{d: decs.get(i + 1, 0) for i, d in enumerate(DECENDIOS)}}
    caminho = tmp_path / "zarc.parquet"
    pl.DataFrame([linha("Soja", "14", {29: 20}), linha("Soja", "11", {31: 40})],
                 schema_overrides={d: pl.Int8 for d in DECENDIOS} | {"SafraIni": pl.Int16}).write_parquet(caminho)
    return caminho


CAT = pl.DataFrame([
    {"id_cultura": c, "nome_pt": n, "uso": u, "modo": m, "obrigatoria": True, "escala_cultivo": 0}
    for c, n, u, m in [("soja", "Soja", "agricultura", "safra"), ("cacau", "Cacau", "agricultura", "safra"),
                       ("cafe", "Café", "agricultura", "implantacao"), ("eucalipto", "Eucalipto", "silvicultura", "implantacao")]
])
SOLO = {"classe_ad": "AD 4 (1,10)", "argila": 54.0}


def t6(tabua, plantio=date(2026, 10, 15), **kw):
    r = avaliar_t6(0, 0, plantio, deslocamentos=(0,), culturas=CAT, geocodigo=GEO, solo=SOLO, caminho_zarc=tabua,
                   colapsar_variantes=False, **kw)
    return {row["id_cultura"]: row for row in r.iter_rows(named=True)}


def test_dentro_da_janela_do_zarc_e_elegivel(tabua):
    soja = t6(tabua)["soja"]
    assert soja["status_elegibilidade"] == "elegivel" and soja["financiavel"]
    assert soja["elegivel_proagro"] and soja["elegivel_psr"] and soja["portaria_zarc"] == "Port.9_de_2026"
    assert any("RNC" in a for a in soja["avisos"])


def test_fora_da_janela_e_inelegivel(tabua):
    soja = t6(tabua, plantio=date(2026, 11, 4))["soja"]        # dec31: só no solo AD1, não no AD4
    assert soja["status_elegibilidade"] == "inelegivel" and not soja["elegivel_proagro"] and soja["score_t6"] == 0.0


def test_sem_zarc_perene_e_silvicultura_a_verificar(tabua):
    r = t6(tabua)
    assert r["cacau"]["status_elegibilidade"] == "a_verificar" and r["cacau"]["elegivel_proagro"] is False
    assert r["cafe"]["status_elegibilidade"] == "a_verificar" and r["cafe"]["score_t6"] is None
    assert r["eucalipto"]["status_elegibilidade"] == "a_verificar"


@pytest.mark.parametrize("imovel, esperado", [
    ({"car": "cancelado"}, "inelegivel"),
    ({"car": "ativo", "terra_indigena": True}, "inelegivel"),
    ({"car": "ativo", "embargo_ibama": True}, "condicional"),
    ({"car": "pendente", "embargo_ibama": True}, "inelegivel"),
    ({"car": "ativo"}, "elegivel"),
])
def test_impedimentos_do_imovel_prevalecem(tabua, imovel, esperado):
    soja = t6(tabua, imovel=imovel)["soja"]
    assert soja["status_elegibilidade"] == esperado


def test_aviso_quando_imovel_nao_informado():
    status, motivos, avisos = impedimentos_socioambientais(None)
    assert status is None and not motivos and any("CAR" in a for a in avisos)
    with pytest.raises(ValueError):
        impedimentos_socioambientais({"car": "talvez"})
