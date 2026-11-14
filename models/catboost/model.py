"""CatBoost via API scikit-learn (``CatBoostClassifier`` / ``CatBoostRegressor``).

Docs: https://catboost.ai/docs/en/references/training-parameters/
Obs.: o número de árvores se chama ``iterations`` (não ``n_estimators``).
"""
from __future__ import annotations

from typing import Any

import pandas as pd
from catboost import CatBoostClassifier, CatBoostRegressor

from ..common.spec import CLASSIFICATION, ModelSpec


def _categorical_columns(X) -> list[str] | None:
    if not isinstance(X, pd.DataFrame):
        return None
    cols = [c for c in X.columns if isinstance(X[c].dtype, pd.CategoricalDtype)]
    return cols or None


class _AutoCatFeaturesMixin:
    """Passa ``cat_features`` no ``fit`` a partir do dtype ``category``.

    Passar no construtor quebra o ``sklearn.clone`` (usado no ``cross_validate``), porque o
    CatBoost modifica esse parâmetro internamente.
    """

    def fit(self, X, y=None, **kwargs):
        if kwargs.get("cat_features") is None:
            kwargs["cat_features"] = _categorical_columns(X)
        return super().fit(X, y, **kwargs)


class AutoCatBoostClassifier(_AutoCatFeaturesMixin, CatBoostClassifier):
    pass


class AutoCatBoostRegressor(_AutoCatFeaturesMixin, CatBoostRegressor):
    pass


def default_params(task: str, seed: int) -> dict[str, Any]:
    return {
        "iterations": 500,
        "learning_rate": 0.05,
        "depth": 6,
        "l2_leaf_reg": 3.0,
        "random_seed": seed,
        "thread_count": -1,
        "verbose": 0,
        "allow_writing_files": False,  # evita criar a pasta catboost_info/
    }


def build_estimator(task: str, params: dict[str, Any], cat_features: list[str]):
    cls = AutoCatBoostClassifier if task == CLASSIFICATION else AutoCatBoostRegressor
    return cls(**params)


SPEC = ModelSpec(
    name="catboost",
    display_name="CatBoost",
    library="catboost",
    default_params=default_params,
    build_estimator=build_estimator,
)
