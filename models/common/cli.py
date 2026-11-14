"""Argumentos de CLI comuns aos três pipelines."""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

from .spec import TASKS


def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s", datefmt="%H:%M:%S")


def add_data_args(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("dados")
    g.add_argument("--data", help="Caminho do dataset (.csv ou .parquet)")
    g.add_argument("--target", help="Nome da coluna alvo")
    g.add_argument("--drop", nargs="*", default=[], help="Colunas a descartar (ids, vazamentos...)")
    g.add_argument("--task", choices=("auto", *TASKS), default="auto")
    g.add_argument("--demo", action="store_true", help="Usa um dataset sintético (smoke test)")
    g.add_argument("--seed", type=int, default=42)


def add_model_args(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("modelo")
    g.add_argument("--params", help="Override de hiperparâmetros: JSON inline ou caminho para .json")
    g.add_argument("--output-dir", default="artifacts", help="Raiz dos artefatos")


def parse_params(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    path = Path(raw)
    text = path.read_text(encoding="utf-8") if path.suffix == ".json" and path.exists() else raw
    params = json.loads(text)
    if not isinstance(params, dict):
        raise SystemExit("--params precisa ser um objeto JSON")
    return params
