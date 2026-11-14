"""Métricas de holdout e scorers de validação cruzada por tipo de tarefa."""
from __future__ import annotations

import numpy as np
from sklearn import metrics as skm

from .spec import CLASSIFICATION

# Scorers "neg_*" do sklearn são negativos; o sinal é invertido ao reportar.
NEGATED = {"log_loss", "rmse", "mae"}


def cv_scoring(task: str, n_classes: int | None = None) -> dict[str, str]:
    if task == CLASSIFICATION:
        auc = "roc_auc" if n_classes == 2 else "roc_auc_ovr"
        return {"accuracy": "accuracy", "f1_macro": "f1_macro", "roc_auc": auc, "log_loss": "neg_log_loss"}
    return {"rmse": "neg_root_mean_squared_error", "mae": "neg_mean_absolute_error", "r2": "r2"}


def holdout_metrics(task: str, y_true, y_pred, y_proba=None) -> dict[str, float]:
    if task == CLASSIFICATION:
        out = {
            "accuracy": skm.accuracy_score(y_true, y_pred),
            "f1_macro": skm.f1_score(y_true, y_pred, average="macro"),
        }
        if y_proba is not None:
            labels = np.arange(y_proba.shape[1])
            out["log_loss"] = skm.log_loss(y_true, y_proba, labels=labels)
            if y_proba.shape[1] == 2:
                out["roc_auc"] = skm.roc_auc_score(y_true, y_proba[:, 1])
            else:
                out["roc_auc"] = skm.roc_auc_score(y_true, y_proba, multi_class="ovr", labels=labels)
    else:
        out = {
            "rmse": skm.root_mean_squared_error(y_true, y_pred),
            "mae": skm.mean_absolute_error(y_true, y_pred),
            "r2": skm.r2_score(y_true, y_pred),
        }
    return {k: float(v) for k, v in out.items()}
