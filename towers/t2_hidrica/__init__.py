"""Torre 2: simulação hídrica (balanço FAO-56 a partir da umidade atual do solo, NASA POWER + IMERG).

Uso:
    from towers.t2_hidrica import avaliar_t2
    resultado = avaliar_t2(lat=-23.3, lon=-51.2, data_plantio=date(2026, 11, 20))
"""
from .torre import avaliar_t2

__all__ = ["avaliar_t2"]
