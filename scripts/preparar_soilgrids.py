"""Pré-calcula o SoilGrids para o Brasil inteiro numa grade de 0,01° (≈ 1,1 km), em blocos de 1°.

    python scripts/preparar_soilgrids.py            # ~25 min na primeira vez; retoma se for interrompido

Por que: a API REST do SoilGrids é lenta (10–15 s por consulta, com quedas) e tem limite de uso; não dá para
pré-consultar o país ponto a ponto. Os mapas da ISRIC (CC-BY 4.0) são lidos direto do servidor de arquivos, só
na janela do Brasil:

- propriedades: ``data_aggregated/1000m`` (média de 250 m reamostrada para 1 km, projeção Homolosine),
  reprojetadas para graus;
- classes WRB: probabilidade de cada uma das 30 classes (250 m, em graus), pela overview de ~1 km.

Mesmos cálculos de ``towers.data.soilgrids``: textura = média 0–60 cm ponderada pela espessura; química = 0–30 cm;
classe = as 3 mais prováveis. Pixel sem dado (água, área urbana) recebe o valor do pixel válido mais próximo
em até 0,1° (o anel de busca da consulta pela API), com a distância registrada.

Saída: ``data/raw/soilgrids/grade_brasil.parquet`` (lat_n, lon_w, bloco = npz comprimido). Depois:
``python scripts/carregar_neon.py soilgrids_grade``. Requer ``rasterio`` e ``scipy`` (só este script).
"""
from __future__ import annotations

import io
import logging
import sys
import time
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from towers.data.soilgrids_grade import (  # noqa: E402
    CAMINHO_GRADE, CLASSES_WRB, ESCALA, LESTE, NORTE, OESTE, RESOLUCAO, SUL, TAM_BLOCO,
)

log = logging.getLogger("preparar_soilgrids")

BASE = "/vsicurl/https://files.isric.org/soilgrids/latest/"
CAMADAS_DIR = ROOT / "data" / "raw" / "soilgrids" / "camadas"
TEXTURA = {"sand": "areia", "silt": "silte", "clay": "argila"}
QUIMICA = {"phh2o": "ph", "cec": "ctc", "soc": "carbono_organico", "bdod": "densidade"}
PROF_0_60 = {"0-5cm": 5, "5-15cm": 10, "15-30cm": 15, "30-60cm": 30}
PROF_0_30 = {"0-5cm": 5, "5-15cm": 10, "15-30cm": 15}
# d_factor da ISRIC: valor do mapa ÷ fator = unidade usada no código (%, pH, cmol(c)/kg, g/kg, kg/dm³)
FATOR = {"sand": 10, "silt": 10, "clay": 10, "phh2o": 10, "cec": 10, "soc": 10, "bdod": 100}
RAIO_PREENCHER = 10          # pixels (0,1°)
MARGEM_BLOCO_GRAUS = 0.5     # guarda os blocos com sede de município a até 0,5°

ALTURA = round((NORTE - SUL) / RESOLUCAO)
LARGURA = round((LESTE - OESTE) / RESOLUCAO)


def _env():
    from rasterio.env import Env
    return Env(GDAL_HTTP_TIMEOUT=120, GDAL_HTTP_MAX_RETRY=8, GDAL_HTTP_RETRY_DELAY=3, VSI_CACHE=True,
               GDAL_CACHEMAX=512, CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif,.vrt,.ovr")


def _ler(caminho_remoto: str, reprojetar: bool) -> np.ndarray:
    """Janela do Brasil na grade de 0,01°, como float32 com NaN onde não há dado.

    O cache em disco guarda o tipo original do mapa (int16 ou uint8), para retomar sem baixar de novo.
    """
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.transform import from_origin
    from rasterio.vrt import WarpedVRT
    from rasterio.windows import from_bounds

    local = CAMADAS_DIR / (caminho_remoto.replace("/", "__") + ".npz")
    if local.exists():
        z = np.load(local)
        return _como_float(z["a"], z["nodata"].item())
    t = time.perf_counter()
    for tentativa in range(4):
        try:
            with _env(), rasterio.open(BASE + caminho_remoto) as src:
                if reprojetar:
                    tr = from_origin(OESTE, NORTE, RESOLUCAO, RESOLUCAO)
                    with WarpedVRT(src, crs="EPSG:4326", transform=tr, width=LARGURA, height=ALTURA,
                                   resampling=Resampling.average, src_nodata=src.nodata, nodata=src.nodata) as v:
                        a = v.read(1)
                else:
                    a = src.read(1, window=from_bounds(OESTE, SUL, LESTE, NORTE, src.transform),
                                 out_shape=(ALTURA, LARGURA), resampling=Resampling.average)
                nodata = src.nodata
            break
        except Exception as e:  # rede instável: tenta de novo
            log.warning("falha ao ler %s (%s); tentativa %d", caminho_remoto, e, tentativa + 1)
            time.sleep(10 * (tentativa + 1))
    else:
        raise RuntimeError(f"não foi possível ler {caminho_remoto}")
    CAMADAS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = local.with_suffix(".tmp.npz")
    np.savez(tmp, a=a, nodata=np.array(nodata))
    tmp.replace(local)
    log.info("%-60s %4.0f s", caminho_remoto, time.perf_counter() - t)
    return _como_float(a, nodata)


def _como_float(a: np.ndarray, nodata) -> np.ndarray:
    f = a.astype(np.float32)
    f[a == nodata] = np.nan
    return f


def _media_ponderada(prop: str, profs: dict[str, int]) -> np.ndarray:
    soma = sum(_ler(f"data_aggregated/1000m/{prop}/{prop}_{d}_mean_1000.tif", True) * e for d, e in profs.items())
    return soma / sum(profs.values()) / FATOR[prop]       # NaN em qualquer profundidade → NaN (como a API)


def _preencher(valido: np.ndarray, *arrays: np.ndarray) -> tuple[list[np.ndarray], np.ndarray]:
    """Copia para os pixels inválidos o valor do válido mais próximo (até RAIO_PREENCHER); distância em pixels."""
    from scipy.ndimage import distance_transform_edt
    dist, (ii, jj) = distance_transform_edt(~valido, return_indices=True)
    perto = dist <= RAIO_PREENCHER
    saida = []
    for a in arrays:
        b = a[ii, jj]
        b[~perto] = np.nan if np.issubdtype(a.dtype, np.floating) else 255
        saida.append(b)
    return saida, np.where(perto, np.round(dist), 255).astype(np.uint8)


def calcular() -> dict[str, np.ndarray]:
    g: dict[str, np.ndarray] = {}
    tex = {nome: _media_ponderada(p, PROF_0_60) for p, nome in TEXTURA.items()}
    valido = np.logical_and.reduce([np.isfinite(a) for a in tex.values()])
    preenchidos, g["dist_textura"] = _preencher(valido, *tex.values())
    g.update(zip(tex, preenchidos))

    qui = {nome: _media_ponderada(p, PROF_0_30) for p, nome in QUIMICA.items()}
    valido = np.logical_and.reduce([np.isfinite(a) for a in qui.values()])
    preenchidos, g["dist_quimica"] = _preencher(valido, *qui.values())
    g.update(zip(qui, preenchidos))

    # classes WRB: as 3 de maior probabilidade em cada pixel (top-3 atualizado classe a classe: pouca memória)
    shape = (ALTURA, LARGURA)
    top = [np.full(shape, 255, np.uint8) for _ in range(3)]
    ptop = [np.full(shape, -1.0, np.float32) for _ in range(3)]
    valido, soma = np.ones(shape, bool), np.zeros(shape, np.float32)
    for k, c in enumerate(CLASSES_WRB):
        p = _ler(f"data/wrb/{c}.vrt", False)
        valido &= np.isfinite(p)
        p = np.nan_to_num(p, nan=-1)
        soma += np.maximum(p, 0)
        for pos in range(3):           # insere p na posição certa e empurra os de baixo
            maior = p > ptop[pos]
            for baixo in range(2, pos, -1):
                top[baixo] = np.where(maior, top[baixo - 1], top[baixo])
                ptop[baixo] = np.where(maior, ptop[baixo - 1], ptop[baixo])
            top[pos] = np.where(maior, np.uint8(k), top[pos])
            ptop_pos = np.where(maior, p, ptop[pos])
            p = np.where(maior, -2, p)          # já inserido: não entra nas posições seguintes
            ptop[pos] = ptop_pos
        del p
    valido &= soma > 0
    preenchidos, g["dist_classe"] = _preencher(valido, *top, *ptop)
    for k in range(3):
        g[f"classe{k + 1}"] = preenchidos[k]
        g[f"prob{k + 1}"] = preenchidos[3 + k]
    return g


def _inteiro(nome: str, a: np.ndarray) -> np.ndarray:
    if a.dtype == np.uint8:
        return a
    if nome.startswith("prob"):
        return np.where(np.isfinite(a), np.clip(np.round(a), 0, 100), 255).astype(np.uint8)
    return np.where(np.isfinite(a), np.round(a * ESCALA[nome]), -32768).astype(np.int16)


def blocos(g: dict[str, np.ndarray]) -> pl.DataFrame:
    mun = pl.read_csv(ROOT / "data" / "raw" / "ibge" / "municipios.csv")
    lats, lons = mun["latitude"].to_numpy(), mun["longitude"].to_numpy()
    linhas = []
    for lat_n in range(int(NORTE), int(SUL), -1):
        for lon_w in range(int(OESTE), int(LESTE)):
            perto = ((lats <= lat_n + MARGEM_BLOCO_GRAUS) & (lats >= lat_n - 1 - MARGEM_BLOCO_GRAUS)
                     & (lons >= lon_w - MARGEM_BLOCO_GRAUS) & (lons <= lon_w + 1 + MARGEM_BLOCO_GRAUS)).any()
            if not perto:
                continue
            i0, j0 = round((NORTE - lat_n) / RESOLUCAO), round((lon_w - OESTE) / RESOLUCAO)
            fatia = {k: _inteiro(k, v[i0:i0 + TAM_BLOCO, j0:j0 + TAM_BLOCO]) for k, v in g.items()}
            if all((fatia[d] == 255).all() for d in ("dist_textura", "dist_quimica", "dist_classe")):
                continue          # bloco inteiro sem dado (oceano)
            buf = io.BytesIO()
            np.savez_compressed(buf, **fatia)
            linhas.append({"lat_n": lat_n, "lon_w": lon_w, "bloco": buf.getvalue()})
    return pl.DataFrame(linhas, schema={"lat_n": pl.Int16, "lon_w": pl.Int16, "bloco": pl.Binary})


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    t = time.perf_counter()
    df = blocos(calcular())
    CAMINHO_GRADE.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(CAMINHO_GRADE)
    mb = CAMINHO_GRADE.stat().st_size / 1e6
    log.info("grade: %d blocos de 1°, %.1f MB, em %.0f min → %s", df.height, mb, (time.perf_counter() - t) / 60,
             CAMINHO_GRADE.relative_to(ROOT).as_posix())


if __name__ == "__main__":
    main()
