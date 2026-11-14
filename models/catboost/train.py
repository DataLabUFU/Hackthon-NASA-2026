"""Pipeline de train do catboost.

Uso: python -m models.catboost.train --help
"""
from ..common.runners import train_main
from .model import SPEC

if __name__ == "__main__":
    train_main(SPEC)
