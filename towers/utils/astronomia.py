"""Funções astronômicas da FAO-56 (Allen et al., 1998, cap. 3).

Usadas pela Torre 1 (comprimento do dia → alerta de fotoperíodo) e pela Torre 2
(radiação extraterrestre Ra → ET0 por Hargreaves).

Todas as funções aceitam escalares ou arrays NumPy e trabalham com latitude em graus
decimais (negativa no hemisfério sul) e dia do ano J (1–366).
"""
from __future__ import annotations

from datetime import date
from typing import Iterable

import numpy as np

GSC = 0.0820  # constante solar (MJ m⁻² min⁻¹)


def dia_do_ano(datas: Iterable[date] | date) -> np.ndarray | int:
    """Dia do ano (J) de uma data ou de uma sequência de datas."""
    if isinstance(datas, date):
        return datas.timetuple().tm_yday
    return np.array([d.timetuple().tm_yday for d in datas])


def declinacao_solar(j):
    """Declinação solar δ (rad), FAO-56 eq. 24."""
    return 0.409 * np.sin(2 * np.pi * np.asarray(j) / 365 - 1.39)


def distancia_relativa_terra_sol(j):
    """Inverso da distância relativa Terra–Sol dr, FAO-56 eq. 23."""
    return 1 + 0.033 * np.cos(2 * np.pi * np.asarray(j) / 365)


def angulo_por_do_sol(lat: float, j):
    """Ângulo horário do pôr do sol ωs (rad), FAO-56 eq. 25.

    O argumento do arccos é limitado a [-1, 1] para latitudes polares (sol da meia-noite
    ou noite polar), que não ocorrem no Brasil, mas evitam NaN em testes.
    """
    phi = np.radians(lat)
    return np.arccos(np.clip(-np.tan(phi) * np.tan(declinacao_solar(j)), -1.0, 1.0))


def comprimento_dia(lat: float, j):
    """Horas de luz N (h), FAO-56 eq. 34."""
    return 24 / np.pi * angulo_por_do_sol(lat, j)


def radiacao_extraterrestre(lat: float, j):
    """Radiação extraterrestre diária Ra (MJ m⁻² dia⁻¹), FAO-56 eq. 21."""
    phi = np.radians(lat)
    delta = declinacao_solar(j)
    ws = angulo_por_do_sol(lat, j)
    return (
        24 * 60 / np.pi * GSC * distancia_relativa_terra_sol(j)
        * (ws * np.sin(phi) * np.sin(delta) + np.cos(phi) * np.cos(delta) * np.sin(ws))
    )
