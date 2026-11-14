"""Testes da Torre 2 (balanço hídrico) com dados sintéticos, sem rede."""
from datetime import date, timedelta

import numpy as np
import polars as pl
import pytest

from towers.data import soilgrids
from towers.data.fao56 import curva_kc, ler_parametros, parametros_t2
from towers.data.ptf_zarc import CAMINHO_PADRAO as PTF_CSV, _inteiros_somando_100, agua_disponivel
from towers.t2_hidrica import avaliar_t2
from towers.t2_hidrica.balanco import simular
from towers.t2_hidrica.estado_inicial import fracao_disponivel


# --- balanço hídrico ---------------------------------------------------------------------------

def _sim(P, et0=5.0, kc=1.0, taw=100.0, p=0.5, dr0=0.0, T=60, pre=0):
    n = 1
    return simular(np.full((n, T), P), np.full((n, T), et0), np.full((n, T), kc), np.array([taw]),
                   np.array([p]), np.array([dr0]), pre, np.array([[0, T]]))


def test_chuva_farta_sem_deficit():
    r = _sim(P=10.0)
    assert r["eta"][0] == pytest.approx(r["etc"][0])


def test_sem_chuva_gera_deficit():
    r = _sim(P=0.0)
    assert r["eta"][0] < 0.6 * r["etc"][0]
    # sem estresse enquanto a depleção ≤ RAW (50 mm a 5 mm/dia = 10 dias)
    r10 = _sim(P=0.0, T=10)
    assert r10["eta"][0] == pytest.approx(r10["etc"][0])


def test_solo_inicialmente_seco_estressa_desde_o_inicio():
    seco = _sim(P=0.0, T=10, dr0=90.0)
    assert seco["eta"][0] < seco["etc"][0]


def test_dias_pre_nao_entram_nas_metricas():
    r = simular(np.zeros((1, 15)), np.full((1, 15), 5.0), np.full((1, 15), 1.0), np.array([100.0]),
                np.array([0.5]), np.array([0.0]), 5, np.array([[0, 10]]))
    assert r["etc"][0] == pytest.approx(50.0)   # só os 10 dias da cultura


# --- parâmetros FAO-56 -------------------------------------------------------------------------

@pytest.mark.parametrize("dur", [30, 45, 90, 120, 365])
def test_curva_kc(dur):
    kc, (c0, c1) = curva_kc(0.3, 1.2, 0.5, (0.15, 0.25, 0.40, 0.20), dur)
    assert len(kc) == dur and 0 < c0 < c1 <= dur
    assert kc[0] == pytest.approx(0.3) and kc.max() == pytest.approx(1.2)
    assert (kc[c0:c1] == 1.2).all()


def test_tabela_fao56_valida():
    par = ler_parametros()
    assert par.filter(pl.col("chave").str.starts_with("grupo:")).height == 11
    assert par.select(pl.min_horizontal(pl.col("raiz_m", "p", "kc_mid").min())).item() > 0
    assert par.filter(pl.col("chave").str.starts_with("grupo:"))["ky"].null_count() == 0   # grupos sempre têm Ky


def _cat(**extra):
    base = dict(id_cultura="x", nome_pt="X", uso="agricultura", modo="safra", colheita="reprodutiva",
                CAT="cereals & pseudocereals", obrigatoria=False, escala_cultivo=2, ciclo_min=90, ciclo_max=120)
    return base | extra


@pytest.mark.parametrize("extra, grupo", [
    ({}, "cereais"),
    ({"CAT": "pulses (grain legumes)"}, "leguminosas_grao"),
    ({"CAT": "vegetables", "colheita": "vegetativa"}, "hortalicas_folhosas"),
    ({"CAT": "vegetables"}, "hortalicas_fruto"),
    ({"modo": "implantacao", "CAT": "fruits & nuts"}, "frutiferas_perenes"),
    ({"uso": "silvicultura", "modo": "implantacao", "CAT": "forest/wood"}, "silvicultura"),
    ({"CAT": None}, "outras_anuais"),
])
def test_grupo_fao(extra, grupo):
    r = parametros_t2(pl.DataFrame([_cat(**extra)])).row(0, named=True)
    assert (r["grupo_fao"], r["parametros_t2_origem"]) == (grupo, "grupo")


def test_valor_especifico_prevalece_sobre_o_grupo():
    r = parametros_t2(pl.DataFrame([_cat(id_cultura="soja", CAT="pulses (grain legumes)")])).row(0, named=True)
    assert r["parametros_t2_origem"] == "cultura" and r["ky"] == pytest.approx(0.85)


# --- solo --------------------------------------------------------------------------------------

def test_textura_normalizada_soma_100():
    assert sum(_inteiros_somando_100(64.6, 14.3, 21.4)) == 100
    assert _inteiros_somando_100(33.33, 33.33, 33.34) in {(33, 33, 34), (34, 33, 33), (33, 34, 33)}


@pytest.mark.skipif(not PTF_CSV.exists(), reason="tabela da PTF não baixada")
def test_ptf_zarc_valores_plausiveis():
    arenoso = agua_disponivel(85, 5, 10)["ad_mm_cm"]
    medio = agua_disponivel(65, 14, 21)["ad_mm_cm"]
    argiloso = agua_disponivel(19, 27, 54)["ad_mm_cm"]
    assert arenoso < medio < argiloso
    assert 0.7 < medio < 1.0 and 1.0 < argiloso < 1.3


def test_soilgrids_procura_vizinho_quando_ponto_sem_dado(tmp_path):
    chamadas = []

    def falsa(lat, lon):
        chamadas.append((lat, lon))
        return None if len(chamadas) < 3 else {"areia": 40.0, "silte": 20.0, "argila": 40.0}

    t = soilgrids.textura(-23.3, -51.2, cache_dir=tmp_path, consulta=falsa)
    assert t["argila"] == 40.0 and t["distancia_graus"] == 0.02 and len(chamadas) == 3
    soilgrids.textura(-23.3, -51.2, cache_dir=tmp_path, consulta=falsa)   # cache
    assert len(chamadas) == 3


# --- estado inicial ----------------------------------------------------------------------------

def test_fracao_normalizada_pelo_historico_local():
    dias = [date(2020, 1, 1) + timedelta(days=i) for i in range(101)]
    clima = pl.DataFrame({"data": dias, "GWETROOT": np.linspace(0.6, 1.0, 101)})
    d, f = fracao_disponivel(clima)
    assert d == dias[-1] and f == pytest.approx(1.0)
    _, meio = fracao_disponivel(clima, dias[50])
    assert meio == pytest.approx(0.5, abs=0.02)


# --- ponta a ponta -----------------------------------------------------------------------------

def clima_t2(chuva=4.0, gwet=0.8, fim=date(2025, 12, 31)):
    dias = [date(2001, 1, 1) + timedelta(days=i) for i in range((fim - date(2001, 1, 1)).days + 1)]
    n = len(dias)
    rng = np.random.default_rng(0)
    return pl.DataFrame({
        "data": dias, "T2M": np.full(n, 22.0), "T2M_MIN": np.full(n, 16.0), "T2M_MAX": np.full(n, 28.0),
        "IMERG_PRECTOT": np.full(n, chuva), "RH2M": np.full(n, 70.0), "WS2M": np.full(n, 2.0),
        "ALLSKY_SFC_SW_DWN": np.full(n, 20.0), "PS": np.full(n, 94.0),
        "GWETROOT": np.clip(gwet + rng.normal(0, 0.05, n), 0, 1),
    })


def catalogo_t2():
    return pl.DataFrame([
        _cat(id_cultura="soja", nome_pt="Soja", CAT="pulses (grain legumes)", ciclo_min=105, ciclo_max=150),
        _cat(id_cultura="laranja", nome_pt="Laranja", modo="implantacao", CAT="fruits & nuts",
             ciclo_min=None, ciclo_max=None),
    ], schema_overrides={"ciclo_min": pl.Int64, "ciclo_max": pl.Int64})


SOLO = {"ad_mm_cm": 1.1, "classe_ad": "AD 4 (1,10)", "origem": "teste"}


def test_avaliar_t2_umido_vs_seco():
    args = dict(deslocamentos=(0,), culturas=catalogo_t2(), solo=SOLO, ano_referencia=2026)
    umido = avaliar_t2(-23.0, -51.0, date(2025, 10, 1), clima=clima_t2(chuva=6.0), **args)
    seco = avaliar_t2(-23.0, -51.0, date(2025, 10, 1), clima=clima_t2(chuva=0.5), **args)
    su, ss = (d.filter(pl.col("id_cultura") == "soja").row(0, named=True) for d in (umido, seco))
    assert su["score_t2"] > 0.95 and su["prob_perda20"] == 0
    assert ss["score_t2"] < 0.6 and ss["prob_perda20"] > 0.9 and ss["irrigacao_mm_med"] > 200
    assert ss["prob_isna_critico"] > 0.9
    assert umido.filter(pl.col("id_cultura") == "laranja")["ciclo_dias"].to_list() == [None]


def test_irrigado_zera_a_queda_mas_informa_a_lamina():
    r = avaliar_t2(-23.0, -51.0, date(2025, 10, 1), deslocamentos=(0,), culturas=catalogo_t2(), solo=SOLO,
                   clima=clima_t2(chuva=0.5), ano_referencia=2026, irrigado=True)
    soja = r.filter(pl.col("id_cultura") == "soja").row(0, named=True)
    assert soja["score_t2"] == pytest.approx(1.0) and soja["irrigacao_mm_med"] > 200


def test_plantio_futuro_parte_do_estado_atual():
    """Último GWETROOT em 31/12/2025; plantio 20 dias depois → 20 dias de solo nu antes do ciclo."""
    clima = clima_t2(chuva=0.0, gwet=0.95)
    r = avaliar_t2(-23.0, -51.0, date(2026, 1, 20), deslocamentos=(0,), culturas=catalogo_t2(), solo=SOLO,
                   clima=clima, ano_referencia=2026)
    soja = r.filter(pl.col("id_cultura") == "soja").row(0, named=True)
    assert soja["data_estado_solo"] == date(2025, 12, 31) and soja["score_t2"] < 0.5


# --- restrição de ciclos e estado climatológico ------------------------------------------------

def test_restringir_ciclos_pela_duracao_fao_e_pelo_tipico():
    from towers.data.ecocrop import expandir_ciclos
    from towers.t2_hidrica.torre import restringir_ciclos
    cat = pl.DataFrame([
        _cat(id_cultura="milho", ciclo_min=65, ciclo_max=365, duracao_fao=150),     # faixa FAO: 105–195
        _cat(id_cultura="outra", ciclo_min=60, ciclo_max=180, duracao_fao=None),     # típico (120) ± 1 passo
    ], schema_overrides={"ciclo_min": pl.Int64, "ciclo_max": pl.Int64, "duracao_fao": pl.Int64})
    r = restringir_ciclos(expandir_ciclos(cat, chave="id_cultura"))
    milho = r.filter(pl.col("id_cultura") == "milho")
    assert milho["ciclo_dias"].to_list() == [105, 120, 150, 180]
    assert milho.filter("ciclo_referencia")["ciclo_dias"].to_list() == [150]
    assert r.filter(pl.col("id_cultura") == "outra")["ciclo_dias"].to_list() == [105, 120, 150]


def test_estado_climatologico_e_score_tipico():
    r = avaliar_t2(-23.0, -51.0, date(2025, 10, 1), deslocamentos=(0,), culturas=catalogo_t2(), solo=SOLO,
                   clima=clima_t2(chuva=6.0), ano_referencia=2026, estado_inicial="climatologico")
    soja = r.filter(pl.col("id_cultura") == "soja").row(0, named=True)
    assert soja["estado_inicial"] == "climatologico" and soja["score_t2"] > 0.95
    assert soja["score_t2_tipico"] is not None and soja["score_t2_tipico"] <= soja["score_t2"] + 1e-9
    with pytest.raises(ValueError):
        avaliar_t2(-23.0, -51.0, date(2025, 10, 1), culturas=catalogo_t2(), solo=SOLO, clima=clima_t2(),
                   estado_inicial="outro")
