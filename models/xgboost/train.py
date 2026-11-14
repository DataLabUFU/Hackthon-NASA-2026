"""Pipeline de train do xgboost.

Uso: python -m models.xgboost.train --help
"""
from ..common.runners import train_main
from .model import SPEC

if __name__ == "__main__":
    train_main(SPEC)
