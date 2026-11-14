"""Testes da resolução de nomes (GBIF simulado, sem rede)."""
import polars as pl

from towers.data import taxonomia
from towers.data.taxonomia import escolher_nomes, nomes_pt_brasil, slug

FLORA = "Flora e Funga do Brasil - Lista Oficial"


def test_so_aceita_nomes_da_flora_do_brasil():
    nomes = ["Pêra-abacate", "abacate", "abacate", "abacateiro", "louro-abacate"]
    fontes = ["Catalogue of Life", "Catalogue of Life", FLORA, FLORA, FLORA]
    principal, alt = escolher_nomes(nomes, fontes)
    assert principal == "Abacate"               # aparece em 2 fontes
    assert "Pêra-abacate" not in alt            # nome de Portugal (fora da Flora do Brasil)
    assert alt == ["Abacateiro", "Louro-abacate"]


def test_sem_nome_brasileiro():
    assert escolher_nomes(["fidalguinhos"], ["DAISIE"]) == (None, [])
    assert escolher_nomes([], []) == (None, [])


def test_empate_vai_para_o_mais_curto():
    principal, _ = escolher_nomes(["guandu", "feijão-guandu"], [FLORA, FLORA])
    assert principal == "Guandu"


def test_cache_consulta_so_o_que_falta(tmp_path):
    chamadas = []

    def falso(especie):
        chamadas.append(especie)
        return {"especie": especie, "gbif_key": 1, "gbif_rank": "SPECIES", "gbif_match": "EXACT",
                "nome_aceito": especie, "nomes_pt": ["teste"], "fontes_pt": [FLORA]}

    cache = tmp_path / "nomes.parquet"
    nomes_pt_brasil(["A a", "B b"], cache=cache, consultar=falso, workers=1)
    df = nomes_pt_brasil(["A a", "B b", "C c"], cache=cache, consultar=falso, workers=1)
    assert chamadas == ["A a", "B b", "C c"]
    assert df["nome_pt"].to_list() == ["Teste"] * 3


def test_erro_de_rede_nao_vai_para_o_cache(tmp_path):
    import requests

    def falha(especie):
        raise requests.ConnectionError("sem rede")

    cache = tmp_path / "nomes.parquet"
    df = nomes_pt_brasil(["A a"], cache=cache, consultar=falha, workers=1)
    assert df["nome_pt"].to_list() == [None]
    assert not cache.exists()


def test_variedade_usa_nomes_do_proprio_taxon(monkeypatch):
    """Brócolis (var. italica) não pode herdar 'couve, repolho' da espécie."""
    pedidos = []

    class Resp:
        def __init__(self, dados): self.dados = dados
        def json(self): return self.dados

    class Sessao:
        def get(self, url, params=None, **_):
            pedidos.append(url)
            if url.endswith("/match"):
                return Resp({"usageKey": 111, "acceptedUsageKey": 222, "rank": "VARIETY", "matchType": "EXACT",
                             "canonicalName": "Brassica oleracea italica", "species": "Brassica oleracea"})
            return Resp({"results": []})

    r = taxonomia.consultar_gbif("Brassica oleracea var. italica", sessao=Sessao())
    assert pedidos[-1].endswith("/111/vernacularNames")
    assert r["nomes_pt"] == []


def test_casamento_nao_exato_nao_busca_nomes():
    class Resp:
        def json(self): return {"usageKey": 9, "rank": "GENUS", "matchType": "HIGHERRANK"}

    class Sessao:
        def __init__(self): self.n = 0
        def get(self, *a, **k):
            self.n += 1
            return Resp()

    s = Sessao()
    r = taxonomia.consultar_gbif("Lycopersicon esculentum", sessao=s)
    assert s.n == 1 and r["nomes_pt"] == []


def test_slug():
    assert slug("Café arábica") == "cafe-arabica"
    assert slug("Capim-colonião / Mombaça") == "capim-coloniao-mombaca"
