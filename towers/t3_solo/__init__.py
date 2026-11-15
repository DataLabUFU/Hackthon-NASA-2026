"""Torre 3: aptidão do solo (requisitos do ECOCROP × SoilGrids + informações do produtor).

Uso:
    from towers.t3_solo import avaliar_t3
    resultado = avaliar_t3(lat=-23.3, lon=-51.2, problemas_solo=["compactado"], analise={"ph": 5.2})
"""
from .torre import avaliar_t3

__all__ = ["avaliar_t3"]
