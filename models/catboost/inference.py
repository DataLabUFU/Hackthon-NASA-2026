"""Pipeline de inference do catboost.

Uso: python -m models.catboost.inference --help
"""
from ..common.runners import inference_main
from .model import SPEC

if __name__ == "__main__":
    inference_main(SPEC)
