"""Torre 1: aptidão climática (ECOCROP × NASA POWER).

Uso:
    from towers.t1_aptidao import avaliar_t1
    resultado = avaliar_t1(lat=-23.3, lon=-51.2, data_plantio=date(2026, 10, 15))
"""
from .torre import avaliar_t1

__all__ = ["avaliar_t1"]
