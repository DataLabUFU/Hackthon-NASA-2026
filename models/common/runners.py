"""Implementação genérica de treino, benchmark e inferência sobre um ``ModelSpec``.

Os scripts em ``models/<lib>/`` só injetam o spec do seu modelo. Toda a configuração vem
do YAML (ver ``config.py``).
"""
from __future__ import annotations

import logging
import platform
import time
from datetime import datetime
from importlib.metadata import version
from pathlib import Path

import numpy as np
import pandas as pd
import sklearn
from omegaconf import DictConfig
from sklearn.model_selection import KFold, StratifiedKFold, cross_validate
from sklearn.preprocessing import LabelEncoder

from . import artifacts, data
from .config import load_config, merge_params, setup_logging, to_yaml
from .metrics import NEGATED, cv_scoring, holdout_metrics
from .preprocessing import build_pipeline, infer_cat_features
from .spec import CLASSIFICATION, ModelSpec

log = logging.getLogger(__name__)

CONFIG_FILE = "config.yaml"


def _prepare(spec: ModelSpec, cfg: DictConfig):
    X, y, task = data.resolve_data(cfg)
    label_encoder = None
    if task == CLASSIFICATION:
        # XGBoost exige rótulos 0..n-1; codificamos para todos por consistência.
        label_encoder = LabelEncoder().fit(y)
        y = pd.Series(label_encoder.transform(y), index=y.index, name=y.name)
    cat_features = infer_cat_features(X)
    params = merge_params(spec, task, cfg)
    pipeline = build_pipeline(spec.build_estimator(task, params, cat_features), cat_features)
    log.info("%s | features categóricas: %s", spec.display_name, cat_features or "nenhuma")
    return X, y, task, label_encoder, cat_features, params, pipeline


def _versions(spec: ModelSpec) -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "scikit-learn": sklearn.__version__,
        spec.library: version(spec.library),
    }


def _save_config(cfg: DictConfig, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / CONFIG_FILE).write_text(to_yaml(cfg), encoding="utf-8")


def _data_label(cfg: DictConfig) -> str:
    return "demo" if cfg.data.demo else cfg.data.path


# --------------------------------------------------------------------------- treino
def train_main(spec: ModelSpec, argv=None) -> None:
    setup_logging()
    cfg = load_config(spec, "train", argv)
    test_size = cfg.train.test_size

    X, y, task, le, cat_features, params, pipeline = _prepare(spec, cfg)

    if test_size > 0:
        X_tr, X_te, y_tr, y_te = data.split(X, y, task, test_size, cfg.seed)
    else:
        X_tr, y_tr, X_te, y_te = X, y, None, None

    t0 = time.perf_counter()
    pipeline.fit(X_tr, y_tr)
    fit_seconds = time.perf_counter() - t0
    log.info("Treino concluído em %.2fs", fit_seconds)

    metrics = {}
    if X_te is not None:
        y_pred = np.ravel(pipeline.predict(X_te))
        y_proba = pipeline.predict_proba(X_te) if task == CLASSIFICATION else None
        metrics = holdout_metrics(task, y_te, y_pred, y_proba)
        log.info("Holdout: %s", {k: round(v, 4) for k, v in metrics.items()})

    run_id = artifacts.new_run_id()
    metadata = {
        "model": spec.name,
        "run_id": run_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "task": task,
        "target": y.name,
        "data": _data_label(cfg),
        "features": list(X.columns),
        "cat_features": cat_features,
        "classes": le.classes_.tolist() if le is not None else None,
        "params": params,
        "n_train": len(X_tr),
        "n_test": 0 if X_te is None else len(X_te),
        "fit_seconds": fit_seconds,
        "holdout_metrics": metrics,
        "versions": _versions(spec),
    }
    bundle = {"pipeline": pipeline, "label_encoder": le, "metadata": metadata}
    run_dir = artifacts.save_bundle(bundle, cfg.output_dir, spec.name, run_id)
    _save_config(cfg, run_dir)
    log.info("Modelo salvo em %s", run_dir)


# --------------------------------------------------------------------------- benchmark
def benchmark_main(spec: ModelSpec, argv=None) -> None:
    setup_logging()
    cfg = load_config(spec, "benchmark", argv)
    n_folds, n_jobs = cfg.benchmark.folds, cfg.benchmark.n_jobs

    X, y, task, le, _, params, pipeline = _prepare(spec, cfg)
    scoring = cv_scoring(task, len(le.classes_) if le is not None else None)
    splitter = StratifiedKFold if task == CLASSIFICATION else KFold
    cv = splitter(n_splits=n_folds, shuffle=True, random_state=cfg.seed)

    log.info("Rodando %d-fold CV...", n_folds)
    res = cross_validate(pipeline, X, y, cv=cv, scoring=scoring, n_jobs=n_jobs, error_score="raise")

    folds = pd.DataFrame({
        "fold": range(1, n_folds + 1),
        "fit_time": res["fit_time"],
        "score_time": res["score_time"],
    })
    for name in scoring:
        scores = res[f"test_{name}"]
        folds[name] = -scores if name in NEGATED else scores
    summary = {
        c: {"mean": float(folds[c].mean()), "std": float(folds[c].std(ddof=0))}
        for c in folds.columns if c != "fold"
    }

    run_id = artifacts.new_run_id()
    out_dir = artifacts.model_root(cfg.output_dir, spec.name) / "benchmarks" / run_id
    _save_config(cfg, out_dir)
    folds.to_csv(out_dir / "folds.csv", index=False)
    artifacts.write_json({
        "model": spec.name,
        "run_id": run_id,
        "task": task,
        "data": _data_label(cfg),
        "n_samples": len(X),
        "folds": n_folds,
        "seed": cfg.seed,
        "params": params,
        "summary": summary,
        "versions": _versions(spec),
    }, out_dir / "summary.json")

    log.info("Resultado %s (%d folds):", spec.display_name, n_folds)
    for c, s in summary.items():
        log.info("  %-12s %.4f +/- %.4f", c, s["mean"], s["std"])
    log.info("Benchmark salvo em %s", out_dir)


# --------------------------------------------------------------------------- inferência
def predict_frame(bundle: dict, X: pd.DataFrame, proba: bool = False) -> pd.DataFrame:
    meta = bundle["metadata"]
    missing = [c for c in meta["features"] if c not in X.columns]
    if missing:
        raise KeyError(f"Colunas ausentes no input: {missing}")
    X = X[meta["features"]]
    pipeline, le = bundle["pipeline"], bundle["label_encoder"]

    pred = np.ravel(pipeline.predict(X))
    if le is not None:
        pred = le.inverse_transform(pred.astype(int))
    out = pd.DataFrame({"prediction": pred}, index=X.index)
    if proba and meta["task"] == CLASSIFICATION:
        probs = pipeline.predict_proba(X)
        for i, cls in enumerate(meta["classes"]):
            out[f"proba_{cls}"] = probs[:, i]
    return out


def inference_main(spec: ModelSpec, argv=None) -> None:
    setup_logging()
    cfg = load_config(spec, "inference", argv)
    inf = cfg.inference

    path = artifacts.resolve_model_path(inf.model, cfg.output_dir, spec.name)
    bundle = artifacts.load_bundle(path)
    if bundle["metadata"]["model"] != spec.name:
        raise SystemExit(f"{path} é um modelo {bundle['metadata']['model']!r}, não {spec.name!r}")
    log.info("Modelo carregado: %s (run %s)", path, bundle["metadata"]["run_id"])

    X = data.read_table(inf.input)
    preds = predict_frame(bundle, X, proba=inf.proba)
    keep = list(inf.keep)
    out = pd.concat([X[keep], preds], axis=1) if keep else preds
    data.write_table(out, inf.output)
    log.info("%d predições salvas em %s", len(out), inf.output)
