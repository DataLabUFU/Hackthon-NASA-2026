"""XGBoost via API scikit-learn (``XGBClassifier`` / ``XGBRegressor``).

Docs: https://xgboost.readthedocs.io/en/stable/parameter.html
"""
from __future__ import annotations

from typing import Any

from xgboost import XGBClassifier, XGBRegressor

from ..common.spec import CLASSIFICATION, ModelSpec


def default_params(task: str, seed: int) -> dict[str, Any]:
    return {
        "n_estimators": 500,
        "learning_rate": 0.05,
        "max_depth": 6,
        "min_child_weight": 1,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "reg_lambda": 1.0,
        "tree_method": "hist",
        "enable_categorical": True,  # usa o dtype "category" do pandas nativamente
        "random_state": seed,
        "n_jobs": -1,
    }


def build_estimator(task: str, params: dict[str, Any], cat_features: list[str]):
    cls = XGBClassifier if task == CLASSIFICATION else XGBRegressor
    return cls(**params)


SPEC = ModelSpec(
    name="xgboost",
    display_name="XGBoost",
    library="xgboost",
    default_params=default_params,
    build_estimator=build_estimator,
)
