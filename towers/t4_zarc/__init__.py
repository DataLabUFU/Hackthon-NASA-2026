"""Torre 4: zoneamento oficial (ZARC/MAPA) por município, data de plantio e solo.

Uso:
    from towers.t4_zarc import avaliar_t4
    resultado = avaliar_t4(lat=-23.3, lon=-51.2, data_plantio=date(2026, 10, 15))
"""
from .torre import avaliar_t4

__all__ = ["avaliar_t4"]
