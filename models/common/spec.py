"""Contrato que cada modelo implementa para plugar nos pipelines de treino/benchmark/inferência."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from sklearn.base import BaseEstimator

CLASSIFICATION = "classification"
REGRESSION = "regression"
TASKS = (CLASSIFICATION, REGRESSION)


@dataclass(frozen=True)
class ModelSpec:
    name: str
    """Identificador usado nas pastas de artefatos (ex.: ``lightgbm``)."""
    display_name: str
    library: str
    """Nome do pacote Python, usado para registrar a versão no metadata."""
    default_params: Callable[[str, int], dict[str, Any]]
    """``(task, seed) -> params`` padrão do estimador."""
    build_estimator: Callable[[str, dict[str, Any], list[str]], BaseEstimator]
    """``(task, params, cat_features) -> estimador sklearn``."""
