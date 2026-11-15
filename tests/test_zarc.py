from datetime import date

import polars as pl
import pytest

from towers.data.zarc import DECENDIOS, decendio, indicacao_por_decendio, indicadas_para, inicio_decendio


@pytest.mark.parametrize("d, dec", [(date(2026, 1, 1), 1), (date(2026, 1, 10), 1), (date(2026, 1, 11), 2),
                                    (date(2026, 1, 31), 3), (date(2026, 2, 1), 4), (date(2026, 12, 31), 36)])
def test_decendio(d, dec):
    assert decendio(d) == dec


def test_inicio_decendio():
    assert inicio_decendio(1, 2026) == date(2026, 1, 1)
    assert inicio_decendio(28, 2026) == date(2026, 10, 1)     # outubro = decêndios 28, 29, 30
    assert inicio_decendio(29, 2026) == date(2026, 10, 11)


@pytest.fixture
def tabua(tmp_path):
    def linha(cultura, safra, solo, dec_indicados, risco=20, geo="4100000"):
        return {"Nome_cultura": cultura, "SafraIni": safra, "geocodigo": geo, "Cod_Solo": solo,
                **{d: (risco if i + 1 in dec_indicados else 0) for i, d in enumerate(DECENDIOS)}}
    linhas = [
        linha("Soja", 2026, "11", {29, 30}, risco=30),
        linha("Soja", 2026, "16", {30, 31}, risco=20),      # outro solo: amplia a janela
        linha("Soja", 2025, "11", {1, 2}),                 # safra antiga: ignorada
        linha("Trigo Irrigado", 2026, "11", {10}),         # irrigado: ignorado por padrão
        linha("Trigo", 2026, "11", {16, 17}),
        linha("Cultura sem mapeamento", 2026, "11", {5}),
    ]
    caminho = tmp_path / "zarc.parquet"
    pl.DataFrame(linhas, schema_overrides={d: pl.Int8 for d in DECENDIOS}).write_parquet(caminho)
    return caminho


def test_indicacao_agrega_solos_e_usa_safra_recente(tabua):
    ind = indicacao_por_decendio(caminho=tabua).filter("indicado")
    soja = ind.filter(pl.col("id_cultura") == "soja")
    assert sorted(soja["dec"].to_list()) == [29, 30, 31]
    assert soja.filter(pl.col("dec") == 30)["melhor_risco"].item() == 20       # menor risco entre solos
    assert sorted(ind.filter(pl.col("id_cultura") == "trigo")["dec"].to_list()) == [16, 17]
    assert set(ind["id_cultura"].unique()) == {"soja", "trigo"}


def test_indicadas_para(tabua):
    plantios = [date(2026, 10, 15), date(2026, 6, 1), date(2026, 1, 5)]   # dec 29, 16, 1
    ind = indicadas_para("4100000", plantios, caminho=tabua)
    assert ind == {("soja", date(2026, 10, 15)), ("trigo", date(2026, 6, 1))}
    assert indicadas_para("9999999", plantios, caminho=tabua) == set()


def test_indicacao_por_solo(tabua):
    ind = indicacao_por_decendio(caminho=tabua, por_solo=True).filter("indicado")
    soja = ind.filter(pl.col("id_cultura") == "soja")
    assert sorted(soja.filter(pl.col("cod_solo") == "11")["dec"].to_list()) == [29, 30]
    assert sorted(soja.filter(pl.col("cod_solo") == "16")["dec"].to_list()) == [30, 31]


def test_cod_solo_zarc():
    from towers.t2_hidrica.validacao import cod_solo_zarc
    assert cod_solo_zarc("AD 4 (1,10)") == "14"
    assert cod_solo_zarc("AD 0") == "11" and cod_solo_zarc(None) == "11"
