"""Carregamento de dados e split."""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.datasets import make_classification, make_regression
from sklearn.model_selection import train_test_split

from .spec import CLASSIFICATION, REGRESSION

log = logging.getLogger(__name__)


def read_table(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    raise ValueError(f"Formato não suportado: {suffix} (use .csv ou .parquet)")


def write_table(df: pd.DataFrame, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() in {".parquet", ".pq"}:
        df.to_parquet(path, index=False)
    else:
        df.to_csv(path, index=False)


def load_dataset(path: str, target: str, drop: list[str] | None = None) -> tuple[pd.DataFrame, pd.Series]:
    df = read_table(path)
    if target not in df.columns:
        raise KeyError(f"Coluna alvo {target!r} não encontrada em {path}")
    drop = [c for c in (drop or []) if c in df.columns]
    df = df.dropna(subset=[target])
    y = df[target]
    X = df.drop(columns=[target, *drop])
    return X, y


def make_demo_dataset(task: str, n_samples: int = 3000, seed: int = 42) -> tuple[pd.DataFrame, pd.Series]:
    """Dataset sintético com uma feature categórica e valores ausentes, para smoke tests."""
    rng = np.random.default_rng(seed)
    if task == REGRESSION:
        X, y = make_regression(n_samples=n_samples, n_features=10, n_informative=6, noise=10.0, random_state=seed)
    else:
        X, y = make_classification(n_samples=n_samples, n_features=10, n_informative=6, random_state=seed)
    X = pd.DataFrame(X, columns=[f"f{i}" for i in range(X.shape[1])])
    X["category"] = rng.choice(["a", "b", "c", "d"], size=n_samples).astype(object)
    X.loc[rng.random(n_samples) < 0.05, "f0"] = np.nan
    X.loc[rng.random(n_samples) < 0.05, "category"] = None
    return X, pd.Series(y, name="target")


def infer_task(y: pd.Series, max_classes: int = 20) -> str:
    if not pd.api.types.is_numeric_dtype(y) or pd.api.types.is_bool_dtype(y):
        return CLASSIFICATION
    if pd.api.types.is_integer_dtype(y) and y.nunique() <= max_classes:
        return CLASSIFICATION
    return REGRESSION


def resolve_data(args) -> tuple[pd.DataFrame, pd.Series, str]:
    """Resolve ``--data/--target`` ou ``--demo`` e a tarefa a partir dos argumentos de CLI."""
    if args.demo:
        task = CLASSIFICATION if args.task == "auto" else args.task
        X, y = make_demo_dataset(task, seed=args.seed)
    else:
        if not args.data or not args.target:
            raise SystemExit("Informe --data e --target (ou use --demo).")
        X, y = load_dataset(args.data, args.target, args.drop)
        task = infer_task(y) if args.task == "auto" else args.task
    log.info("Dataset: %d linhas x %d features | tarefa=%s", len(X), X.shape[1], task)
    return X, y, task


def split(X, y, task: str, test_size: float, seed: int):
    stratify = y if task == CLASSIFICATION else None
    return train_test_split(X, y, test_size=test_size, random_state=seed, stratify=stratify)
