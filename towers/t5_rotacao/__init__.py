"""Torre 5: rotação de culturas a partir do histórico (última e penúltima safra).

Uso:
    from towers.t5_rotacao import avaliar_t5
    resultado = avaliar_t5(ultimo="Soja", penultimo="Milho")
"""
from .torre import avaliar_t5

__all__ = ["avaliar_t5"]
