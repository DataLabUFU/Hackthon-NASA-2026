"""LightGBM via API scikit-learn (``LGBMClassifier`` / ``LGBMRegressor``).

Docs: https://lightgbm.readthedocs.io/en/latest/Parameters.html
"""
from __future__ import annotations

from typing import Any

from lightgbm import LGBMClassifier, LGBMRegressor

from ..common.spec import CLASSIFICATION, ModelSpec


def default_params(task: str, seed: int) -> dict[str, Any]:
    return {
        "n_estimators": 500,
        "learning_rate": 0.05,
        "num_leaves": 31,
        "min_child_samples": 20,
        "subsample": 0.8,
        "subsample_freq": 1,
        "colsample_bytree": 0.8,
        "reg_lambda": 0.0,
        "random_state": seed,
        "n_jobs": -1,
        "verbose": -1,
    }


def build_estimator(task: str, params: dict[str, Any], cat_features: list[str]):
    # Colunas com dtype "category" são detectadas automaticamente (categorical_feature="auto").
    cls = LGBMClassifier if task == CLASSIFICATION else LGBMRegressor
    return cls(**params)


SPEC = ModelSpec(
    name="lightgbm",
    display_name="LightGBM",
    library="lightgbm",
    default_params=default_params,
    build_estimator=build_estimator,
)
