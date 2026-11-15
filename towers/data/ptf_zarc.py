"""Água disponível (AD) do solo pela função de pedotransferência do ZARC (Embrapa).

Teixeira, W. G.; Victoria, D. de C.; Barros, A. H. C. (2021). Predição da água disponível no solo
em função da granulometria para uso nas análises de risco no Zoneamento Agrícola de Risco
Climático. Boletim de Pesquisa e Desenvolvimento 272, Embrapa Solos.

A Embrapa publica a função como tabela com as 5.151 combinações inteiras de areia/silte/argila
(soma 100%), com a AD prevista (mm/cm), a classe AD do ZARC (IN MAPA nº 1/2022) e o intervalo
de confiança de 95%: https://github.com/dvictori/ptf_zarc (arquivo Preditos_triangulo_AD_m2.csv).
A função foi ajustada principalmente com Latossolos, Argissolos e Neossolos Quartzarênicos;
não se aplica bem a Vertissolos, Chernossolos e Organossolos.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import polars as pl
import requests

ROOT = Path(__file__).resolve().parents[2]
CAMINHO_PADRAO = ROOT / "data" / "raw" / "embrapa" / "Preditos_triangulo_AD_m2.csv"
URL = "https://raw.githubusercontent.com/dvictori/ptf_zarc/master/resultados/Preditos_triangulo_AD_m2.csv"


@lru_cache(maxsize=1)
def tabela_ptf(caminho: str = str(CAMINHO_PADRAO)) -> dict[tuple[int, int, int], tuple[float, str, float, float]]:
    caminho = Path(caminho)
    if not caminho.exists():
        caminho.parent.mkdir(parents=True, exist_ok=True)
        r = requests.get(URL, timeout=60)
        r.raise_for_status()
        caminho.write_bytes(r.content)
    df = pl.read_csv(caminho, separator=";", decimal_comma=True)
    return {
        (at, sil, arg): (ad, classe, li, ls)
        for at, sil, arg, ad, classe, li, ls in df.select(
            "AT", "SIL", "ARG", "ADm2_mm_cm", "ClasseAD_m2", "LI_ICm2", "LS_ICm2").iter_rows()
    }


def _inteiros_somando_100(areia: float, silte: float, argila: float) -> tuple[int, int, int]:
    """Normaliza para 100% e arredonda pelo maior resto (a soma continua exatamente 100)."""
    total = areia + silte + argila
    frac = [100 * v / total for v in (areia, silte, argila)]
    base = [int(f) for f in frac]
    for i in sorted(range(3), key=lambda k: frac[k] - base[k], reverse=True)[: 100 - sum(base)]:
        base[i] += 1
    return tuple(base)


def agua_disponivel(areia: float, silte: float, argila: float) -> dict:
    """AD (mm/cm), classe AD do ZARC e intervalo de confiança, a partir da textura em %."""
    at, sil, arg = _inteiros_somando_100(areia, silte, argila)
    ad, classe, li, ls = tabela_ptf()[(at, sil, arg)]
    return {"ad_mm_cm": ad, "classe_ad": classe, "ad_li": li, "ad_ls": ls, "textura_usada": (at, sil, arg)}
