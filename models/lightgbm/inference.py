"""Pipeline de inference do lightgbm.

Uso: python -m models.lightgbm.inference --help
"""
from ..common.runners import inference_main
from .model import SPEC

if __name__ == "__main__":
    inference_main(SPEC)
