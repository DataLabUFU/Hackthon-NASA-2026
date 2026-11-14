"""Benchmark da T3 contra o plantio real (PAM/IBGE).

Referência: se uma cultura ocupa área relevante num município (PAM, área plantada ≥ ``AREA_MIN_HA``),
o solo de lá comprovadamente a suporta. A T3 não deveria eliminá-la.

Métricas (pares município × cultura com a cultura na PAM):
- ``eliminacao_indevida``: % das culturas cultivadas com score_t3 ≤ 0,2 (erro grave);
- ``score_alto``: % das cultivadas com score_t3 ≥ 0,8;
- ``auc``: probabilidade de uma cultura cultivada no município ter score maior que uma não cultivada
  (empates = 0,5). Clima e mercado também explicam o que se planta, então o AUC esperado é modesto;
  o principal indicador é a eliminação indevida.

API SIDRA (tabela 5457, variável 8331 = área plantada ou destinada à colheita):
https://apisidra.ibge.gov.br/
"""
from __future__ import annotations

import logging

import polars as pl
import requests

from towers.data.culturas import carregar_culturas, culturas_exibiveis
from towers.data.municipios import carregar_municipios

from .aptidao import aptidao_solo
from .perfil import perfil_solo

log = logging.getLogger(__name__)

URL_SIDRA = "https://apisidra.ibge.gov.br/values/t/5457/n6/{municipios}/v/8331/p/last%201/c782/all"
AREA_MIN_HA = 100.0
ELIMINADA = 0.2

# Produto da PAM → nome da cultura no catálogo (lista curada)
PAM_PARA_NOME = {
    "Abacate": "Abacate", "Abacaxi*": "Abacaxi", "Abóbora": "Abóbora", "Açaí": "Açaí", "Acerola": "Acerola",
    "Alfafa fenada": "Alfafa", "Alface": "Alface", "Algodão arbóreo (em caroço)": "Algodão arbóreo",
    "Algodão herbáceo (em caroço)": "Algodão herbáceo", "Alho": "Alho", "Amendoim (em casca)": "Amendoim",
    "Arroz (em casca)": "Arroz", "Aveia (em grão)": "Aveia-branca", "Azeitona": "Azeitona (oliveira)",
    "Banana (cacho)": "Banana", "Batata-doce": "Batata-doce", "Batata-inglesa": "Batata",
    "Borracha (látex coagulado)": "Seringueira", "Borracha (látex líquido)": "Seringueira",
    "Cacau (em amêndoa)": "Cacau", "Café (em grão) Arábica": "Café arábica",
    "Café (em grão) Canephora": "Café conilon (canéfora)", "Caju": "Caju", "Castanha de caju": "Caju",
    "Cana-de-açúcar": "Cana-de-açúcar", "Cana para forragem": "Cana-de-açúcar", "Canola": "Canola",
    "Caqui": "Caqui", "Cebola": "Cebola", "Cenoura": "Cenoura", "Centeio (em grão)": "Centeio",
    "Cevada (em grão)": "Cevada", "Chá-da-índia (folha verde)": "Chá-da-índia", "Chuchu": "Chuchu",
    "Coco-da-baía*": "Coco-da-baía", "Cupuaçu": "Cupuaçu", "Dendê (cacho de coco)": "Dendê",
    "Erva-mate (folha verde)": "Erva-mate", "Ervilha (em grão)": "Ervilha", "Fava (em grão)": "Fava",
    "Feijão (em grão)": "Feijão", "Figo": "Figo", "Fumo (em folha)": "Fumo", "Gergelim": "Gergelim",
    "Girassol (em grão)": "Girassol", "Goiaba": "Goiaba", "Graviola": "Graviola", "Guaraná (semente)": "Guaraná",
    "Inhame": "Inhame", "Juta (fibra)": "Juta", "Laranja": "Laranja", "Limão": "Limão", "Linho (semente)": "Linhaça",
    "Maçã": "Maçã", "Malva (fibra)": "Malva (fibra)", "Mamão": "Mamão", "Mamona (baga)": "Mamona",
    "Mandioca": "Mandioca", "Manga": "Manga", "Maracujá": "Maracujá", "Marmelo": "Marmelo", "Melancia": "Melancia",
    "Melão": "Melão", "Milho (em grão)": "Milho", "Milho verde": "Milho", "Morango": "Morango",
    "Noz (fruto seco)": "Nogueira-pecã", "Palmito": "Palmito (pupunha)", "Pera": "Pera", "Pêssego": "Pêssego",
    "Pimenta-do-reino": "Pimenta-do-reino", "Pimentão": "Pimentão", "Rami (fibra)": "Rami", "Repolho": "Repolho",
    "Sisal ou agave (fibra)": "Sisal", "Soja (em grão)": "Soja", "Sorgo (em grão)": "Sorgo granífero",
    "Tangerina": "Tangerina", "Tomate": "Tomate", "Trigo (em grão)": "Trigo", "Triticale (em grão)": "Triticale",
    "Tungue (fruto seco)": "Tungue", "Urucum (semente)": "Urucum", "Uva": "Uva",
}


def amostrar_brasil(n_por_uf: int = 2, seed: int = 7) -> pl.DataFrame:
    """Amostra estratificada por UF (todas as 27), para cobrir os grandes tipos de solo do país."""
    mun = carregar_municipios()
    return mun.group_by("uf", maintain_order=True).map_groups(lambda g: g.sample(min(n_por_uf, g.height), seed=seed)).sort("uf")


def area_plantada(geocodigos: list[str], lote: int = 40) -> pl.DataFrame:
    """(geocodigo, nome_pt, area_ha) do último ano da PAM, somando produtos da mesma cultura."""
    linhas = []
    for i in range(0, len(geocodigos), lote):
        r = requests.get(URL_SIDRA.format(municipios=",".join(geocodigos[i:i + lote])), timeout=120)
        r.raise_for_status()
        for d in r.json()[1:]:
            nome = PAM_PARA_NOME.get(d["D4N"])
            if nome and d["V"] not in ("-", "...", "X", "..", ""):
                linhas.append({"geocodigo": d["D1C"], "nome_pt": nome, "area_ha": float(d["V"])})
    return pl.DataFrame(linhas).group_by("geocodigo", "nome_pt").agg(pl.col("area_ha").sum())


def resultados_t3(municipios: pl.DataFrame) -> tuple[pl.DataFrame, list[dict]]:
    """Scores da T3 (completa e "crua") para as culturas da PAM em cada município, + os perfis."""
    cat = culturas_exibiveis(carregar_culturas()).filter(
        pl.col("obrigatoria") & pl.col("nome_pt").is_in(list(set(PAM_PARA_NOME.values()))))
    partes, perfis = [], []
    for i, (geo, nome, uf, lat, lon) in enumerate(municipios.select("geocodigo", "nome", "uf", "lat", "lon").iter_rows(), 1):
        perfil = perfil_solo(lat, lon)
        perfis.append({"geocodigo": geo, "uf": uf, **{k: perfil.get(k) for k in
                       ("wrb", "ph", "textura", "drenagem", "profundidade", "fertilidade")}})
        for versao, kw in (("T3", {}), ("T3 crua", {"piso_corrigivel": 0.0, "latossolo_como_media": False})):
            partes.append(aptidao_solo(cat, perfil, **kw).join(cat.select("id_cultura", "nome_pt"), on="id_cultura")
                          .select("nome_pt", "score_t3", "fator_limitante_solo")
                          .with_columns(geocodigo=pl.lit(geo), uf=pl.lit(uf), versao=pl.lit(versao)))
        log.info("benchmark T3: %d/%d (%s-%s, %s)", i, municipios.height, nome, uf, perfil.get("wrb"))
    return pl.concat(partes), perfis


def _auc(pos: pl.Series, neg: pl.Series) -> float | None:
    if pos.is_empty() or neg.is_empty():
        return None
    p, n = pos.to_numpy()[:, None], neg.to_numpy()[None, :]
    return float(((p > n).sum() + 0.5 * (p == n).sum()) / (p.size * n.size))


def metricas(scores: pl.DataFrame, pam: pl.DataFrame, por: tuple[str, ...] = ()) -> pl.DataFrame:
    df = scores.join(pam, on=["geocodigo", "nome_pt"], how="left").with_columns(
        cultivada=pl.col("area_ha").fill_null(0) >= AREA_MIN_HA)
    linhas = []
    for chave, g in df.group_by(["versao", *por], maintain_order=True):
        cult, nao = g.filter("cultivada"), g.filter(~pl.col("cultivada"))
        # AUC dentro de cada município (compara culturas do mesmo solo), depois a média
        aucs = [a for _, gm in g.group_by("geocodigo")
                if (a := _auc(gm.filter("cultivada")["score_t3"], gm.filter(~pl.col("cultivada"))["score_t3"])) is not None]
        linhas.append(dict(zip(["versao", *por], chave)) | {
            "pares_cultivados": cult.height,
            "eliminacao_indevida": (cult["score_t3"] <= ELIMINADA).mean() if cult.height else None,
            "score_alto": (cult["score_t3"] >= 0.8).mean() if cult.height else None,
            "score_medio_cultivadas": cult["score_t3"].mean(),
            "score_medio_nao_cultivadas": nao["score_t3"].mean(),
            "auc_medio": sum(aucs) / len(aucs) if aucs else None,
        })
    return pl.DataFrame(linhas)
