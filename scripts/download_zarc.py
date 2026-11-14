"""Download da Tábua de Risco do ZARC (Zoneamento Agrícola de Risco Climático) por safra.

Fonte oficial: Portal de Dados Abertos do MAPA (licença CC-BY), os mesmos dados do painel
https://mapa-indicadores.agricultura.gov.br/publico/extensions/Zarc/Zarc.html
Dataset: https://dados.agricultura.gov.br/dataset/tabua-de-risco-zoneamento-agricola-de-risco-climatico

Os CSVs são localizados pela API CKAN do portal (pelo nome do recurso, não pelo ID). Cada
arquivo traz as colunas padrão da tábua e os 36 decêndios (dec1..dec36), com o risco
(0 = não indicado, 20/30/40 = % de risco) de plantio em cada decêndio do ano.

Uso:
    python scripts/download_zarc.py                       # safras 2022..2026
    python scripts/download_zarc.py --safras 2024 2025 --no-parquet
    python scripts/download_zarc.py --force               # rebaixa mesmo se já existir

"Safra 2022" = safra 2022/2023 (SafraIni, o mesmo critério do filtro "Safra" do painel).
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

CKAN_API = "https://dados.agricultura.gov.br/api/3/action/package_show"
DATASET_ID = "tabua-de-risco-zoneamento-agricola-de-risco-climatico"
USER_AGENT = "zarc-downloader/1.0 (python-requests)"

DECENDIOS = [f"dec{i}" for i in range(1, 37)]
COLUNAS_PADRAO = [
    "Nome_cultura", "SafraIni", "SafraFin", "Cod_Cultura", "Cod_Ciclo", "Cod_Solo", "geocodigo",
    "UF", "municipio", "Cod_Clima", "Nome_Clima", "Cod_Outros_Manejos", "Nome_Outros_Manejos",
    "Produtividade", "Cod_NM", "Cod_Munic", "Cod_Meso", "Cod_Micro", "Portaria",
]
COLUNAS = COLUNAS_PADRAO + DECENDIOS

# Códigos lidos como texto para preservar zeros à esquerda (ex.: Cod_Munic "047056").
DTYPES = {c: "string" for c in COLUNAS_PADRAO}
DTYPES.update({c: "Int8" for c in DECENDIOS})
DTYPES.update({"SafraIni": "Int16", "SafraFin": "Int16"})

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "data" / "raw" / "zarc"

log = logging.getLogger("zarc")


def list_resources(session: requests.Session) -> dict[int, dict]:
    """Mapeia SafraIni -> recurso CSV do CKAN (ex.: 2022 -> 'Tábua de risco - Safra 2022/2023')."""
    r = session.get(CKAN_API, params={"id": DATASET_ID}, timeout=60)
    r.raise_for_status()
    out = {}
    for res in r.json()["result"]["resources"]:
        name = res.get("name", "")
        if res.get("format", "").upper() != "CSV" or "Safra " not in name:
            continue
        safra = name.split("Safra ", 1)[1].strip()  # "2022/2023"
        ini, _, fin = safra.partition("/")
        if ini.isdigit() and fin.isdigit():
            out[int(ini)] = res
    return out


def download(session: requests.Session, url: str, dest: Path, retries: int = 3) -> None:
    tmp = dest.with_suffix(dest.suffix + ".part")
    for attempt in range(1, retries + 1):
        try:
            with session.get(url, stream=True, timeout=(30, 300)) as r:
                r.raise_for_status()
                total, t0 = 0, time.perf_counter()
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1 << 20):
                        f.write(chunk)
                        total += len(chunk)
                        if total % (50 << 20) < (1 << 20):
                            log.info("  %s: %.0f MB", dest.name, total / 2**20)
            tmp.replace(dest)
            log.info("  %s: %.1f MB em %.0fs", dest.name, total / 2**20, time.perf_counter() - t0)
            return
        except (requests.RequestException, OSError) as e:
            log.warning("  tentativa %d/%d falhou: %s", attempt, retries, e)
            if attempt == retries:
                tmp.unlink(missing_ok=True)
                raise
            time.sleep(5 * attempt)


def read_csv(path: Path) -> pd.DataFrame:
    header = pd.read_csv(path, sep=";", nrows=0, encoding="utf-8-sig").columns.tolist()
    missing = [c for c in COLUNAS if c not in header]
    if missing:
        raise ValueError(f"{path.name}: colunas ausentes {missing}")
    return pd.read_csv(path, sep=";", encoding="utf-8-sig", usecols=COLUNAS, dtype=DTYPES)[COLUNAS]


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s", datefmt="%H:%M:%S")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--safras", nargs="+", type=int, default=[2022, 2023, 2024, 2025, 2026],
                   help="Anos de início da safra (2022 = 2022/2023)")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    p.add_argument("--force", action="store_true", help="Rebaixa arquivos já existentes")
    p.add_argument("--no-parquet", action="store_true", help="Não gera o parquet consolidado")
    args = p.parse_args(argv)

    args.out.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT

    resources = list_resources(session)
    faltando = [s for s in args.safras if s not in resources]
    if faltando:
        log.error("Safras não publicadas no portal: %s (disponíveis: %s)", faltando, sorted(resources))
        return 1

    manifest = {"source": f"https://dados.agricultura.gov.br/dataset/{DATASET_ID}",
                "license": "Creative Commons Attribution", "files": []}
    frames = []
    for safra in args.safras:
        res = resources[safra]
        dest = args.out / f"tabua_risco_safra_{safra}_{safra + 1}.csv"
        log.info("Safra %d/%d", safra, safra + 1)
        if dest.exists() and not args.force:
            log.info("  já existe, pulando download (use --force para rebaixar)")
        else:
            download(session, res["url"], dest)

        df = read_csv(dest)
        log.info("  %d linhas | %d culturas | %d municípios", len(df), df["Nome_cultura"].nunique(), df["geocodigo"].nunique())
        manifest["files"].append({
            "safra": f"{safra}/{safra + 1}", "file": dest.name, "rows": len(df),
            "resource_url": res["url"], "resource_last_modified": res.get("last_modified"),
        })
        if not args.no_parquet:
            frames.append(df)

    if frames:
        pq = args.out / "tabua_risco_zarc.parquet"
        pd.concat(frames, ignore_index=True).to_parquet(pq, index=False)
        log.info("Parquet consolidado: %s", pq)

    manifest["downloaded_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("Concluído em %s", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
