"""Evapotranspiração de referência (ET0), FAO-56.

- ``et0_penman_monteith``: equação 6 da FAO-56 (padrão), com umidade relativa média (eq. 19),
  radiação solar medida (Rs, da POWER) e pressão atmosférica da própria POWER (PS).
- ``et0_hargreaves``: equação 52, só com temperatura; usada onde a radiação ainda não foi publicada
  (a POWER publica a radiação com ~2,5 meses de atraso).

Unidades: temperatura °C, UR %, vento a 2 m em m/s, Rs em MJ m⁻² dia⁻¹, pressão em kPa → ET0 em mm/dia.
"""
from __future__ import annotations

import numpy as np

from .astronomia import radiacao_extraterrestre

SIGMA = 4.903e-9  # Stefan-Boltzmann (MJ K⁻⁴ m⁻² dia⁻¹)


def pressao_vapor_saturacao(t):
    """e°(T) em kPa (eq. 11)."""
    return 0.6108 * np.exp(17.27 * t / (t + 237.3))


def altitude_da_pressao(p_kpa):
    """Inverte a eq. 7 (P = 101,3 ((293 − 0,0065 z) / 293)^5,26) → altitude em m."""
    return (293.0 - 293.0 * (np.asarray(p_kpa) / 101.3) ** (1 / 5.26)) / 0.0065


def et0_penman_monteith(tmax, tmin, ur_media, u2, rs, lat: float, j, pressao_kpa):
    tmax, tmin, ur_media, u2, rs, pressao_kpa = map(np.asarray, (tmax, tmin, ur_media, u2, rs, pressao_kpa))
    tmed = (tmax + tmin) / 2
    delta = 4098 * pressao_vapor_saturacao(tmed) / (tmed + 237.3) ** 2            # eq. 13
    gama = 0.000665 * pressao_kpa                                               # eq. 8
    es = (pressao_vapor_saturacao(tmax) + pressao_vapor_saturacao(tmin)) / 2    # eq. 12
    ea = ur_media / 100 * es                                                    # eq. 19
    ra = radiacao_extraterrestre(lat, j)
    rso = (0.75 + 2e-5 * altitude_da_pressao(pressao_kpa)) * ra                 # eq. 37
    rns = 0.77 * rs                                                             # eq. 38 (albedo 0,23)
    razao = np.clip(rs / np.where(rso > 0, rso, np.nan), 0.25, 1.0)
    rnl = (SIGMA * ((tmax + 273.16) ** 4 + (tmin + 273.16) ** 4) / 2
           * (0.34 - 0.14 * np.sqrt(ea)) * (1.35 * razao - 0.35))              # eq. 39
    rn = rns - rnl
    et0 = (0.408 * delta * rn + gama * 900 / (tmed + 273) * u2 * (es - ea)) / (delta + gama * (1 + 0.34 * u2))
    return np.maximum(et0, 0.0)


def et0_hargreaves(tmax, tmin, lat: float, j):
    tmax, tmin = np.asarray(tmax), np.asarray(tmin)
    ra_mm = 0.408 * radiacao_extraterrestre(lat, j)
    return np.maximum(0.0023 * ((tmax + tmin) / 2 + 17.8) * np.sqrt(np.clip(tmax - tmin, 0, None)) * ra_mm, 0.0)
