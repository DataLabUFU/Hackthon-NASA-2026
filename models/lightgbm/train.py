"""Pipeline de train do lightgbm.

Uso: python -m models.lightgbm.train --help
"""
from ..common.runners import train_main
from .model import SPEC

if __name__ == "__main__":
    train_main(SPEC)
