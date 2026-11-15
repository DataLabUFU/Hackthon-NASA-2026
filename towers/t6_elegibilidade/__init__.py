"""Torre 6: elegibilidade a crédito de custeio, Proagro e seguro rural (PSR).

Uso:
    from towers.t6_elegibilidade import avaliar_t6
    resultado = avaliar_t6(lat=-23.3, lon=-51.2, data_plantio=date(2026, 10, 15), imovel={"car": "ativo"})
"""
from .torre import avaliar_t6

__all__ = ["avaliar_t6"]
