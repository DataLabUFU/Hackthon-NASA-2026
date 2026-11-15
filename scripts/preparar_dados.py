"""Baixa e prepara os dados do recomendador (rodar uma vez, a partir da raiz do repositório).

    python scripts/preparar_dados.py            # tudo
    python scripts/preparar_dados.py --sem-gbif # pula os nomes populares do GBIF (~7 min na 1ª vez)

Gera, em data/ (ignorada pelo git):
- raw/ecocrop/EcoCrop_DB.csv            requisitos das culturas (FAO ECOCROP, cópia OpenCLIM)
- raw/ibge/municipios.csv               municípios com coordenadas
- raw/embrapa/Preditos_triangulo_AD_m2.csv   água disponível pela PTF do ZARC (Embrapa)
- raw/zarc/tabua_risco_zarc.parquet     Tábua de Risco do ZARC (MAPA), 3 safras mais recentes
- cache/gbif/nomes.parquet              nomes populares brasileiros (GBIF / Flora e Funga do Brasil)
O clima (NASA POWER) e o solo (SoilGrids) são baixados sob demanda, por local, na primeira consulta.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from towers.data import ecocrop, municipios, ptf_zarc, zarc  # noqa: E402
from towers.data.culturas import carregar_culturas  # noqa: E402


def etapa(nome, f):
    t = time.perf_counter()
    logging.info("→ %s", nome)
    r = f()
    logging.info("  ok (%.0f s)", time.perf_counter() - t)
    return r


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sem-gbif", action="store_true", help="não consulta os nomes populares no GBIF")
    p.add_argument("--forcar-zarc", action="store_true", help="baixa o ZARC mesmo se já existir")
    args = p.parse_args(argv)

    etapa("ECOCROP", ecocrop.baixar_ecocrop)
    etapa("Municípios (IBGE)", lambda: municipios.carregar_municipios(baixar=True))
    etapa("PTF de água disponível (Embrapa/ZARC)", ptf_zarc.tabela_ptf)
    if args.forcar_zarc or not zarc.CAMINHO_PADRAO.exists():
        etapa("Tábua de Risco do ZARC (MAPA) — alguns minutos", zarc.baixar_zarc)
    cat = etapa("Catálogo de culturas" + ("" if args.sem_gbif else " + nomes do GBIF (~7 min na 1ª vez)"),
                lambda: carregar_culturas(usar_gbif=not args.sem_gbif))
    logging.info("Pronto: %d culturas exibíveis.", cat["exibivel"].sum())
    return 0


if __name__ == "__main__":
    sys.exit(main())
