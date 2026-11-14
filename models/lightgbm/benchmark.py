"""Pipeline de benchmark do lightgbm.

Uso: python -m models.lightgbm.benchmark --help
"""
from ..common.runners import benchmark_main
from .model import SPEC

if __name__ == "__main__":
    benchmark_main(SPEC)
