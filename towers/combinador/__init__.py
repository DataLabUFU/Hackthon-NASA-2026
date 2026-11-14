"""Combinador das torres e ordenador da recomendação (melhores, intermediárias e piores)."""
from .combinador import combinar
from .ordenador import localizar, ordenar, setores
from .pesos import OBJETIVOS
from .recomendador import Recomendacao, recomendar

__all__ = ["OBJETIVOS", "Recomendacao", "combinar", "localizar", "ordenar", "recomendar", "setores"]
