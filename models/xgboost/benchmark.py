"""Pipeline de benchmark do xgboost.

Uso: python -m models.xgboost.benchmark --help
"""
from ..common.runners import benchmark_main
from .model import SPEC

if __name__ == "__main__":
    benchmark_main(SPEC)
