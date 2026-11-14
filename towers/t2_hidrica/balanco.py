"""Componente 4 da T2: balanço hídrico diário FAO-56 (coeficiente de cultura único), vetorizado.

Todas as simulações de um grupo (mesma duração total) andam juntas: arrays [simulações × dias].

    Ks  = 1                              se Dr ≤ RAW
        = (TAW − Dr) / ((1 − p) × TAW)   se Dr > RAW          (FAO-56 eq. 84)
    ETa = Ks × Kc × ET0
    Dr  = clip(Dr − P + ETa, 0, TAW)                          (excesso drena; sem escoamento na v0)

Os ``dias_pre`` iniciais (entre a data do estado do solo e o plantio) usam Kc de solo nu
(``KC_SOLO_NU``) e não entram nas métricas da cultura.
"""
from __future__ import annotations

import numpy as np

KC_SOLO_NU = 0.3


def simular(P: np.ndarray, ET0: np.ndarray, kc: np.ndarray, taw: np.ndarray, p: np.ndarray, dr0: np.ndarray,
            dias_pre: int, fase_critica: np.ndarray) -> dict[str, np.ndarray]:
    """Balanço diário.

    P, ET0, kc: [n, T] (T = dias_pre + ciclo); taw, p, dr0: [n]; fase_critica: [n, 2] (início, fim)
    em dias a partir do plantio. Retorna totais por simulação: etc, eta (ciclo), etc_crit, eta_crit
    (fase crítica = intermediária, floração/enchimento).
    """
    n, T = P.shape
    raw = p * taw
    dr = dr0.astype(float).copy()
    tot = {k: np.zeros(n) for k in ("etc", "eta", "etc_crit", "eta_crit")}
    for t in range(T):
        etc = kc[:, t] * ET0[:, t]
        excesso = np.maximum(dr - raw, 0.0)
        ks = np.where(excesso > 0, np.clip((taw - dr) / np.maximum((1 - p) * taw, 1e-9), 0.0, 1.0), 1.0)
        eta = ks * etc
        dr = np.clip(dr - P[:, t] + eta, 0.0, taw)
        d = t - dias_pre
        if d >= 0:
            tot["etc"] += etc
            tot["eta"] += eta
            crit = (d >= fase_critica[:, 0]) & (d < fase_critica[:, 1])
            tot["etc_crit"] += np.where(crit, etc, 0.0)
            tot["eta_crit"] += np.where(crit, eta, 0.0)
    return tot
