"""Persistência de modelos treinados em ``artifacts/<modelo>/runs/<run_id>/``."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import joblib

MODEL_FILE = "model.joblib"
METADATA_FILE = "metadata.json"
LATEST_FILE = "LATEST"


def new_run_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S-%f")


def model_root(output_dir: str | Path, model_name: str) -> Path:
    return Path(output_dir) / model_name


def write_json(data: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def save_bundle(bundle: dict[str, Any], output_dir: str | Path, model_name: str, run_id: str) -> Path:
    root = model_root(output_dir, model_name)
    run_dir = root / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, run_dir / MODEL_FILE)
    write_json(bundle["metadata"], run_dir / METADATA_FILE)
    (root / LATEST_FILE).write_text(run_id, encoding="utf-8")
    return run_dir


def resolve_model_path(model: str | None, output_dir: str | Path, model_name: str) -> Path:
    """Aceita um ``model.joblib``, uma pasta de run, ou ``None`` (último run treinado)."""
    if model is None:
        root = model_root(output_dir, model_name)
        latest = root / LATEST_FILE
        if not latest.exists():
            raise FileNotFoundError(f"Nenhum modelo treinado em {root}. Rode o train primeiro.")
        return root / "runs" / latest.read_text(encoding="utf-8").strip() / MODEL_FILE
    path = Path(model)
    return path / MODEL_FILE if path.is_dir() else path


def load_bundle(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(path)
    return joblib.load(path)
