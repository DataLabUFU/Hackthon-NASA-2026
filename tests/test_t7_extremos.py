"""Testes da Torre 7 com trechos reais do dados_unificados.csv (nenhum dado inventado).

O CSV fica em data/raw/power/ (fora do git). Sem ele, os testes que precisam de dados são
pulados. Sempre que possível, o valor esperado é recalculado à parte, direto das colunas
brutas do arquivo, para não testar o código contra ele mesmo.
"""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from omegaconf import OmegaConf

from towers.t7_extremos import config, dados, enso, eventos, probabilidade, referencia, tendencia

CSV = dados.CAMINHO_PADRAO


@pytest.fixture(scope="module")
def df():
    if not CSV.exists():
        pytest.skip("dados_unificados.csv não está em data/raw/power/")
    return dados.ler_dados_unificados(CSV)


@pytest.fixture(scope="module")
def ref(df):
    return dados.filtrar_referencia(df)


@pytest.fixture(scope="module")
def bruto():
    """Leitura independente do arquivo, sem passar pelo módulo."""
    if not CSV.exists():
        pytest.skip("dados_unificados.csv não está em data/raw/power/")
    return pd.read_csv(CSV, sep=";", encoding="utf-8-sig")


# ------------------------------------------------------------------------------- leitura
def test_leitura_formato(df):
    assert len(df) == 168_020
    assert df["PONTO"].nunique() == 20
    assert df.groupby("PONTO").size().eq(8_401).all()
    assert df["data"].min() == pd.Timestamp("2000-01-01")
    assert df["data"].max() == pd.Timestamp("2022-12-31")
    assert "﻿YEAR" not in df.columns


def test_decendio_em_datas_reais(df):
    p01 = df[df["PONTO"] == "P01"].set_index("data")["decendio"]
    assert p01[pd.Timestamp("2000-01-10")] == 1
    assert p01[pd.Timestamp("2000-01-11")] == 2
    assert p01[pd.Timestamp("2000-01-31")] == 3
    assert p01[pd.Timestamp("2000-02-29")] == 6
    assert p01[pd.Timestamp("2000-12-31")] == 36
    assert sorted(p01.unique()) == list(range(1, 37))


def test_referencia_exclui_2022(df, ref):
    assert ref["YEAR"].max() == 2021
    assert ref["YEAR"].min() == 2000
    assert len(ref) == len(df) - 20 * 365
    with pytest.raises(ValueError):
        dados.filtrar_referencia(df, ano_fim=2022)


# ------------------------------------------------------------------------------- eventos
def test_chuva_acumulada_3_dias(df, bruto):
    c3 = eventos.chuva_acumulada(df, dias=3)
    p05 = df.index[df["PONTO"] == "P05"]
    chuva = bruto.loc[bruto["PONTO"] == "P05", "PRECTOTCORR"].to_numpy()
    assert c3.loc[p05[:2]].isna().all()                       # sem 3 dias de histórico
    for k in (2, 100, 4_000, 8_400):
        assert c3.loc[p05[k]] == pytest.approx(chuva[k - 2:k + 1].sum())


def test_janelas_nao_cruzam_pontos(df):
    c3 = eventos.chuva_acumulada(df, dias=3)
    q2 = eventos.queda_temperatura(df, dias=2)
    primeiros = df.groupby("PONTO").head(2).index
    assert c3.loc[primeiros].isna().all()
    assert q2.loc[primeiros].isna().all()


def test_queda_temperatura_2_dias(df, bruto):
    q = eventos.queda_temperatura(df, dias=2)
    qa = eventos.queda_temperatura(df, dias=2, absoluto=True)
    idx = df.index[df["PONTO"] == "P12"]
    t2m = bruto.loc[bruto["PONTO"] == "P12", "T2M"].to_numpy()
    for k in (2, 365, 5_000):
        assert q.loc[idx[k]] == pytest.approx(t2m[k - 2] - t2m[k])
        assert qa.loc[idx[k]] == pytest.approx(abs(t2m[k - 2] - t2m[k]))


def test_indicador_evento_limiar(df):
    q = eventos.queda_temperatura(df, dias=2)
    ind = eventos.indicador_evento(q, 4.0)
    assert ind[q.isna()].isna().all()
    assert (ind[q >= 4.0] == 1).all() and (ind[q < 4.0] == 0).all()
    estrito = eventos.indicador_evento(q, 4.0, inclusivo=False)
    assert (estrito[q == 4.0] == 0).all()


def test_dia_do_ano_365():
    d = pd.to_datetime(["2000-02-28", "2000-02-29", "2000-03-01", "2001-03-01", "2000-12-31", "2001-12-31"])
    assert eventos.dia_do_ano_365(d).tolist() == [59, 59, 60, 60, 365, 365]


def test_climatologia_dtr(ref):
    clim = eventos.climatologia_dtr(ref, janela=31)
    assert len(clim) == 20 * 365 and clim["dtr_clim"].notna().all()
    # conferência independente para um dia: média de todas as DTR de P07 cujo dia-365 cai na janela
    p07 = ref[ref["PONTO"] == "P07"]
    doy = eventos.dia_do_ano_365(p07["data"])
    alvo = 10
    vizinhos = {((alvo - 1 + k) % 365) + 1 for k in range(-15, 16)}
    esperado = (p07["T2M_MAX"] - p07["T2M_MIN"])[np.isin(doy, list(vizinhos))].mean()
    obtido = clim.query("PONTO == 'P07' and doy == @alvo")["dtr_clim"].item()
    assert obtido == pytest.approx(esperado)


def test_climatologia_nao_usa_2022(df, ref):
    """Climatologia calculada com a referência não muda se o df completo tiver 2022."""
    c1 = eventos.climatologia_dtr(ref)
    c2 = eventos.climatologia_dtr(dados.filtrar_referencia(df[df["YEAR"] <= 2021]))
    pd.testing.assert_frame_equal(c1, c2)


def test_indicador_estiagem(ref):
    clim = eventos.climatologia_dtr(ref)
    ind = eventos.indicador_estiagem(ref, clim, n_dias=10, limiar_alta=2.0)
    p03 = ref.index[ref["PONTO"] == "P03"]
    anom = ind.loc[p03, "anomalia_dtr"].to_numpy()
    assert np.isnan(ind.loc[p03[:9], "anomalia_media"]).all()
    assert ind.loc[p03[50], "anomalia_media"] == pytest.approx(anom[41:51].mean())
    assert ind.loc[p03[50], "frac_dias_alta"] == pytest.approx((anom[41:51] >= 2.0).mean())


# --------------------------------------------------------------------------- probabilidade
@pytest.fixture(scope="module")
def ind_queda(ref):
    q = eventos.queda_temperatura(ref, dias=2)
    return eventos.indicador_evento(q, 4.0)


def test_indicador_anual_por_decendio(ref, ind_queda):
    anual = probabilidade.indicador_anual_por_unidade(ref, ind_queda, "decendio")
    assert len(anual) == 20 * 22 * 36
    # dec. 1 de 2000 não tem os 2 dias anteriores → inválido; o resto é completo
    assert anual.query("YEAR == 2000 and decendio == 1")["evento"].isna().all()
    assert anual.query("not (YEAR == 2000 and decendio == 1)")["evento"].notna().all()
    # conferência direta num caso: P09, 2010, decêndio 20
    sub = ref[(ref["PONTO"] == "P09") & (ref["YEAR"] == 2010) & (ref["decendio"] == 20)]
    esperado = float((ind_queda.loc[sub.index] == 1).any())
    assert anual.query("PONTO == 'P09' and YEAR == 2010 and decendio == 20")["evento"].item() == esperado


def test_safras_out_mar_sao_21(ref, ind_queda):
    safra = probabilidade.indicador_por_safra(ref, ind_queda, (10, 1), (3, 31))
    validas = safra.dropna(subset=["evento"])
    assert validas.groupby("PONTO").size().eq(21).all()
    assert validas["ano_safra"].min() == 2000 and validas["ano_safra"].max() == 2020


def test_p_algum_direto_dos_anos(ref, ind_queda):
    c3 = eventos.chuva_acumulada(ref, dias=3)
    ind_chuva = eventos.indicador_evento(c3, float(c3.quantile(0.99)), inclusivo=False)
    a = probabilidade.indicador_por_safra(ref, ind_chuva).set_index(["PONTO", "ano_safra"])["evento"]
    b = probabilidade.indicador_por_safra(ref, ind_queda).set_index(["PONTO", "ano_safra"])["evento"]
    algum = probabilidade.combinar_algum(a, b)
    ok = a.notna() & b.notna()
    assert (algum[ok] == np.maximum(a[ok], b[ok])).all()
    assert algum[~ok].isna().all()
    pa, pb, pab = a.groupby("PONTO").mean(), b.groupby("PONTO").mean(), algum.groupby("PONTO").mean()
    assert (pab >= np.maximum(pa, pb) - 1e-12).all() and (pab <= pa + pb + 1e-12).all()


def test_bootstrap_de_anos(ref, ind_queda):
    safra = probabilidade.indicador_por_safra(ref, ind_queda).dropna()
    anos = safra.query("PONTO == 'P01'")["evento"].to_numpy()
    r1 = probabilidade.probabilidade_bootstrap(anos, repeticoes=1000, semente=7)
    r2 = probabilidade.probabilidade_bootstrap(anos, repeticoes=1000, semente=7)
    assert r1["p"][0] == pytest.approx(anos.mean())
    assert r1["n_anos"][0] == len(anos) == 21
    assert r1["ic_inf"][0] == r2["ic_inf"][0] and r1["ic_sup"][0] == r2["ic_sup"][0]
    assert 0 <= r1["ic_inf"][0] <= r1["p"][0] <= r1["ic_sup"][0] <= 1
    # cada réplica é uma média de 21 anos sorteados: os limites são múltiplos de 1/21
    assert (r1["ic_inf"][0] * 21) == pytest.approx(round(r1["ic_inf"][0] * 21))


def test_suavizacao_circular(ref, ind_queda):
    anual = probabilidade.indicador_anual_por_unidade(ref, ind_queda, "decendio")
    tab = probabilidade.tabela_por_unidade(anual, "decendio", repeticoes=200, semente=1)
    p01 = tab[tab["PONTO"] == "P01"].set_index("decendio")
    assert p01.loc[1, "p_clim_suav"] == pytest.approx((p01.loc[36, "p_clim"] + p01.loc[1, "p_clim"] + p01.loc[2, "p_clim"]) / 3)
    assert p01.loc[36, "p_clim_suav"] == pytest.approx((p01.loc[35, "p_clim"] + p01.loc[36, "p_clim"] + p01.loc[1, "p_clim"]) / 3)
    assert p01.loc[1, "n_anos"] == 21 and p01.loc[2, "n_anos"] == 22
    assert ((tab["ic_inf"] <= tab["p_clim"]) & (tab["p_clim"] <= tab["ic_sup"])).all()


def test_tabela_por_safra_reprodutivel(ref, ind_queda):
    safra = probabilidade.indicador_por_safra(ref, ind_queda)
    t1 = probabilidade.tabela_por_safra(safra, repeticoes=300, semente=42)
    t2 = probabilidade.tabela_por_safra(safra, repeticoes=300, semente=42)
    pd.testing.assert_frame_equal(t1, t2)
    assert len(t1) == 20 and t1["n_anos"].eq(21).all()


# --------------------------------------------------------------------------------- config
def test_config_padrao_carrega():
    cfg = config.carregar_config()
    assert cfg.referencia.ano_fim == 2021
    assert cfg.limiares.chuva_extrema.status == "PROVISORIO"
    assert config.limiar_obrigatorio(cfg.limiares.chuva_extrema, "chuva_extrema") == 80.0
    pendente = config.carregar_config(overrides=["limiares.chuva_extrema.valor=null"])
    with pytest.raises(ValueError, match="pendente"):
        config.limiar_obrigatorio(pendente.limiares.chuva_extrema, "chuva_extrema")


def test_config_recusa_2022_e_status_invalido():
    with pytest.raises(ValueError):
        config.carregar_config(overrides=["referencia.ano_fim=2022"])
    with pytest.raises(ValueError):
        config.carregar_config(overrides=["limiares.chuva_extrema.status=OK"])
    with pytest.raises(ValueError, match="DEFINIDO"):
        config.carregar_config(overrides=["limiares.queda_temperatura.status=DEFINIDO", "limiares.queda_temperatura.valor=null"])


def test_config_recusa_chave_desconhecida(tmp_path: Path):
    arq = tmp_path / "x.yaml"
    arq.write_text(OmegaConf.to_yaml({"referencia": {"ano_final": 2021}}), encoding="utf-8")
    with pytest.raises(Exception):
        config.carregar_config(arq)


# ----------------------------------------------------------------------------- referência
@pytest.fixture(scope="module")
def tabelas(ref):
    cfg = config.carregar_config(overrides=["bootstrap.repeticoes=200"])
    diarios = referencia.indicadores_diarios(ref, cfg)
    ind = referencia.tabela_indicadores(ref, diarios)
    return cfg, diarios, ind, referencia.tabela_decendio(ind, cfg), referencia.tabela_safra(ref, diarios, cfg)


def test_indicadores_usam_limiares_da_config(ref, tabelas):
    cfg, diarios, ind, _, _ = tabelas
    c3 = eventos.chuva_acumulada(ref, 3)
    assert (diarios["chuva_extrema"][c3 > 80] == 1).all() and (diarios["chuva_extrema"][c3 <= 80] == 0).all()
    q = eventos.queda_temperatura(ref, 2)
    assert (diarios["queda_brusca"][q >= 5] == 1).all() and (diarios["queda_brusca"][q < 5] == 0).all()
    assert len(ind) == 20 * 22 * 36 and ind["YEAR"].max() == 2021


def test_algum_por_decendio_e_safra(tabelas):
    _, _, ind, dec, saf = tabelas
    ok = ind[["chuva_extrema", "queda_brusca"]].notna().all(axis=1)
    assert (ind.loc[ok, "algum"] == ind.loc[ok, ["chuva_extrema", "queda_brusca"]].max(axis=1)).all()
    for tab in (dec, saf):
        chave = ["PONTO", "decendio"] if "decendio" in tab else ["PONTO"]
        w = tab.pivot_table(index=chave, columns="evento", values="p_clim")
        assert (w["algum"] >= w[["chuva_extrema", "queda_brusca"]].max(axis=1) - 1e-12).all()
        assert (w["algum"] <= w["chuva_extrema"] + w["queda_brusca"] + 1e-12).all()
    assert len(dec) == 3 * 20 * 36 and len(saf) == 3 * 20
    assert saf["n_anos"].eq(21).all()


def test_safra_bate_com_sensibilidade_p06(tabelas):
    """P06 com queda >= 5 °C: 5 de 21 safras (mesmo valor da análise de sensibilidade)."""
    saf = tabelas[4]
    p = saf.query("PONTO == 'P06' and evento == 'queda_brusca'")["p_clim"].item()
    assert p == pytest.approx(5 / 21)


# ------------------------------------------------------------------------------ tendência
@pytest.fixture(scope="module")
def anuais(ref):
    return tendencia.series_anuais(ref)


def test_series_anuais_conferidas(ref, anuais):
    assert len(anuais) == 20 * 22
    p06 = ref[(ref["PONTO"] == "P06") & (ref["YEAR"] == 2015)]
    linha = anuais.query("PONTO == 'P06' and ano == 2015").iloc[0]
    assert linha["chuva_total"] == pytest.approx(p06["PRECTOTCORR"].sum())
    assert linha["tmax_max"] == pytest.approx(p06["T2M_MAX"].max())
    # veranico conferido com itertools.groupby (contagem independente)
    from itertools import groupby
    jm = p06[p06["data"].dt.month <= 3]["PRECTOTCORR"] < 1.0
    esperado = max((len(list(g)) for seco, g in groupby(jm) if seco), default=0)
    assert linha["veranico_jan_mar"] == esperado


def test_tendencia_sen_e_kendall(anuais):
    from scipy import stats
    s = anuais.query("PONTO == 'P06'")
    r = tendencia.tendencia(s["ano"], s["chuva_total"])
    x, y = s["ano"].to_numpy(float), s["chuva_total"].to_numpy()
    inclin = [(y[j] - y[i]) / (x[j] - x[i]) for i in range(len(x)) for j in range(i + 1, len(x))]
    assert r["sen_por_ano"] == pytest.approx(np.median(inclin))
    assert r["p"] == pytest.approx(stats.kendalltau(x, y)[1])
    assert r["n_anos"] == 22


def test_holm_por_ponto(anuais):
    t = tendencia.tendencias_por_ponto(anuais).query("PONTO == 'P06'")
    p = np.sort(t["p"].to_numpy())
    m = len(p)
    holm = np.maximum.accumulate(np.minimum(1, (m - np.arange(m)) * p))
    assert np.allclose(np.sort(t["p_holm"].to_numpy()), holm)


# ----------------------------------------------------------------------------------- ENSO
@pytest.fixture(scope="module")
def ind_e_grupos(ref):
    """Indicador real (queda >= 5 °C por safra, P06) e uma partição REAL dos anos que não é
    ENSO: safras com chuva acima ou abaixo da mediana. Só serve para testar a lógica."""
    q = eventos.indicador_evento(eventos.queda_temperatura(ref), 5.0)
    s = probabilidade.indicador_por_safra(ref, q).query("PONTO == 'P06'").set_index("ano_safra")["evento"].dropna()
    sub = ref[ref["PONTO"] == "P06"]
    md = sub["data"].dt.month
    ano_s = sub["data"].dt.year - (md <= 3).astype(int)
    tot = sub[md.isin([10, 11, 12, 1, 2, 3])].groupby(ano_s)["PRECTOTCORR"].sum().reindex(s.index)
    grupos = pd.Series(np.where(tot > tot.median(), "chuvosa", "seca"), index=s.index)
    return s, grupos


def test_enso_sem_tabela(ind_e_grupos):
    s, _ = ind_e_grupos
    assert enso.probabilidade_enso(s, None, None) == {"enso": "nao_calculado"}


def test_enso_logica_com_particao_real(ind_e_grupos):
    from scipy import stats
    s, g = ind_e_grupos
    r = enso.probabilidade_enso(s, g, "seca", k=10, repeticoes=300, repeticoes_permutacao=2000,
                                fases_validas=("seca", "chuvosa"))
    na = (g == "seca").to_numpy()
    ev = s.to_numpy()
    assert r["n_anos"] == 21 and r["n_anos_fase"] == na.sum()
    assert r["p_clim"] == pytest.approx(ev.mean())
    assert r["p_enso"] == pytest.approx(ev[na].mean())
    esperado = (na.sum() * ev[na].mean() + 10 * ev.mean()) / (na.sum() + 10)
    assert r["p_final"] == pytest.approx(esperado)
    assert min(r["p_enso"], r["p_clim"]) - 1e-12 <= r["p_final"] <= max(r["p_enso"], r["p_clim"]) + 1e-12
    t = [[ev[na].sum(), na.sum() - ev[na].sum()], [ev[~na].sum(), (~na).sum() - ev[~na].sum()]]
    assert r["p_fisher"] == pytest.approx(stats.fisher_exact(np.array(t, dtype=int))[1])
    assert 0 < r["p_permutacao"] <= 1


def test_enso_p_final_sem_anos_da_fase():
    assert enso.p_final(np.nan, 0, 0.3, 10) == 0.3


def test_enso_valida_fases(ind_e_grupos):
    s, g = ind_e_grupos
    with pytest.raises(ValueError):
        enso.probabilidade_enso(s, g, "seca")  # nomes fora de El Niño / La Niña / Neutro


# -------------------------------------------------------------------------------- consulta
from datetime import date

from towers.t7_extremos import consulta


@pytest.fixture(scope="module")
def base():
    if not CSV.exists():
        pytest.skip("dados_unificados.csv não está em data/raw/power/")
    return consulta.preparar_base(config.carregar_config(overrides=["bootstrap.repeticoes=200"]))


def test_consulta_bate_com_janela_de_safra(base, ref):
    """Fase de 01/10 a 31/12 = mesma conta de indicador_por_safra((10, 1), (12, 31))."""
    fases = [{"nome": "out-dez", "inicio": 0, "fim": 91, "eventos": ["chuva_extrema", "queda_brusca"]}]
    tab = consulta.indicadores_por_ano(base, "P06", date(2026, 10, 1), fases).set_index("ano")
    diarios = referencia.indicadores_diarios(ref, base.cfg)
    for ev in ("chuva_extrema", "queda_brusca"):
        s = probabilidade.indicador_por_safra(ref, diarios[ev], (10, 1), (12, 31))
        esperado = s.query("PONTO == 'P06'").set_index("ano_safra")["evento"]
        pd.testing.assert_series_equal(tab[ev], esperado, check_names=False, check_index_type=False)


def test_consulta_saida(base):
    fases = [
        {"nome": "plantio", "inicio": 0, "fim": 20, "eventos": ["chuva_extrema", "queda_brusca"]},
        {"nome": "colheita", "inicio": 110, "fim": 130, "eventos": ["chuva_extrema"]},
    ]
    r = consulta.consultar(base, "P06", date(2026, 10, 20), fases)
    assert r["enso"] == {"enso": "nao_calculado"}
    assert r["n_anos"] == 21  # a safra que começa em 2021 usaria 2022: fica de fora
    pa, pc, po = r["p_algum"]["p"], r["p_chuva_extrema"]["p"], r["p_oscilacao"]["p"]
    assert max(pc, po) - 1e-12 <= pa <= pc + po + 1e-12
    for k in ("p_chuva_extrema", "p_oscilacao", "p_algum"):
        assert r[k]["ic_inf"] <= r[k]["p"] <= r[k]["ic_sup"]
    assert r["confianca"]["limiares"] == "PROVISORIO"


def test_consulta_estiagem(base):
    fases = [{"nome": "plantio", "inicio": 0, "fim": 10, "eventos": ["queda_brusca"]}]
    assert consulta.consultar(base, "P01", date(2000, 1, 5), fases)["indicador_estiagem"]["status"] == "sem_dado"
    est = consulta.consultar(base, "P01", date(2022, 6, 1), fases)["indicador_estiagem"]
    sub = base.completo.query("PONTO == 'P01'")
    trecho = sub[(sub["data"] >= "2022-05-22") & (sub["data"] <= "2022-05-31")]
    assert est["anomalia_media_c"] == pytest.approx(eventos.anomalia_dtr(trecho, base.clim_dtr).mean())


def test_consulta_valida_entrada(base):
    with pytest.raises(ValueError):
        consulta.indicadores_por_ano(base, "P01", date(2026, 10, 1), [{"inicio": 5, "fim": 1, "eventos": []}])
    with pytest.raises(ValueError):
        consulta.indicadores_por_ano(base, "P01", date(2026, 10, 1), [{"inicio": 0, "fim": 1, "eventos": ["geada"]}])
    with pytest.raises(KeyError):
        consulta.indicadores_por_ano(base, "P99", date(2026, 10, 1), [{"inicio": 0, "fim": 1, "eventos": ["queda_brusca"]}])


# ------------------------------------------------------------------------------ coordenadas
def test_pontos_na_grade_e_completos(df):
    p = dados.ler_pontos()
    assert sorted(p["PONTO"]) == sorted(df["PONTO"].unique())
    assert not p.duplicated(["LAT", "LON"]).any()
    for lat, lon in zip(p["LAT"], p["LON"]):
        assert dados.celula_grade(lat, lon) == (lat, lon)  # centro de célula


def test_ponto_da_coordenada():
    assert dados.ponto_da_coordenada(-18.92, -48.27) == "P06"   # ponto de teste da análise preliminar
    assert dados.ponto_da_coordenada(-18.5, -48.75) == "P01"
    assert dados.ponto_da_coordenada(-23.3, -51.2) is None       # Londrina: fora da área


def test_consulta_por_coordenada(base):
    fases = [{"nome": "plantio", "inicio": 0, "fim": 20, "eventos": ["queda_brusca"]}]
    r = consulta.consultar_coordenada(base, -18.92, -48.27, date(2026, 10, 20), fases)
    assert r["ponto"] == "P06" and (r["lat"], r["lon"]) == (-19.0, -48.125)
    assert r == consulta.consultar(base, "P06", date(2026, 10, 20), fases)
    assert consulta.consultar_coordenada(base, -23.3, -51.2, date(2026, 10, 20), fases)["status"] == "fora_da_area"


def test_tabelas_com_coordenadas(tabelas):
    saf = referencia.com_coordenadas(tabelas[4])
    assert list(saf.columns[:3]) == ["PONTO", "LAT", "LON"] and saf[["LAT", "LON"]].notna().all().all()


# ------------------------------------------------------------------------------------ GPD
from towers.t7_extremos import gpd


@pytest.fixture(scope="module")
def chuva_safra_p06(ref):
    s = gpd.serie_safra(ref, eventos.chuva_acumulada(ref, 3))
    return s[s["PONTO"] == "P06"]


def test_serie_safra(chuva_safra_p06):
    dias = chuva_safra_p06.groupby("ano_safra").size()
    assert len(dias) == 21 and set(dias) <= {182, 183}  # 183 quando a safra tem 29/02


def test_declustering_com_r1_bate_com_sequencias(chuva_safra_p06):
    from itertools import groupby
    u = float(chuva_safra_p06["valor"].quantile(0.95))
    for _, sub in chuva_safra_p06.groupby("ano_safra"):
        v = sub["valor"].to_numpy()
        picos, n = gpd.declusterizar(v, u, r=1)
        seqs = [list(g) for acima, g in groupby(v, key=lambda x: x > u) if acima]
        assert len(picos) == len(seqs) and n == sum(map(len, seqs))
        assert np.allclose(picos, [max(s) for s in seqs])


def test_declustering_r3(chuva_safra_p06):
    u = float(chuva_safra_p06["valor"].quantile(0.95))
    pk = gpd.picos_por_safra(chuva_safra_p06, u, r=3)
    assert (pk["pico"] > u).all()
    assert 0 < pk.attrs["n_grupos"] <= pk.attrs["n_excedencias"]
    assert pk.attrs["n_grupos"] < len(gpd.picos_por_safra(chuva_safra_p06, u, r=1))  # r maior junta grupos


def test_ajuste_gpd_bate_com_scipy(chuva_safra_p06):
    from scipy import stats
    a = gpd.ajustar_ponto(chuva_safra_p06, 0.95, 3)
    y = a["picos"]["pico"].to_numpy() - a["u"]
    xi, _, sigma = stats.genpareto.fit(y, floc=0)
    assert a["ok"] and a["xi"] == pytest.approx(xi, abs=1e-3) and a["sigma"] == pytest.approx(sigma, rel=1e-3)


def test_retorno_e_probabilidade_sao_inversos(chuva_safra_p06):
    a = gpd.ajustar_ponto(chuva_safra_p06, 0.95, 3)
    for T in (5, 10, 20):
        z = gpd.nivel_retorno(T, a["u"], a["sigma"], a["xi"], a["lam"])
        assert gpd.prob_safra(z, a["u"], a["sigma"], a["xi"], a["lam"]) == pytest.approx(1 / T)
    with pytest.raises(ValueError):
        gpd.prob_safra(a["u"] - 1, a["u"], a["sigma"], a["xi"], a["lam"])


def test_tendencia_nao_piora_verossimilhanca(chuva_safra_p06):
    a = gpd.ajustar_ponto(chuva_safra_p06, 0.95, 3)
    y, anos = a["picos"]["pico"].to_numpy() - a["u"], a["picos"]["ano_safra"].to_numpy()
    assert gpd.ajustar_gpd_tendencia(y, anos)["nll"] <= a["nll"] + 1e-6
    t = gpd.teste_tendencia_escala(y, anos)
    assert t["deviance"] >= 0 and 0 <= t["p"] <= 1


def test_nivel_retorno_empirico(chuva_safra_p06):
    m = chuva_safra_p06.groupby("ano_safra")["valor"].max().to_numpy()
    z = gpd.nivel_retorno_empirico(m, 10)
    assert m.min() <= z <= m.max()


GPD_RES = config.ROOT / "artifacts" / "t7" / "gpd" / "gpd_por_ponto.csv"


@pytest.mark.skipif(not GPD_RES.exists(), reason="rode antes `python -m scripts.t7_gpd`")
def test_gpd_so_na_chuva_e_nos_aprovados(tabelas):
    res = referencia.ler_resultado_gpd(GPD_RES)
    emp = tabelas[4].query("evento == 'chuva_extrema'").set_index("PONTO")["p_clim"]
    g = res.query("variavel == 'chuva_3d'").set_index("PONTO")
    estaveis = set(g.index[g["gpd_aprovada"]])
    concordam = set(g.index[(g["p_gpd_ic_inf"] <= emp.reindex(g.index)) & (emp.reindex(g.index) <= g["p_gpd_ic_sup"])])
    # sem a regra de concordância: todos os estáveis; com ela: só os que também concordam
    solto = referencia.aplicar_gpd_chuva(tabelas[4], res, 80.0, exigir_concordancia=False)
    assert set(solto.query("evento == 'chuva_extrema' and metodo == 'gpd'")["PONTO"]) == estaveis
    saf = referencia.aplicar_gpd_chuva(tabelas[4], res, 80.0)
    chuva = saf[saf["evento"] == "chuva_extrema"].set_index("PONTO")
    aprovados = estaveis & concordam
    assert set(chuva.index[chuva["metodo"] == "gpd"]) == aprovados
    assert (chuva.loc[sorted(estaveis - concordam), "motivo_metodo"] == "valor empírico fora do IC da GPD").all()
    assert (saf.loc[saf["evento"] != "chuva_extrema", "metodo"] == "empirico").all()
    for p in aprovados:
        assert chuva.loc[p, "p_clim"] == pytest.approx(g.loc[p, "p_gpd"])
    # o valor empírico fica guardado ao lado
    assert np.allclose(chuva["p_empirico"].loc[emp.index], emp)
    with pytest.raises(ValueError, match="outro limiar"):
        referencia.aplicar_gpd_chuva(tabelas[4], res, 70.0)
