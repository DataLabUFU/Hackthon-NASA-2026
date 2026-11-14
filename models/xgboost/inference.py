"""Pipeline de inference do xgboost.

Uso: python -m models.xgboost.inference --help
"""
from ..common.runners import inference_main
from .model import SPEC

if __name__ == "__main__":
    inference_main(SPEC)
