"""Testes da Torre 7 com trechos REAIS do dados_unificados.csv (nenhum dado inventado).

O CSV fica em data/raw/power/ (fora do git). Sem ele, os testes que precisam de dados são
pulados, como os testes da T1 sem o EcoCrop_DB.csv. Os valores esperados são recalculados à
parte, direto das colunas brutas do arquivo.
"""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from omegaconf import OmegaConf

from towers.t7_extremos import config, dados, eventos, probabilidade

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
    with pytest.raises(ValueError, match="pendente"):
        config.limiar_obrigatorio(cfg.limiares.chuva_extrema, "chuva_extrema")


def test_config_recusa_2022_e_status_invalido():
    with pytest.raises(ValueError):
        config.carregar_config(overrides=["referencia.ano_fim=2022"])
    with pytest.raises(ValueError):
        config.carregar_config(overrides=["limiares.chuva_extrema.status=OK"])
    with pytest.raises(ValueError, match="DEFINIDO"):
        config.carregar_config(overrides=["limiares.queda_temperatura.status=DEFINIDO"])


def test_config_recusa_chave_desconhecida(tmp_path: Path):
    arq = tmp_path / "x.yaml"
    arq.write_text(OmegaConf.to_yaml({"referencia": {"ano_final": 2021}}), encoding="utf-8")
    with pytest.raises(Exception):
        config.carregar_config(arq)
