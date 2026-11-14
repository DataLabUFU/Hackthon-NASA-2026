"""Testes da Torre 1 com clima sintético (sem rede, sem ECOCROP)."""
from datetime import date, timedelta

import numpy as np
import polars as pl
import pytest

from towers.t1_aptidao import avaliar_t1
from towers.t1_aptidao.aptidao import (
    agregar_anos, alerta_fotoperiodo, aptidao_por_ano, melhor_ciclo, trapezio,
)
from towers.t1_aptidao.janelas import janelas_climaticas


# --- dados sintéticos --------------------------------------------------------------------------

def clima_sintetico(inicio=date(2001, 1, 1), fim=date(2025, 12, 31), t=22.0, tmin=15.0, chuva=3.0,
                    amplitude_sazonal=0.0, lat=-23.0):
    dias = [inicio + timedelta(days=i) for i in range((fim - inicio).days + 1)]
    j = np.array([d.timetuple().tm_yday for d in dias])
    # hemisfério sul: mais frio perto do dia 180
    saz = amplitude_sazonal * np.cos(2 * np.pi * (j - 15) / 365)
    return pl.DataFrame({
        "data": dias,
        "T2M": t + saz, "T2M_MIN": tmin + saz, "T2M_MAX": t + 7 + saz,
        "IMERG_PRECTOT": np.full(len(dias), chuva),
    })


def cultura(id_cultura="teste", modo="safra", TMIN=10, TOPMN=18, TOPMX=26, TMAX=35, KTMP=-1, KTMPR=None,
            RMIN=150, ROPMN=250, ROPMX=2000, RMAX=3000, ciclo=(90, 150), colheita="reprodutiva",
            foto=(True, True, True), **extra):
    curto, neutro, longo = foto
    base = dict(
        id_cultura=id_cultura, nome_pt=id_cultura.capitalize(), uso="agricultura", modo=modo, colheita=colheita,
        obrigatoria=True, escala_cultivo=0, TMIN=TMIN, TOPMN=TOPMN, TOPMX=TOPMX, TMAX=TMAX, KTMP=KTMP, KTMPR=KTMPR,
        RMIN=RMIN, ROPMN=ROPMN, ROPMX=ROPMX, RMAX=RMAX,
        ciclo_min=ciclo[0] if modo == "safra" else None, ciclo_max=ciclo[1] if modo == "safra" else None,
        chuva_conhecida=True, ciclo_conhecido=True, ktmp_origem="ecocrop", foto_conhecido=True,
        fonte_parametros="teste", foto_curto=curto, foto_neutro=neutro, foto_longo=longo,
        foto_sensivel=not (curto and neutro and longo),
    )
    return base | extra


def catalogo(*culturas):
    return pl.DataFrame(list(culturas), schema_overrides={"ciclo_min": pl.Int64, "ciclo_max": pl.Int64,
                                                         "KTMPR": pl.Int64})


# --- componente 5: trapézio --------------------------------------------------------------------

@pytest.mark.parametrize("x, esperado", [(5, 0.0), (10, 0.0), (14, 0.5), (18, 1.0), (22, 1.0), (26, 1.0),
                                         (30.5, 0.5), (35, 0.0), (40, 0.0)])
def test_trapezio(x, esperado):
    df = pl.DataFrame({"x": [float(x)]})
    v = df.select(trapezio(pl.col("x"), pl.lit(10.0), pl.lit(18.0), pl.lit(26.0), pl.lit(35.0))).item()
    assert v == pytest.approx(esperado)


# --- componente 4: janelas ---------------------------------------------------------------------

def test_janelas_contagem_e_chuva():
    clima = clima_sintetico(fim=date(2005, 12, 31))
    jan = janelas_climaticas(clima, [date(2026, 10, 1)], [90, 120])
    # 90 dias: 5 anos (out/2005 + 90 termina em 30/12). 120 dias: 4 anos (out/2005 + 120 passa do fim da série)
    assert jan.height == 5 + 4
    assert jan.filter(pl.col("ciclo_dias") == 90)["chuva"].unique().to_list() == [270.0]


def test_janela_com_dia_faltando_e_descartada():
    clima = clima_sintetico(fim=date(2005, 12, 31)).with_columns(
        IMERG_PRECTOT=pl.when(pl.col("data") == date(2003, 11, 15)).then(None).otherwise(pl.col("IMERG_PRECTOT")))
    jan = janelas_climaticas(clima, [date(2026, 10, 1)], [90])
    assert 2003 not in jan["ano"].to_list()                        # não vira "seca"
    assert {2001, 2002, 2004, 2005} <= set(jan["ano"].to_list())


def test_janela_que_passa_do_fim_da_serie_e_descartada():
    clima = clima_sintetico(fim=date(2005, 12, 31))
    jan = janelas_climaticas(clima, [date(2026, 11, 1)], [120])
    assert 2005 not in jan["ano"].to_list()


def test_extremos_mensais_com_sazonalidade():
    clima = clima_sintetico(fim=date(2003, 12, 31), amplitude_sazonal=6.0)
    jan = janelas_climaticas(clima, [date(2026, 1, 1)], [365]).row(0, named=True)
    assert jan["t_mes_frio"] < 17.5 and jan["t_mes_quente"] > 26.5   # ±6 °C em torno de 22 (média de 30 dias)


# --- componente 5: aptidão por ano -------------------------------------------------------------

def _apt(clima, cult, plantio=date(2026, 10, 1), dias_fase_inicial=30, fase_floracao=None, **kw):
    """Testes de geada fixam margem 3 °C e fase inicial de 30 dias (independem dos padrões calibrados)."""
    kw.setdefault("margem_geada", 3.0)
    cat = catalogo(cult)
    from towers.data.ecocrop import expandir_ciclos
    safra = expandir_ciclos(cat, chave="id_cultura")
    impl = cat.filter(pl.col("modo") == "implantacao").with_columns(ciclo_dias=pl.lit(365, pl.Int64))
    jan = janelas_climaticas(clima, [plantio], set(safra["ciclo_dias"].to_list()) | {365},
                             dias_fase_inicial=dias_fase_inicial, fase_floracao=fase_floracao)
    return aptidao_por_ano(jan, safra, impl, **kw)


def test_cultura_no_otimo_tem_aptidao_1():
    apt = _apt(clima_sintetico(), cultura())
    assert (apt["aptidao"] == 1.0).all()


def test_cultura_de_clima_frio_e_inapta():
    apt = _apt(clima_sintetico(), cultura(TMIN=0, TOPMN=8, TOPMX=14, TMAX=18))
    assert (apt["aptidao"] == 0.0).all()


def test_falta_de_chuva_limita():
    apt = _apt(clima_sintetico(chuva=0.5), cultura(RMIN=200, ROPMN=600))   # 90 dias → 45 mm
    assert (apt["s_chuva"] == 0.0).all() and (apt["aptidao"] == 0.0).all()
    irrigado = _apt(clima_sintetico(chuva=0.5), cultura(RMIN=200, ROPMN=600), irrigado=True)
    assert (irrigado["aptidao"] == 1.0).all()


def test_modo_chuva_anual():
    # 2 mm/dia: ciclo de 90 dias = 180 mm (< RMIN 200); ano = 730 mm (ótimo)
    clima = clima_sintetico(chuva=2.0)
    c = cultura(ciclo=(90, 90), RMIN=200, ROPMN=300)
    assert (_apt(clima, c)["s_chuva"] == 0.0).all()
    anual = _apt(clima, c, modo_chuva="anual").drop_nulls("chuva_avaliada")
    assert (anual["s_chuva"] == 1.0).all()


def test_geada_com_margem():
    # mínima de 2 °C em julho: KTMP = −1 + margem 3 = 2 → letal
    clima = clima_sintetico().with_columns(
        T2M_MIN=pl.when(pl.col("data").dt.month() == 7).then(2.0).otherwise(pl.col("T2M_MIN")))
    apt = _apt(clima, cultura(ciclo=(120, 120)), plantio=date(2026, 5, 1))
    assert apt["letal"].all() and (apt["aptidao"] == 0.0).all()
    sem_margem = _apt(clima, cultura(ciclo=(120, 120)), plantio=date(2026, 5, 1), margem_geada=0.0)
    assert not sem_margem["letal"].any()
    fora_do_inverno = _apt(clima, cultura(ciclo=(120, 120)), plantio=date(2026, 10, 1))
    assert not fora_do_inverno["letal"].any()


def test_perene_usa_ano_inteiro_e_pegamento():
    # geada em julho mata a perene mesmo plantada em outubro (o ano inteiro conta)
    clima = clima_sintetico().with_columns(
        T2M_MIN=pl.when(pl.col("data").dt.month() == 7).then(1.0).otherwise(pl.col("T2M_MIN")))
    apt = _apt(clima, cultura(modo="implantacao"), plantio=date(2026, 10, 1))
    assert apt["letal"].all()
    # pegamento: plantio na seca (sem chuva nos 90 dias iniciais) derruba a aptidão
    seca = clima_sintetico().with_columns(
        IMERG_PRECTOT=pl.when(pl.col("data").dt.month().is_in([6, 7, 8])).then(0.0).otherwise(4.0))
    na_seca = _apt(seca, cultura(modo="implantacao"), plantio=date(2026, 6, 1))
    nas_aguas = _apt(seca, cultura(modo="implantacao"), plantio=date(2026, 10, 1))
    assert na_seca["s_pegamento"].max() == 0.0 and nas_aguas["s_pegamento"].min() == 1.0


# --- componente 5: agregação ponderada --------------------------------------------------------

def test_peso_da_recencia():
    # anos antigos inaptos (40 °C), recentes ótimos
    clima = clima_sintetico().with_columns(
        T2M=pl.when(pl.col("data").dt.year() < 2013).then(40.0).otherwise(pl.col("T2M")))
    apt = _apt(clima, cultura(ciclo=(90, 90)))
    simples = apt["aptidao"].mean()
    ponderada = agregar_anos(apt, ano_referencia=2026, meia_vida=10)["apt_media"].item()
    quase_simples = agregar_anos(apt, ano_referencia=2026, meia_vida=1e6)["apt_media"].item()
    assert ponderada > simples + 0.1
    assert quase_simples == pytest.approx(simples, abs=1e-4)


def test_p20_ponderado_e_anos_efetivos():
    apt = pl.DataFrame({
        "id_cultura": ["x"] * 5, "plantio": [date(2026, 1, 1)] * 5, "ciclo_dias": [90] * 5,
        "ano": [2026] * 5, "aptidao": [0.0, 0.25, 0.5, 0.75, 1.0], "letal": [False] * 5,
        "s_temp": [1.0] * 5, "s_chuva": [1.0] * 5, "s_pegamento": [1.0] * 5,
    })
    agg = agregar_anos(apt, ano_referencia=2026).row(0, named=True)
    assert agg["apt_p20"] == 0.0           # pesos iguais: 20% acumulado no 1º valor
    assert agg["prob_apta"] == pytest.approx(0.6)
    assert agg["n_anos_efetivos"] == pytest.approx(5.0)


def test_melhor_ciclo_tipico_e_extremo():
    agg = pl.DataFrame({
        "id_cultura": ["x"] * 3, "plantio": [date(2026, 1, 1)] * 3, "ciclo_dias": [60, 90, 120],
        "apt_media": [0.9, 0.6, 0.3],
    })
    ciclos = pl.DataFrame({"id_cultura": ["x"] * 3, "ciclo_dias": [60, 90, 120], "ciclo_tipico": [False, True, False],
                           "ciclo_min": [60] * 3, "ciclo_max": [120] * 3})
    r = melhor_ciclo(agg, ciclos).row(0, named=True)
    assert (r["ciclo_dias"], r["apt_media"], r["score_t1_tipico"]) == (60, 0.9, 0.6)
    assert r["alerta_ciclo_extremo"]


# --- componente 5: fotoperíodo -----------------------------------------------------------------

def foto(lat, plantio, ciclo=120, modo="safra", colheita="reprodutiva", aceita=(True, False, False), zarc=False):
    curto, neutro, longo = aceita
    sens = not (curto and neutro and longo)
    return alerta_fotoperiodo(lat, modo, colheita, sens, curto, neutro, longo, plantio, ciclo, indicada_zarc=zarc)


def test_soja_no_sul_em_outubro_alerta_floracao_atrasada():
    alerta, tipo, horas = foto(-28, date(2026, 10, 15))
    assert alerta and tipo == "floracao_atrasada" and horas > 13


def test_zarc_suprime_o_alerta():
    assert foto(-28, date(2026, 10, 15), zarc=True)[0] is False


def test_plantio_de_fevereiro_nao_alerta():
    alerta, _, horas = foto(-28, date(2026, 2, 15))
    assert not alerta and horas < 12.5


def test_dia_longo_no_norte_alerta_floracao_impedida():
    alerta, tipo, _ = foto(-3, date(2026, 6, 1), aceita=(False, False, True))
    assert alerta and tipo == "floracao_impedida"


def test_pendoamento_so_para_colheita_vegetativa_de_dia_longo():
    assert foto(-30, date(2026, 11, 1), colheita="vegetativa", aceita=(False, True, True))[1] == "pendoamento"
    assert foto(-3, date(2026, 11, 1), colheita="vegetativa", aceita=(False, True, True))[0] is False
    assert foto(-30, date(2026, 11, 1), colheita="vegetativa", aceita=(True, False, False))[0] is False


def test_especie_insensivel_nunca_alerta():
    assert foto(-30, date(2026, 11, 1), aceita=(True, True, True))[0] is False


def test_perene_alerta_se_o_dia_nunca_entra_na_faixa():
    assert foto(-3, date(2026, 1, 1), modo="implantacao", ciclo=None, aceita=(False, False, True))[1] == "floracao_impedida"
    assert foto(-30, date(2026, 1, 1), modo="implantacao", ciclo=None, aceita=(False, False, True))[0] is False


# --- componente 6: ponta a ponta ---------------------------------------------------------------

def test_avaliar_t1_ponta_a_ponta():
    cat = catalogo(
        cultura("boa"),
        cultura("fria", TMIN=0, TOPMN=8, TOPMX=14, TMAX=18),
        cultura("perene", modo="implantacao"),
    )
    clima = clima_sintetico().with_columns(   # IMERG com ~2 meses de atraso no fim da série
        IMERG_PRECTOT=pl.when(pl.col("data") > date(2025, 10, 31)).then(None).otherwise(pl.col("IMERG_PRECTOT")))
    res = avaliar_t1(-23.0, -51.0, date(2026, 10, 15), deslocamentos=(-10, 0, 10), culturas=cat, clima=clima,
                     ano_referencia=2026)
    assert res.height == 3 * 3
    assert res["nome_pt"].null_count() == 0
    boa = res.filter(pl.col("id_cultura") == "boa")
    assert boa["gate_t1"].all() and (boa["score_t1"] == 1.0).all()
    assert not res.filter(pl.col("id_cultura") == "fria")["gate_t1"].any()
    assert res.filter(pl.col("id_cultura") == "perene")["ciclo_dias"].null_count() == 3
    assert res["gate_t1"].to_list() == sorted(res["gate_t1"].to_list(), reverse=True)   # aprovados primeiro
    # 2025: plantio em out/2025 + 90 dias passa do fim do IMERG → janela descartada
    assert boa["n_anos"].max() <= 24


# --- geada por fase (KTMP na fase inicial, KTMPR depois) ----------------------------------------

def test_geada_usa_ktmpr_depois_da_fase_inicial():
    # mínima de 1 °C em julho; KTMP = −1 (fase inicial), KTMPR = −15 (planta estabelecida); margem 3
    clima = clima_sintetico().with_columns(
        T2M_MIN=pl.when(pl.col("data").dt.month() == 7).then(1.0).otherwise(pl.col("T2M_MIN")))
    resistente = cultura(ciclo=(120, 120), KTMPR=-15)
    # plantio em 1/maio: julho cai depois dos 30 dias iniciais → vale o KTMPR → sobrevive
    assert not _apt(clima, resistente, plantio=date(2026, 5, 1))["letal"].any()
    # plantio em 20/junho: julho cai na fase inicial → vale o KTMP → morre
    assert _apt(clima, resistente, plantio=date(2026, 6, 20))["letal"].all()
    # sem KTMPR, usa o KTMP no ciclo todo (conservador)
    assert _apt(clima, cultura(ciclo=(120, 120)), plantio=date(2026, 5, 1))["letal"].all()


def test_duracao_da_fase_inicial_configuravel():
    clima = clima_sintetico().with_columns(
        T2M_MIN=pl.when(pl.col("data").dt.month() == 7).then(1.0).otherwise(pl.col("T2M_MIN")))
    from towers.data.ecocrop import expandir_ciclos
    cat = catalogo(cultura(ciclo=(120, 120), KTMPR=-15))
    safra = expandir_ciclos(cat, chave="id_cultura")
    vazio = cat.filter(pl.lit(False))
    curta = janelas_climaticas(clima, [date(2026, 6, 1)], [120], dias_fase_inicial=15, fase_floracao=None)
    longa = janelas_climaticas(clima, [date(2026, 6, 1)], [120], dias_fase_inicial=45, fase_floracao=None)
    assert not aptidao_por_ano(curta, safra, vazio, margem_geada=3.0)["letal"].any()
    assert aptidao_por_ano(longa, safra, vazio, margem_geada=3.0)["letal"].all()


# --- variantes ---------------------------------------------------------------------------------

def test_variantes_colapsadas_na_melhor():
    cat = catalogo(
        cultura("arroz", nome_pt="Arroz"),
        cultura("arroz--indica", nome_pt="Arroz", TMIN=0, TOPMN=8, TOPMX=14, TMAX=18),   # variante pior
    )
    res = avaliar_t1(-23.0, -51.0, date(2026, 10, 15), deslocamentos=(0,), culturas=cat,
                     clima=clima_sintetico(), ano_referencia=2026, indicadas_zarc=set())
    assert res.height == 1 and res["id_cultura"].item() == "arroz" and res["n_variantes"].item() == 2
    todas = avaliar_t1(-23.0, -51.0, date(2026, 10, 15), deslocamentos=(0,), culturas=cat,
                       clima=clima_sintetico(), ano_referencia=2026, indicadas_zarc=set(), colapsar_variantes=False)
    assert todas.height == 2


def test_zarc_informado_suprime_alerta_no_resultado():
    soja = cultura("soja", foto=(True, False, False), ciclo=(120, 120))
    args = dict(deslocamentos=(0,), culturas=catalogo(soja), clima=clima_sintetico(), ano_referencia=2026)
    sem = avaliar_t1(-28.0, -52.0, date(2026, 10, 15), indicadas_zarc=set(), **args)
    com = avaliar_t1(-28.0, -52.0, date(2026, 10, 15), indicadas_zarc={("soja", date(2026, 10, 15))}, **args)
    assert sem["alerta_foto"].item() and not com["alerta_foto"].item() and com["indicada_zarc"].item()


def test_geada_na_floracao_mata_grao_mesmo_com_ktmpr_baixo():
    """Trigo-like: KTMPR −20 protege a planta, mas a geada na floração (45–70% do ciclo) mata o grão."""
    clima = clima_sintetico().with_columns(
        T2M_MIN=pl.when(pl.col("data").dt.month() == 7).then(1.0).otherwise(pl.col("T2M_MIN")))
    trigo = cultura(ciclo=(120, 120), KTMPR=-20)
    # plantio em 15/maio: floração ≈ 8/jul–7/ago → geada de julho → perde
    assert _apt(clima, trigo, plantio=date(2026, 5, 15), fase_floracao=(0.45, 0.70))["letal"].all()
    # sem a fase de floração, o KTMPR −20 protege
    assert not _apt(clima, trigo, plantio=date(2026, 5, 15), fase_floracao=None)["letal"].any()
    # colheita vegetativa (forragem) não sofre a regra da floração
    forragem = cultura(ciclo=(120, 120), KTMPR=-20, colheita="vegetativa")
    assert not _apt(clima, forragem, plantio=date(2026, 5, 15), fase_floracao=(0.45, 0.70))["letal"].any()
