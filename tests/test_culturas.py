"""Testes do catálogo de culturas (sem rede: GBIF desligado, exceto onde simulado)."""
import polars as pl
import pytest

from towers.data.culturas import (
    COLHEITAS_VALIDAS, carregar_culturas, culturas_exibiveis, ler_obrigatorias, relatorio_excluidas,
)
from towers.data.ecocrop import CAMINHO_PADRAO

pytestmark = pytest.mark.skipif(not CAMINHO_PADRAO.exists(), reason="EcoCrop_DB.csv não baixado")


@pytest.fixture(scope="module")
def cat():
    return carregar_culturas(usar_gbif=False)


def cultura(cat, nome_pt):
    df = cat.filter(pl.col("nome_pt") == nome_pt)
    assert df.height == 1, f"{nome_pt}: {df.height} linhas"
    return df.row(0, named=True)


def test_lista_obrigatoria_valida():
    obrig = ler_obrigatorias()
    assert obrig.height >= 150


def test_toda_cultura_obrigatoria_esta_completa(cat):
    """Nenhuma cultura importante some: nome, colheita definida e parâmetros climáticos."""
    obrig = ler_obrigatorias()
    curadas = cat.filter("obrigatoria")
    assert sorted(curadas["nome_pt"].to_list()) == sorted(obrig["nome_pt"].to_list())
    assert curadas["exibivel"].all()
    assert curadas.select(pl.col("TMIN", "TOPMN", "TOPMX", "TMAX", "KTMP").null_count()).sum_horizontal().item() == 0
    assert curadas["colheita"].is_in(COLHEITAS_VALIDAS).all()


def test_usuario_nunca_ve_nome_cientifico_ou_vazio(cat):
    vis = culturas_exibiveis(cat)
    assert vis["nome_pt"].null_count() == 0
    assert (vis["nome_pt"] != vis["especie"]).all()
    assert vis["colheita"].is_in(COLHEITAS_VALIDAS).all()


def test_ids_unicos(cat):
    assert cat["id_cultura"].is_unique().all()


def test_cafe_tem_colheita_curada(cat):
    cafe = cultura(cat, "Café arábica")
    assert (cafe["colheita"], cafe["colheita_origem"], cafe["modo"]) == ("reprodutiva", "curada", "implantacao")


def test_mesma_especie_vira_culturas_diferentes(cat):
    g, f = cultura(cat, "Sorgo granífero"), cultura(cat, "Sorgo forrageiro")
    assert g["especie"] == f["especie"] == "Sorghum bicolor"
    assert (g["colheita"], f["colheita"]) == ("reprodutiva", "vegetativa")
    assert g["id_cultura"] != f["id_cultura"]


@pytest.mark.parametrize("nome_pt", ["Pinus (taeda)", "Acácia-negra", "Paricá", "Crotalária-spectabilis", "Tungue"])
def test_readmitidas(cat, nome_pt):
    assert cultura(cat, nome_pt)["exibivel"]


@pytest.mark.parametrize("nome_pt, modo", [("Mandioca", "safra"), ("Mamona", "safra"), ("Morango", "safra"),
                                            ("Tomate", "safra"), ("Café arábica", "implantacao")])
def test_modo_forcado(cat, nome_pt, modo):
    c = cultura(cat, nome_pt)
    assert c["modo"] == modo
    if modo == "safra":
        assert c["ciclo_min"] is not None and c["ciclo_max"] is not None


def test_culturas_extra_com_fonte(cat):
    aveia = cultura(cat, "Aveia-preta")
    assert "Avena sativa" in aveia["fonte_parametros"]
    triticale = cultura(cat, "Triticale")
    assert (triticale["TOPMN"], triticale["TOPMX"]) == (15, 25)
    assert "637/2021" in triticale["fonte_parametros"]
    assert cultura(cat, "Trigo")["fonte_parametros"] == "ECOCROP (FAO)"


def test_filtro_de_silvicultura(cat):
    com = culturas_exibiveis(cat)
    sem = culturas_exibiveis(cat, incluir_silvicultura=False)
    assert com.filter(pl.col("uso") == "silvicultura").height >= 11
    assert sem.filter(pl.col("uso") == "silvicultura").is_empty()


def test_sem_gbif_so_obrigatorias_sao_exibidas(cat):
    assert culturas_exibiveis(cat).filter(~pl.col("obrigatoria") & (pl.col("nome_pt_origem") != "grupo")).is_empty()


def test_subespecie_herda_nome_do_grupo_e_variedade_nao(cat):
    abacates = cat.filter(pl.col("binomio") == "Persea americana")
    assert set(abacates["nome_pt"].to_list()) == {"Abacate"}          # ssp. guatemalan/mexican/west indian
    couve_rabano = cat.filter(pl.col("especie") == "Brassica oleracea var. gongyloides")
    assert couve_rabano["nome_pt"].to_list() == [None]               # var. não herda


def test_relatorio_de_excluidas(cat):
    rel = relatorio_excluidas(cat)
    assert rel.height == cat.filter(~pl.col("exibivel")).height
    assert set(rel["motivo"].unique()) <= {
        "erva daninha", "nome repetido", "sem nome brasileiro e colheita indefinida", "sem nome brasileiro",
        "colheita indefinida"}


def test_subespecie_herdada_tem_origem_grupo(cat):
    arroz = cat.filter((pl.col("binomio") == "Oryza sativa") & ~pl.col("obrigatoria"))
    assert arroz.height >= 2 and (arroz["nome_pt_origem"] == "grupo").all() and arroz["exibivel"].all()


def test_nomes_unicos_entre_exibiveis(cat):
    """Fora as subespécies agrupadas sob a cultura-mãe, nenhum nome se repete."""
    vis = culturas_exibiveis(cat).filter(pl.col("nome_pt_origem") != "grupo")
    assert vis["nome_pt"].str.to_lowercase().is_unique().all()


def test_conflito_de_nome():
    from towers.data.culturas import _resolver_conflitos_de_nome
    resto = pl.DataFrame({
        "especie": ["Musa acuminata", "Acacia a", "Acacia b", "Acacia c"],
        "PLAT": ["grown on large scale", "grown on small scale", "grown on large scale", None],
        "colheita": ["reprodutiva", "vegetativa", "vegetativa", "vegetativa"],
        "nome_pt": ["Banana", "Acácia", "Acácia", "Acácia"],
        "nomes_pt_alternativos": [[], ["Acácia-auriculada"], [], []],
        "nome_pt_origem": ["gbif_flora_brasil"] * 4,
    })
    out = _resolver_conflitos_de_nome(resto, {"Banana"})
    nomes = dict(zip(out["especie"], out["nome_pt"]))
    assert nomes["Musa acuminata"] is None                 # curado vence, sem alternativa
    assert nomes["Acacia b"] == "Acácia"                   # larga escala escolhe primeiro
    assert nomes["Acacia a"] == "Acácia-auriculada"        # usa a alternativa livre
    assert nomes["Acacia c"] is None                       # sem alternativa: sai
    assert out.filter("conflito_nome")["especie"].to_list() == ["Musa acuminata", "Acacia c"]


def test_cultura_curada_mantem_id_limpo_mesmo_com_variantes(cat):
    arroz = cat.filter(pl.col("nome_pt") == "Arroz irrigado")
    assert arroz.height >= 2                                            # curada + subespécies herdadas
    assert arroz.filter("obrigatoria")["id_cultura"].to_list() == ["arroz-irrigado"]
    assert all(i.startswith("arroz-irrigado--") for i in arroz.filter(~pl.col("obrigatoria"))["id_cultura"].to_list())



def test_daninhas_fora_da_exibicao_exceto_curadas(cat):
    vis = culturas_exibiveis(cat)
    assert vis.filter(pl.col("daninha") & ~pl.col("obrigatoria")).is_empty()
    assert "Goiaba" in vis["nome_pt"].to_list()            # curada, mesmo marcada como daninha no ECOCROP



def test_tipo_de_cultura():
    from towers.data.culturas import TIPOS_CULTURA, carregar_culturas
    cat = carregar_culturas(usar_gbif=False)
    vis = culturas_exibiveis(cat)
    assert set(vis["tipo_cultura"].unique()) <= set(TIPOS_CULTURA)
    tipo = dict(vis.filter("obrigatoria").select("nome_pt", "tipo_cultura").iter_rows())
    assert tipo["Soja"] == "graos" and tipo["Milho"] == "graos" and tipo["Algodão herbáceo"] == "graos"
    assert tipo["Alface"] == "hortalicas" and tipo["Laranja"] == "frutas" and tipo["Mandioca"] == "raizes"
    assert tipo["Café arábica"] == "industriais_perenes" and tipo["Aveia-preta"] == "forrageiras"
    assert tipo["Eucalipto (grandis)"] == "silvicultura" and tipo["Manjericão"] == "aromaticas"
    so_graos = culturas_exibiveis(cat, tipos=["graos"])
    assert (so_graos["tipo_cultura"] == "graos").all() and so_graos.height < vis.height
    with pytest.raises(ValueError):
        culturas_exibiveis(cat, tipos=["joias"])



def test_arroz_de_sequeiro_e_irrigado(cat):
    seq = cultura(cat, "Arroz")
    irr = cat.filter((pl.col("nome_pt") == "Arroz irrigado") & pl.col("obrigatoria")).row(0, named=True)
    assert seq["id_cultura"] == "arroz" and irr["id_cultura"] == "arroz-irrigado"
    assert (seq["RMIN"], seq["ROPMN"]) == (350, 500) and "Embrapa" in seq["fonte_parametros"]
    assert irr["ROPMN"] >= 1500 and irr["fonte_parametros"] == "ECOCROP (FAO)"     # inundação: só com irrigação
