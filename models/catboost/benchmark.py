"""Pipeline de benchmark do catboost.

Uso: python -m models.catboost.benchmark --help
"""
from ..common.runners import benchmark_main
from .model import SPEC

if __name__ == "__main__":
    benchmark_main(SPEC)
