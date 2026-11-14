"""Implementação genérica de treino, benchmark e inferência sobre um ``ModelSpec``.

Os scripts em ``models/<lib>/`` só injetam o spec do seu modelo.
"""
from __future__ import annotations

import argparse
import logging
import platform
import time
from datetime import datetime
from importlib.metadata import version

import numpy as np
import pandas as pd
import sklearn
from sklearn.model_selection import KFold, StratifiedKFold, cross_validate
from sklearn.preprocessing import LabelEncoder

from . import artifacts, cli, data
from .metrics import NEGATED, cv_scoring, holdout_metrics
from .preprocessing import build_pipeline, infer_cat_features
from .spec import CLASSIFICATION, ModelSpec

log = logging.getLogger(__name__)


def _prepare(spec: ModelSpec, args):
    X, y, task = data.resolve_data(args)
    label_encoder = None
    if task == CLASSIFICATION:
        # XGBoost exige rótulos 0..n-1; codificamos para todos por consistência.
        label_encoder = LabelEncoder().fit(y)
        y = pd.Series(label_encoder.transform(y), index=y.index, name=y.name)
    cat_features = infer_cat_features(X)
    params = {**spec.default_params(task, args.seed), **cli.parse_params(args.params)}
    pipeline = build_pipeline(spec.build_estimator(task, params, cat_features), cat_features)
    log.info("%s | features categóricas: %s", spec.display_name, cat_features or "nenhuma")
    return X, y, task, label_encoder, cat_features, params, pipeline


def _versions(spec: ModelSpec) -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "scikit-learn": sklearn.__version__,
        spec.library: version(spec.library),
    }


# --------------------------------------------------------------------------- treino
def train_main(spec: ModelSpec, argv=None) -> None:
    cli.setup_logging()
    p = argparse.ArgumentParser(description=f"Treino {spec.display_name}")
    cli.add_data_args(p)
    cli.add_model_args(p)
    p.add_argument("--test-size", type=float, default=0.2, help="Fração de holdout (0 = treina com tudo)")
    args = p.parse_args(argv)

    X, y, task, le, cat_features, params, pipeline = _prepare(spec, args)

    if args.test_size > 0:
        X_tr, X_te, y_tr, y_te = data.split(X, y, task, args.test_size, args.seed)
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
        "data": "demo" if args.demo else args.data,
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
    run_dir = artifacts.save_bundle(bundle, args.output_dir, spec.name, run_id)
    log.info("Modelo salvo em %s", run_dir)


# --------------------------------------------------------------------------- benchmark
def benchmark_main(spec: ModelSpec, argv=None) -> None:
    cli.setup_logging()
    p = argparse.ArgumentParser(description=f"Benchmark (validação cruzada) {spec.display_name}")
    cli.add_data_args(p)
    cli.add_model_args(p)
    p.add_argument("--folds", type=int, default=5)
    p.add_argument("--n-jobs", type=int, default=1, help="Folds em paralelo (os boosters já são multi-thread)")
    args = p.parse_args(argv)

    X, y, task, le, _, params, pipeline = _prepare(spec, args)
    scoring = cv_scoring(task, len(le.classes_) if le is not None else None)
    splitter = StratifiedKFold if task == CLASSIFICATION else KFold
    cv = splitter(n_splits=args.folds, shuffle=True, random_state=args.seed)

    log.info("Rodando %d-fold CV...", args.folds)
    res = cross_validate(pipeline, X, y, cv=cv, scoring=scoring, n_jobs=args.n_jobs, error_score="raise")

    folds = pd.DataFrame({
        "fold": range(1, args.folds + 1),
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
    out_dir = artifacts.model_root(args.output_dir, spec.name) / "benchmarks" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    folds.to_csv(out_dir / "folds.csv", index=False)
    artifacts.write_json({
        "model": spec.name,
        "run_id": run_id,
        "task": task,
        "data": "demo" if args.demo else args.data,
        "n_samples": len(X),
        "folds": args.folds,
        "seed": args.seed,
        "params": params,
        "summary": summary,
        "versions": _versions(spec),
    }, out_dir / "summary.json")

    log.info("Resultado %s (%d folds):", spec.display_name, args.folds)
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
    cli.setup_logging()
    p = argparse.ArgumentParser(description=f"Inferência {spec.display_name}")
    p.add_argument("--input", required=True, help="Dataset a ser predito (.csv ou .parquet)")
    p.add_argument("--output", required=True, help="Arquivo de saída (.csv ou .parquet)")
    p.add_argument("--model", help="model.joblib ou pasta do run (padrão: último treino)")
    p.add_argument("--output-dir", default="artifacts", help="Raiz dos artefatos")
    p.add_argument("--proba", action="store_true", help="Inclui probabilidades por classe")
    p.add_argument("--keep", nargs="*", default=[], help="Colunas do input copiadas para a saída (ex.: id)")
    args = p.parse_args(argv)

    path = artifacts.resolve_model_path(args.model, args.output_dir, spec.name)
    bundle = artifacts.load_bundle(path)
    if bundle["metadata"]["model"] != spec.name:
        raise SystemExit(f"{path} é um modelo {bundle['metadata']['model']!r}, não {spec.name!r}")
    log.info("Modelo carregado: %s (run %s)", path, bundle["metadata"]["run_id"])

    X = data.read_table(args.input)
    preds = predict_frame(bundle, X, proba=args.proba)
    out = pd.concat([X[args.keep], preds], axis=1) if args.keep else preds
    data.write_table(out, args.output)
    log.info("%d predições salvas em %s", len(out), args.output)
