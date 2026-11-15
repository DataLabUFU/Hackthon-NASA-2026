import polars as pl
import pytest

from towers.data.ecocrop import (
    CAMINHO_PADRAO, GRADE_CICLO, RE_CONTROLE, carregar_ecocrop, expandir_ciclos, ler_ecocrop_bruto, separar_nome,
)

pytestmark = pytest.mark.skipif(not CAMINHO_PADRAO.exists(), reason="EcoCrop_DB.csv não baixado")


@pytest.fixture(scope="module")
def eco():
    return carregar_ecocrop(baixar=False)


def linha(eco, especie):
    df = eco.filter(pl.col("especie") == especie)
    assert df.height == 1, f"{especie} não encontrada (ou duplicada)"
    return df.row(0, named=True)


# --- integridade ------------------------------------------------------------------------------

def test_ids_e_nomes_unicos(eco):
    assert eco["id_ecoport"].is_unique().all()
    assert eco["especie"].is_unique().all()


def test_faixas_de_temperatura_ordenadas(eco):
    assert eco.filter(~(
        (pl.col("TMIN") <= pl.col("TOPMN")) & (pl.col("TOPMN") <= pl.col("TOPMX")) & (pl.col("TOPMX") <= pl.col("TMAX"))
    )).is_empty()


# --- tópico 5: codificação --------------------------------------------------------------------

def test_nenhum_caractere_de_controle_sobra():
    bruto = ler_ecocrop_bruto()
    textos = bruto.select(pl.col(pl.String)).to_dicts()
    sobras = {c for linha_ in textos for v in linha_.values() if v for c in RE_CONTROLE.findall(v)}
    assert not sobras, f"bytes sem tradução: {sorted(hex(ord(c)) for c in sobras)}"


@pytest.mark.parametrize("especie, trecho", [
    ("Myristica fragrans", "múskathýði"),   # islandês: 0x87 = ý, 0x9B = ð
    ("Centaurea cyanus", "akurprýði"),
])
def test_traducao_de_bytes(especie, trecho):
    nomes = ler_ecocrop_bruto().filter(pl.col("ScientificName") == especie)["COMNAME"][0]
    assert trecho in nomes


# --- tópico 2: KTMP ---------------------------------------------------------------------------

def test_ktmp_sempre_preenchido(eco):
    assert eco["KTMP"].null_count() == 0
    assert set(eco["ktmp_origem"].unique()) == {"ecocrop", "imputado"}


def test_ktmp_imputado_pela_faixa_de_tmin(eco):
    imp = eco.filter(pl.col("ktmp_origem") == "imputado")
    assert (imp.filter(pl.col("TMIN") >= 15)["KTMP"] == 0).all()
    assert (imp.filter(pl.col("TMIN") < 15)["KTMP"] == -1).all()
    soja = linha(eco, "Glycine max")
    assert (soja["KTMP"], soja["ktmp_origem"]) == (-1, "imputado")
    trigo = linha(eco, "Triticum aestivum")
    assert trigo["ktmp_origem"] == "ecocrop"


# --- tópico 3: duplicatas ---------------------------------------------------------------------

@pytest.mark.parametrize("nome, esperado", [
    ("Zea mays ssp. mays", ("Zea mays ssp. mays", "Zea mays", "ssp. mays")),
    ("Setaria sphacelata  var. sericea", ("Setaria sphacelata var. sericea", "Setaria sphacelata", "var. sericea")),
    ("Musa acuminata x balbisiana", ("Musa acuminata x balbisiana", "Musa acuminata x balbisiana", None)),
    ("Urochloa mosambicensis, stolonifera type",
     ("Urochloa mosambicensis stolonifera type", "Urochloa mosambicensis", "stolonifera type")),
    ("Glycine max", ("Glycine max", "Glycine max", None)),
])
def test_separar_nome(nome, esperado):
    assert separar_nome(nome) == esperado


def test_duplicatas_identicas_fundidas(eco):
    milho = linha(eco, "Zea mays")
    assert "Zea mays ssp. mays" in milho["sinonimos"]
    assert milho["foto_conhecido"]  # fotoperíodo veio da entrada ssp. mays
    assert eco.filter(pl.col("especie") == "Zea mays ssp. mays").is_empty()
    assert "Allium cepa var. cepa" in linha(eco, "Allium cepa")["sinonimos"]


def test_variantes_diferentes_continuam_separadas(eco):
    couves = eco.filter(pl.col("binomio") == "Brassica oleracea")
    assert couves.height >= 6
    assert couves["variante"].null_count() == 0
    assert eco.filter(pl.col("binomio") == "Persea americana").height == 4


# --- tópico 4c: silvicultura ------------------------------------------------------------------

@pytest.mark.parametrize("especie, uso", [
    ("Eucalyptus grandis", "silvicultura"),
    ("Coffea arabica", "agricultura"),
    ("Glycine max", "agricultura"),
    ("Hevea brasiliensis", "agricultura"),  # seringueira: tem uso de fruto/forragem na base
])
def test_uso(eco, especie, uso):
    assert linha(eco, especie)["uso"] == uso


# --- modo e colheita --------------------------------------------------------------------------

@pytest.mark.parametrize("especie, modo, colheita", [
    ("Glycine max", "safra", "reprodutiva"),
    ("Zea mays", "safra", "reprodutiva"),
    ("Lycopersicon esculentum", "safra", "reprodutiva"),      # tomate: fruto, apesar de "vegetables"
    ("Lactuca sativa var. capitata", "safra", "vegetativa"),  # alface
    ("Manihot esculenta", "implantacao", "vegetativa"),       # mandioca: raiz
    # Café: CAT = 'materials, medicinals' não indica a colheita → "indefinida" no ECOCROP puro.
    # A lista de culturas obrigatórias corrige (ver test_culturas.py).
    ("Coffea arabica", "implantacao", "indefinida"),
    ("Citrus sinensis", "implantacao", "reprodutiva"),
    ("Saccharum officinarum", "implantacao", "vegetativa"),   # sem LISPA/CAT/PLAT: modo pelo GMIN = 210
    ("Ipomoea batatas", "safra", "vegetativa"),               # sem metadados: colheita pela tabela manual
])
def test_culturas_conhecidas(eco, especie, modo, colheita):
    r = linha(eco, especie)
    assert (r["modo"], r["colheita"]) == (modo, colheita)


def test_colheita_sem_pista_e_indefinida(eco):
    indef = eco.filter(pl.col("colheita") == "indefinida")
    assert indef.height > 0
    assert (indef["colheita_origem"] == "indefinida").all()
    # medicinal/aromática sem outra categoria não ganha tipo de colheita por chute
    so_medicinal = eco.filter(pl.col("CAT") == "medicinals & aromatic")
    assert (so_medicinal["colheita"] == "indefinida").all()


def test_cafe_e_dende_entram_pela_indicacao_de_cultivo(eco):
    # CAT = "materials, ..." (sem categoria agrícola), mas PLAT = "grown on large scale"
    for especie in ("Coffea arabica", "Camellia sinensis", "Elaeis guineensis"):
        linha(eco, especie)


def test_fotoperiodo(eco):
    soja = linha(eco, "Glycine max")
    assert soja["foto_sensivel"] and soja["foto_curto"] and not soja["foto_longo"]
    batata = linha(eco, "Solanum tuberosum")  # aceita as três classes
    assert not batata["foto_sensivel"]


# --- ciclos -----------------------------------------------------------------------------------

def test_ciclo_desconhecido_usa_padrao(eco):
    sem_ciclo = eco.filter((pl.col("modo") == "safra") & ~pl.col("ciclo_conhecido"))
    assert sem_ciclo.height > 0
    assert (sem_ciclo["ciclo_min"] == 90).all() and (sem_ciclo["ciclo_max"] == 180).all()


def test_implantacao_nao_tem_ciclo(eco):
    perenes = eco.filter(pl.col("modo") == "implantacao")
    assert perenes["ciclo_min"].is_null().all() and perenes["ciclo_max"].is_null().all()


def test_expandir_ciclos_soja(eco):
    soja = expandir_ciclos(eco.filter(pl.col("especie") == "Glycine max"))
    # GMIN = 75, GMAX = 180
    assert soja["ciclo_dias"].to_list() == [75, 90, 105, 120, 150, 180]
    assert soja.filter("ciclo_tipico")["ciclo_dias"].to_list() == [120]  # ponto médio 127,5


def test_expandir_ciclos_cobre_todas_as_especies_de_safra(eco):
    exp = expandir_ciclos(eco)
    safra = eco.filter(pl.col("modo") == "safra")
    assert exp["id_ecoport"].n_unique() == safra.height
    assert exp.filter("ciclo_tipico").group_by("id_ecoport").len()["len"].max() == 1
    assert set(exp["ciclo_dias"].unique()) <= set(GRADE_CICLO)
