"""Testes do cliente POWER sem rede: a chamada HTTP é simulada."""
import os
import time
from datetime import date, timedelta

import polars as pl
import pytest

from towers.data import power


def serie_falsa(inicio: date, fim: date, params, faltando=None):
    """DataFrame no formato de baixar_power. ``faltando``: {param: {datas sem dado}}."""
    faltando = faltando or {}
    dias = [inicio + timedelta(days=i) for i in range((fim - inicio).days + 1)]
    return pl.DataFrame(
        {"data": dias, **{p: [None if d in faltando.get(p, ()) else float(d.day) for d in dias] for p in params}},
        schema={"data": pl.Date, **{p: pl.Float64 for p in params}},
    )


@pytest.fixture
def chamadas(monkeypatch):
    """Substitui baixar_power por uma versão local e registra as chamadas."""
    registro = []
    faltando = {}

    def falso(lat, lon, inicio, fim, params, **_):
        registro.append((inicio, fim, tuple(params)))
        return serie_falsa(inicio, fim, params, faltando)

    monkeypatch.setattr(power, "baixar_power", falso)
    return registro, faltando


def test_celula_grade():
    assert power.celula_grade(-23.31, -51.16) == (-23.5, -51.25)
    assert power.celula_grade(0.1, 0.2) == (0.0, 0.0)


def test_consulta_usa_utc_e_converte_ausentes():
    ini, fim = date(2020, 1, 1), date(2020, 1, 5)
    enviado = {}

    class Resp:
        def raise_for_status(self): ...

        def json(self):
            valores = {d.strftime("%Y%m%d"): (-999.0 if d.day == 3 else 1.0)
                       for d in (ini + timedelta(days=i) for i in range(5))}
            return {"properties": {"parameter": {"IMERG_PRECTOT": valores}}}

    class Sessao:
        def get(self, url, params=None, **_):
            enviado.update(params)
            return Resp()

    df = power.baixar_power(0, 0, ini, fim, ["IMERG_PRECTOT"], sessao=Sessao())
    assert enviado["time-standard"] == "UTC"
    assert df["IMERG_PRECTOT"].null_count() == 1 and df.schema["data"] == pl.Date


def test_padroes_da_serie():
    assert power.INICIO_PADRAO == date(2001, 1, 1)
    assert power.CHUVA == "IMERG_PRECTOT" and power.CHUVA in power.PARAMS_T1


# --- cache ------------------------------------------------------------------------------------

def test_cache_evita_nova_chamada(tmp_path, chamadas):
    registro, _ = chamadas
    ini, fim = date(2020, 1, 1), date(2020, 3, 31)
    a = power.clima_diario(-23.3, -51.2, ini, fim, cache_dir=tmp_path)
    b = power.clima_diario(-23.3, -51.2, ini, fim, cache_dir=tmp_path)
    assert len(registro) == 1
    assert a.equals(b) and a.height == 91


def test_cache_baixa_so_o_inicio_que_falta(tmp_path, chamadas):
    registro, _ = chamadas
    power.clima_diario(-23.3, -51.2, date(2020, 1, 1), date(2020, 1, 31), cache_dir=tmp_path)
    df = power.clima_diario(-23.3, -51.2, date(2019, 12, 1), date(2020, 1, 31), cache_dir=tmp_path)
    assert registro[-1][:2] == (date(2019, 12, 1), date(2019, 12, 31))
    assert df.height == 62 and df["data"].is_sorted()


def test_cache_baixa_parametro_novo(tmp_path, chamadas):
    registro, _ = chamadas
    power.clima_diario(-23.3, -51.2, date(2020, 1, 1), date(2020, 1, 31), params=("T2M",), cache_dir=tmp_path)
    df = power.clima_diario(-23.3, -51.2, date(2020, 1, 1), date(2020, 1, 31),
                            params=("T2M", "IMERG_PRECTOT"), cache_dir=tmp_path)
    assert registro[-1][2] == ("IMERG_PRECTOT",)
    assert df.columns[:3] == ["data", "T2M", "IMERG_PRECTOT"]


def test_atualizacao_reprocessa_ultimos_120_dias(tmp_path, chamadas):
    registro, _ = chamadas
    power.clima_diario(-23.3, -51.2, date(2020, 1, 1), date(2020, 12, 31), cache_dir=tmp_path)
    # simula cache salvo ontem
    arquivo = next(tmp_path.iterdir())
    ontem = time.time() - 86400
    os.utime(arquivo, (ontem, ontem))
    power.clima_diario(-23.3, -51.2, date(2020, 1, 1), date(2021, 1, 31), cache_dir=tmp_path)
    assert registro[-1][:2] == (date(2020, 12, 31) - timedelta(days=power.DIAS_REPROCESSAR), date(2021, 1, 31))


def test_dado_reprocessado_substitui_o_antigo(tmp_path, monkeypatch):
    versao = {"valor": 1.0}

    def falso(lat, lon, inicio, fim, params, **_):
        df = serie_falsa(inicio, fim, params)
        return df.with_columns([pl.lit(versao["valor"]).alias(p) for p in params])

    monkeypatch.setattr(power, "baixar_power", falso)
    power.clima_diario(-23.3, -51.2, date(2020, 1, 1), date(2020, 6, 30), params=("T2M",), cache_dir=tmp_path)
    arquivo = next(tmp_path.iterdir())
    os.utime(arquivo, (time.time() - 86400,) * 2)
    versao["valor"] = 2.0  # valor "consolidado"
    df = power.clima_diario(-23.3, -51.2, date(2020, 1, 1), date(2020, 7, 31), params=("T2M",), cache_dir=tmp_path)
    assert df.filter(pl.col("data") == date(2020, 6, 30))["T2M"].item() == 2.0   # reprocessado
    assert df.filter(pl.col("data") == date(2020, 1, 1))["T2M"].item() == 1.0    # fora da janela


# --- lacunas ----------------------------------------------------------------------------------

def test_chuva_nunca_e_preenchida_e_temperatura_so_lacuna_curta():
    dias = [date(2020, 1, d) for d in range(1, 13)]
    df = pl.DataFrame({
        "data": dias,
        "IMERG_PRECTOT": [5.0, None, None, 3.0] + [1.0] * 8,
        #       lacuna de 2 dias ↓↓        lacuna de 4 dias ↓↓↓↓
        "T2M": [10.0, None, None, 16.0, 16.0, None, None, None, None, 26.0, 26.0, None],
    })
    out = power.interpolar_lacunas_curtas(df, ["IMERG_PRECTOT", "T2M"])
    assert out["IMERG_PRECTOT"].null_count() == 2                 # chuva intacta
    assert out["T2M"][1:3].to_list() == [12.0, 14.0]              # lacuna de 2 dias interpolada
    assert out["T2M"][5:9].null_count() == 4                      # lacuna de 4 dias continua nula
    assert out["T2M"][11] is None                                 # cauda não é extrapolada


def test_cauda_do_imerg_fica_nula_e_nao_corta_a_temperatura(tmp_path, chamadas):
    _, faltando = chamadas
    ini, fim = date(2020, 1, 1), date(2020, 3, 31)
    faltando["IMERG_PRECTOT"] = {fim - timedelta(days=i) for i in range(60)}  # ~2 meses de defasagem
    df = power.clima_diario(-23.3, -51.2, ini, fim, params=("T2M", "IMERG_PRECTOT"), cache_dir=tmp_path)
    assert df["data"].max() == fim                       # temperatura até o fim
    assert df["IMERG_PRECTOT"].tail(60).null_count() == 60  # chuva não inventada
    ult = power.ultimo_dia_valido(df, ["T2M", "IMERG_PRECTOT"])
    assert ult["IMERG_PRECTOT"] == fim - timedelta(days=60) and ult["T2M"] == fim


def test_remove_cauda_nao_publicada():
    df = pl.DataFrame({"data": [date(2020, 1, d) for d in (1, 2, 3)], "T2M": [1.0, None, None]})
    assert power._remover_cauda_vazia(df, ["T2M"]).height == 1
