"""Leitura do NeonDB com conexão falsa: formato do ZARC, fallbacks e caches."""
import json
from datetime import date, datetime, timezone

import polars as pl
import pytest

from towers.data import neon, soilgrids, zarc


class Cursor:
    def __init__(self, linhas):
        self.linhas = linhas

    def fetchall(self):
        return self.linhas

    def fetchone(self):
        return self.linhas[0] if self.linhas else None


class ConexaoFalsa:
    """Responde às consultas pelo nome da tabela; guarda os comandos executados."""

    def __init__(self, respostas):
        self.respostas, self.executados = respostas, []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.executados.append((sql, params))
        for tabela, linhas in self.respostas.items():
            if f"from {tabela}" in sql:
                return Cursor(linhas)
        return Cursor([])


@pytest.fixture
def banco(monkeypatch):
    """Liga o Neon com uma URL fictícia e devolve a conexão falsa (preencha ``respostas``)."""
    con = ConexaoFalsa({})
    neon.url.cache_clear()
    neon._zarc_municipios.cache_clear()
    monkeypatch.setenv("RECOMENDADOR_NEON", "1")
    monkeypatch.setenv("NEON_URL", "postgresql://teste")
    monkeypatch.setattr(neon, "conectar", lambda: con)
    monkeypatch.setattr(neon._envios, "submit", lambda f, *a: f(*a))   # envio síncrono no teste
    yield con
    neon.url.cache_clear()
    neon._zarc_municipios.cache_clear()


def test_desligado_nos_testes():
    neon.url.cache_clear()
    assert not neon.habilitado()
    assert neon.garantir_arquivos() == []


def test_zarc_decodifica_riscos(banco):
    riscos = "0234" + "5" + "-" * 31
    banco.respostas["zarc_vigente"] = [
        ("5208707", 52, "Goiânia", "soja", False, "AD13", "2", "Portaria SPA/MAPA nº 1", 2026, riscos)]
    df = neon.zarc_linhas(["5208707"])
    r = df.row(0, named=True)
    assert (r["UF"], r["municipio"], r["SafraIni"]) == ("GO", "Goiânia", 2026)
    assert [r[f"dec{i}"] for i in range(1, 7)] == [0, 20, 30, 40, 50, None]
    assert df.columns[:9] == ["geocodigo", "UF", "municipio", "id_cultura", "irrigado", "Cod_Solo", "Cod_Ciclo",
                              "Portaria", "SafraIni"]


def test_tabua_sem_parquet_usa_o_banco(banco, monkeypatch, tmp_path):
    monkeypatch.setattr(zarc, "CAMINHO_PADRAO", tmp_path / "nao_existe.parquet")
    banco.respostas["zarc_vigente"] = [
        ("5208707", 52, "Goiânia", "soja", False, "AD13", "2", "P1", 2026, "2" * 36),
        ("5208707", 52, "Goiânia", "arroz-irrigado", True, "AD13", "2", "P2", 2026, "3" * 36)]
    seco = zarc.tabua(["5208707"], zarc.CAMINHO_PADRAO).collect()
    assert seco["id_cultura"].to_list() == ["soja"]
    todos = zarc.tabua(["5208707"], zarc.CAMINHO_PADRAO, incluir_irrigado=True).collect()
    assert todos.height == 2
    assert zarc.zarc_disponivel(zarc.CAMINHO_PADRAO)
    ind = zarc.indicadas_para("5208707", [date(2026, 1, 5)], zarc.CAMINHO_PADRAO)
    assert ind == {("soja", date(2026, 1, 5))}


def test_banco_fora_do_ar_nao_derruba(banco, monkeypatch):
    def falha():
        raise OSError("sem rede")
    monkeypatch.setattr(neon, "conectar", falha)
    assert neon.zarc_linhas(["123"]) is None
    assert neon.ler_soilgrids("textura", 0, 0) == (False, None)
    assert neon.garantir_arquivos(["nao/existe.csv"]) == []


def test_garantir_arquivos_grava_o_que_falta(banco, tmp_path):
    banco.respostas["arquivos"] = [("data/raw/x.csv", b"a,b\n1,2\n")]
    (tmp_path / "data/raw").mkdir(parents=True)
    (tmp_path / "data/raw/ja_existe.csv").write_text("ok")
    gravados = neon.garantir_arquivos(["data/raw/x.csv", "data/raw/ja_existe.csv"], raiz=tmp_path)
    assert gravados == ["data/raw/x.csv"] and (tmp_path / "data/raw/x.csv").read_bytes() == b"a,b\n1,2\n"
    assert banco.executados[0][1] == (["data/raw/x.csv"],)   # só pede o que falta


def test_soilgrids_le_do_banco_antes_da_api(banco, monkeypatch, tmp_path):
    monkeypatch.setattr(soilgrids, "CACHE_PADRAO", tmp_path)
    banco.respostas["soilgrids_cache"] = [({"areia": 30.0, "silte": 20.0, "argila": 50.0, "distancia_graus": 0.0},)]

    def api(*a):
        raise AssertionError("não deveria chamar a API")
    t = soilgrids.textura(-16.0, -49.0, cache_dir=tmp_path, consulta=api)
    assert t["argila"] == 50.0
    assert json.loads((tmp_path / "textura_-16.000_-49.000.json").read_text())["argila"] == 50.0


def test_soilgrids_envia_consulta_nova(banco, monkeypatch, tmp_path):
    monkeypatch.setattr(soilgrids, "CACHE_PADRAO", tmp_path)
    t = soilgrids.textura(-16.0, -49.0, cache_dir=tmp_path,
                          consulta=lambda la, lo: {"areia": 1.0, "silte": 2.0, "argila": 97.0})
    assert t["argila"] == 97.0
    sql, params = banco.executados[-1]
    assert "insert into soilgrids_cache" in sql and json.loads(params[3])["argila"] == 97.0


def test_soilgrids_cache_fora_do_padrao_nao_usa_banco(banco, tmp_path):
    soilgrids.textura(-16.0, -49.0, cache_dir=tmp_path, consulta=lambda la, lo: None)
    assert banco.executados == []


def test_power_le_celula_do_banco(banco, tmp_path):
    df = pl.DataFrame({"data": [date(2026, 1, 1)], "T2M": [25.0]})
    df.write_parquet(tmp_path / "orig.parquet")
    quando = datetime(2026, 1, 2, tzinfo=timezone.utc)
    banco.respostas["power_cache"] = [((tmp_path / "orig.parquet").read_bytes(), quando)]
    destino = tmp_path / "power" / "celula.parquet"
    assert neon.ler_power(-16.0, -49.375, "utc", destino)
    assert pl.read_parquet(destino).equals(df) and destino.stat().st_mtime == quando.timestamp()
