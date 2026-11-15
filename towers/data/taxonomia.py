"""Nomes científicos aceitos e nomes populares brasileiros via GBIF, com cache local.

API (gratuita, sem chave): https://www.gbif.org/developer/species
- ``/v1/species/match``: resolve o nome do ECOCROP (inclusive sinônimos antigos) no backbone do GBIF;
- ``/v1/species/{key}/vernacularNames``: nomes populares por idioma e fonte.

Regras:

- Só vale casamento ``EXACT``. Os demais (ex.: ``Lycopersicon esculentum`` → só o gênero *Solanum*)
  ficam sem nome; as culturas importantes têm nome curado em ``culturas_obrigatorias.csv``.
- Só valem nomes em português da fonte **Flora e Funga do Brasil – Lista Oficial**, para não
  mostrar nomes de Portugal (ex.: "pêra-abacate", "fidalguinhos").
- Nome principal = o nome brasileiro que aparece em mais fontes do GBIF (empate → o mais curto).
- Variedades e subespécies usam os nomes do próprio táxon, nunca os da espécie (senão brócolis
  herdaria "couve, repolho").

Só nomes científicos são enviados ao GBIF.
"""
from __future__ import annotations

import logging
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Iterable

import polars as pl
import requests

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
CACHE_PADRAO = ROOT / "data" / "cache" / "gbif" / "nomes.parquet"

GBIF = "https://api.gbif.org/v1/species"
USER_AGENT = "towers-taxonomy/0.1 (python-requests)"
FONTE_BRASIL = "Flora e Funga do Brasil"
IDIOMAS_PT = ("por", "pt")
RANKS_INFRAESPECIFICOS = ("SUBSPECIES", "VARIETY", "FORM")

SCHEMA_CACHE = {
    "especie": pl.String, "gbif_key": pl.Int64, "gbif_rank": pl.String, "gbif_match": pl.String,
    "nome_aceito": pl.String, "nomes_pt": pl.List(pl.String), "fontes_pt": pl.List(pl.String),
}


def consultar_gbif(especie: str, sessao: requests.Session | None = None) -> dict:
    """Casamento + nomes em português de uma espécie (2 chamadas)."""
    get = (sessao or requests).get
    hdr = {"User-Agent": USER_AGENT}
    m = get(f"{GBIF}/match", params={"name": especie, "kingdom": "Plantae"}, headers=hdr, timeout=30).json()
    rank, match = m.get("rank"), m.get("matchType")
    # variedade/subespécie: nomes do próprio táxon; espécie: nomes do táxon aceito
    key = m.get("usageKey") if rank in RANKS_INFRAESPECIFICOS else (m.get("acceptedUsageKey") or m.get("usageKey"))
    nomes, fontes = [], []
    if key and match == "EXACT":
        v = get(f"{GBIF}/{key}/vernacularNames", params={"limit": 1000}, headers=hdr, timeout=30).json()
        for r in v.get("results", []):
            if r.get("language") in IDIOMAS_PT and r.get("vernacularName"):
                nomes.append(r["vernacularName"].strip())
                fontes.append(r.get("source") or "")
    return {
        "especie": especie, "gbif_key": key, "gbif_rank": rank, "gbif_match": match,
        "nome_aceito": m.get("species") if rank not in RANKS_INFRAESPECIFICOS else m.get("canonicalName"),
        "nomes_pt": nomes, "fontes_pt": fontes,
    }


def _chave(nome: str) -> str:
    return nome.casefold()


def capitalizar(nome: str) -> str:
    return nome[:1].upper() + nome[1:]


def escolher_nomes(nomes: list[str], fontes: list[str]) -> tuple[str | None, list[str]]:
    """(nome principal, alternativos) entre os nomes de procedência brasileira."""
    brasileiros: dict[str, str] = {}
    for n, f in zip(nomes, fontes):
        if FONTE_BRASIL in f:
            brasileiros.setdefault(_chave(n), n)
    if not brasileiros:
        return None, []
    frequencia: dict[str, int] = {}
    for n in nomes:
        if _chave(n) in brasileiros:
            frequencia[_chave(n)] = frequencia.get(_chave(n), 0) + 1
    ordem = sorted(brasileiros, key=lambda k: (-frequencia[k], len(k), k))
    principal = capitalizar(brasileiros[ordem[0]])
    return principal, [capitalizar(brasileiros[k]) for k in ordem[1:]]


def nomes_pt_brasil(especies: Iterable[str], cache: Path | str = CACHE_PADRAO, workers: int = 8,
                    consultar: Callable[[str], dict] = consultar_gbif) -> pl.DataFrame:
    """Uma linha por espécie: nome aceito no GBIF, nome popular brasileiro e alternativos.

    Consulta o GBIF só para as espécies que ainda não estão no cache.
    """
    especies = list(dict.fromkeys(especies))
    cache = Path(cache)
    antigo = pl.read_parquet(cache) if cache.exists() else pl.DataFrame(schema=SCHEMA_CACHE)
    faltam = [e for e in especies if e not in set(antigo["especie"].to_list())]

    if faltam:
        log.info("GBIF: consultando %d espécies", len(faltam))
        with ThreadPoolExecutor(max_workers=workers) as ex:
            novos = pl.DataFrame(list(ex.map(_seguro(consultar), faltam)), schema=SCHEMA_CACHE)
        validos = novos.filter(pl.col("gbif_match") != "ERRO")
        if validos.height:
            cache.parent.mkdir(parents=True, exist_ok=True)
            pl.concat([antigo, validos]).write_parquet(cache)
        antigo = pl.concat([antigo, novos])

    df = antigo.filter(pl.col("especie").is_in(especies))
    escolhas = [escolher_nomes(n or [], f or []) for n, f in zip(df["nomes_pt"].to_list(), df["fontes_pt"].to_list())]
    return df.select("especie", "gbif_key", "gbif_match", "nome_aceito").with_columns(
        nome_pt=pl.Series([e[0] for e in escolhas], dtype=pl.String),
        nomes_pt_alternativos=pl.Series([e[1] for e in escolhas], dtype=pl.List(pl.String)),
    )


def _seguro(consultar: Callable[[str], dict]) -> Callable[[str], dict]:
    """Erro de rede numa espécie não derruba as demais (fica sem nome e não vai para o cache)."""
    def f(especie: str) -> dict:
        try:
            return consultar(especie)
        except (requests.RequestException, ValueError) as e:
            log.warning("GBIF: falha em %s: %s", especie, e)
            return {"especie": especie, "gbif_key": None, "gbif_rank": None, "gbif_match": "ERRO",
                    "nome_aceito": None, "nomes_pt": [], "fontes_pt": []}
    return f


def slug(texto: str) -> str:
    """Identificador estável a partir de um nome ("Café arábica" → "cafe-arabica")."""
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()
    return "-".join("".join(c if c.isalnum() else " " for c in t).split())
