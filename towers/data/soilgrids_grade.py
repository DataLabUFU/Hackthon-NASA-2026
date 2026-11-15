"""SoilGrids pré-calculado para o Brasil: grade de 0,01° (≈ 1,1 km) em blocos de 1° × 1°.

Gerado por ``scripts/preparar_soilgrids.py`` a partir dos mapas da ISRIC (CC-BY 4.0). Os blocos ficam em
``data/raw/soilgrids/grade_brasil.parquet`` e, para o app na nuvem, na tabela ``soilgrids_grade`` do NeonDB.

``consultar(tipo, lat, lon)`` devolve ``(coberto, dados)``, com ``dados`` no mesmo formato das consultas à API
em ``towers.data.soilgrids``: ``coberto`` = False quando o ponto está fora da grade ou ela não está disponível
(o chamador usa a API); ``dados`` None = pixel sem dado num raio de 0,1° (água, área urbana extensa).
"""
from __future__ import annotations

import io
import logging
import math
import threading
from functools import lru_cache
from pathlib import Path

import numpy as np
import polars as pl

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
CAMINHO_GRADE = ROOT / "data" / "raw" / "soilgrids" / "grade_brasil.parquet"
NORTE, SUL, OESTE, LESTE = 6, -34, -75, -34        # janela (graus inteiros: blocos de 1° alinhados)
RESOLUCAO = 0.01
TAM_BLOCO = 100                                     # pixels por lado (1°)
# valor guardado (int16) = valor × escala; -32768 = sem dado
ESCALA = {"areia": 10, "silte": 10, "argila": 10, "ph": 100, "ctc": 10, "carbono_organico": 10, "densidade": 100}
CLASSES_WRB = (
    "Acrisols", "Albeluvisols", "Alisols", "Andosols", "Arenosols", "Calcisols", "Cambisols", "Chernozems",
    "Cryosols", "Durisols", "Ferralsols", "Fluvisols", "Gleysols", "Gypsisols", "Histosols", "Kastanozems",
    "Leptosols", "Lixisols", "Luvisols", "Nitisols", "Phaeozems", "Planosols", "Plinthosols", "Podzols",
    "Regosols", "Solonchaks", "Solonetz", "Stagnosols", "Umbrisols", "Vertisols",
)
CAMPOS = {"textura": ("areia", "silte", "argila"), "quimica": ("ph", "ctc", "carbono_organico", "densidade")}
SEM_DADO_DIST = 255

_lock = threading.Lock()


def indice(lat: float, lon: float) -> tuple[int, int, int, int] | None:
    """(lat_n, lon_w, i, j) do pixel que contém o ponto, ou None fora da janela."""
    if not (SUL < lat <= NORTE and OESTE <= lon < LESTE):
        return None
    i_g = math.floor((NORTE - lat) / RESOLUCAO + 1e-9)
    j_g = math.floor((lon - OESTE) / RESOLUCAO + 1e-9)
    return NORTE - i_g // TAM_BLOCO, OESTE + j_g // TAM_BLOCO, i_g % TAM_BLOCO, j_g % TAM_BLOCO


@lru_cache(maxsize=1)
def disponivel() -> bool:
    if CAMINHO_GRADE.exists():
        return True
    from . import neon
    return neon.habilitado()


@lru_cache(maxsize=32)
def _bloco(lat_n: int, lon_w: int) -> dict[str, np.ndarray] | None:
    """Arrays do bloco (None = bloco não existe: fora do Brasil ou só oceano). Erro de rede → exceção."""
    if CAMINHO_GRADE.exists():
        df = pl.scan_parquet(CAMINHO_GRADE).filter(
            (pl.col("lat_n") == lat_n) & (pl.col("lon_w") == lon_w)).select("bloco").collect()
        conteudo = df["bloco"][0] if df.height else None
    else:
        from . import neon
        conteudo = neon.ler_bloco_soilgrids(lat_n, lon_w)
    if conteudo is None:
        return None
    with np.load(io.BytesIO(conteudo)) as z:
        return {k: z[k] for k in z.files}


def consultar(tipo: str, lat: float, lon: float) -> tuple[bool, dict | None]:
    if not disponivel() or (idx := indice(lat, lon)) is None:
        return False, None
    lat_n, lon_w, i, j = idx
    try:
        with _lock:
            b = _bloco(lat_n, lon_w)
    except Exception as e:
        log.warning("SoilGrids (grade): bloco (%d, %d) indisponível (%s); usando a API", lat_n, lon_w,
                    type(e).__name__)
        return False, None
    if b is None:
        return False, None
    dist = int(b[f"dist_{tipo}"][i, j])
    if dist == SEM_DADO_DIST:
        return True, None
    if tipo == "classe":
        top = [(CLASSES_WRB[int(b[f"classe{k}"][i, j])], int(b[f"prob{k}"][i, j])) for k in (1, 2, 3)
               if b[f"classe{k}"][i, j] != 255 and b[f"prob{k}"][i, j] != 255]
        if not top:
            return True, None
        dados = {"wrb": top[0][0], "wrb_probabilidades": [list(t) for t in top]}
    else:
        brutos = {c: int(b[c][i, j]) for c in CAMPOS[tipo]}
        if any(v == -32768 for v in brutos.values()):
            return True, None
        dados = {c: v / ESCALA[c] for c, v in brutos.items()}
    return True, dados | {"distancia_graus": round(dist * RESOLUCAO, 3), "fonte": "grade"}
