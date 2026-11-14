"""Pré-processamento compatível com scikit-learn compartilhado pelos três boosters."""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.pipeline import Pipeline
from sklearn.utils.validation import check_is_fitted

MISSING = "__missing__"


def infer_cat_features(X: pd.DataFrame) -> list[str]:
    """Colunas não numéricas (object/string/category) são tratadas como categóricas."""
    return [
        c for c in X.columns
        if not pd.api.types.is_numeric_dtype(X[c]) and not pd.api.types.is_bool_dtype(X[c])
    ]


class CategoricalCaster(TransformerMixin, BaseEstimator):
    """Converte colunas categóricas para ``pd.CategoricalDtype`` com categorias fixadas no fit.

    Fixar as categorias garante que os códigos internos sejam os mesmos no treino e na
    inferência (LightGBM e XGBoost usam esses códigos). Nulos e categorias não vistas
    viram ``__missing__``, porque o CatBoost não aceita NaN em features categóricas.
    """

    def __init__(self, columns: list[str] | None = None):
        self.columns = columns

    def fit(self, X: pd.DataFrame, y=None):
        if not isinstance(X, pd.DataFrame):
            raise TypeError("CategoricalCaster espera um pandas.DataFrame")
        cols = list(self.columns) if self.columns is not None else infer_cat_features(X)
        self.feature_names_in_ = np.asarray(X.columns, dtype=object)
        self.n_features_in_ = X.shape[1]
        self.dtypes_ = {}
        for c in cols:
            values = self._as_str(X[c])
            cats = sorted(set(values.unique()) | {MISSING})
            self.dtypes_[c] = pd.CategoricalDtype(categories=cats)
        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        check_is_fitted(self, "dtypes_")
        X = X.copy()
        for c, dtype in self.dtypes_.items():
            values = self._as_str(X[c])
            values = values.where(values.isin(dtype.categories), MISSING)
            X[c] = values.astype(dtype)
        return X

    def get_feature_names_out(self, input_features=None):
        return self.feature_names_in_

    @staticmethod
    def _as_str(s: pd.Series) -> pd.Series:
        return s.astype("string").fillna(MISSING).astype(object)


def build_pipeline(estimator: BaseEstimator, cat_features: list[str]) -> Pipeline:
    return Pipeline([
        ("prep", CategoricalCaster(columns=cat_features)),
        ("model", estimator),
    ])
