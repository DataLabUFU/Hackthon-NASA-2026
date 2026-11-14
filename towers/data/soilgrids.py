"""Solo por coordenada via SoilGrids 2.0 (ISRIC), com cache.

API: https://rest.isric.org/soilgrids/v2.0/docs (sem chave). Resolução de 250 m.

- ``textura``: areia/silte/argila (%), média ponderada 0–60 cm (usada pela T2 e pela T3).
- ``quimica``: pH em água, CTC a pH 7 (cmol(c)/kg), carbono orgânico (g/kg) e densidade (g/cm³), 0–30 cm.
- ``classe_wrb``: classe de solo WRB mais provável e as 3 primeiras com probabilidade (%).

Pontos sem dado (área urbana, água) são comuns no centro das cidades: procura-se o ponto válido
mais próximo num anel de até ~10 km. Só coordenadas são enviadas à API.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Callable

import requests

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
CACHE_PADRAO = ROOT / "data" / "cache" / "soilgrids"
URL_PROPRIEDADES = "https://rest.isric.org/soilgrids/v2.0/properties/query"
URL_CLASSE = "https://rest.isric.org/soilgrids/v2.0/classification/query"
USER_AGENT = "towers-soilgrids/0.1 (python-requests)"

CAMADAS_0_60 = {"0-5cm": 5, "5-15cm": 10, "15-30cm": 15, "30-60cm": 30}
CAMADAS_0_30 = {"0-5cm": 5, "5-15cm": 10, "15-30cm": 15}
# anel de busca quando o ponto não tem dado (graus): ~2, 5 e 10 km
RAIOS = (0.02, 0.05, 0.1)
# conversões: valor da API ÷ d_factor → unidade-alvo; ajustes adicionais para as unidades usadas aqui
NOMES_TEXTURA = {"sand": "areia", "silt": "silte", "clay": "argila"}                      # %
NOMES_QUIMICA = {"phh2o": "ph", "cec": "ctc", "soc": "carbono_organico", "bdod": "densidade"}


def consultar_propriedades(lat: float, lon: float, propriedades: tuple[str, ...], camadas: dict[str, int],
                           sessao: requests.Session | None = None) -> dict | None:
    """Média ponderada pela espessura de cada propriedade, ou None se o ponto não tiver dado.

    Unidades de saída (após o d_factor): textura %, pH, CTC cmol(c)/kg, carbono g/kg, densidade kg/dm³.
    """
    params = [("lon", lon), ("lat", lat), ("value", "mean")]
    params += [("property", p) for p in propriedades] + [("depth", d) for d in camadas]
    r = (sessao or requests).get(URL_PROPRIEDADES, params=params, headers={"User-Agent": USER_AGENT}, timeout=60)
    r.raise_for_status()
    valores = {}
    for camada in r.json()["properties"]["layers"]:
        fator = camada["unit_measure"]["d_factor"]
        prof = {d["label"]: d["values"]["mean"] for d in camada["depths"]}
        if any(prof.get(c) is None for c in camadas):
            return None
        valores[camada["name"]] = sum(prof[c] * e for c, e in camadas.items()) / sum(camadas.values()) / fator
    return valores


def consultar(lat: float, lon: float, sessao: requests.Session | None = None) -> dict | None:
    """Textura média 0–60 cm em % ({areia, silte, argila})."""
    v = consultar_propriedades(lat, lon, tuple(NOMES_TEXTURA), CAMADAS_0_60, sessao)
    return None if v is None else {NOMES_TEXTURA[k]: v[k] for k in NOMES_TEXTURA}


def consultar_quimica(lat: float, lon: float, sessao: requests.Session | None = None) -> dict | None:
    """pH, CTC (cmol(c)/kg), carbono orgânico (g/kg) e densidade (kg/dm³), 0–30 cm."""
    v = consultar_propriedades(lat, lon, tuple(NOMES_QUIMICA), CAMADAS_0_30, sessao)
    if v is None:
        return None
    return {"ph": v["phh2o"], "ctc": v["cec"], "carbono_organico": v["soc"], "densidade": v["bdod"]}


def consultar_classe(lat: float, lon: float, sessao: requests.Session | None = None) -> dict | None:
    r = (sessao or requests).get(URL_CLASSE, params={"lon": lon, "lat": lat, "number_classes": 3},
                                 headers={"User-Agent": USER_AGENT}, timeout=60)
    r.raise_for_status()
    d = r.json()
    if not d.get("wrb_class_name") or d["wrb_class_name"] == "No information":
        return None
    return {"wrb": d["wrb_class_name"], "wrb_probabilidades": d.get("wrb_class_probability", [])}


def _com_vizinhos(nome: str, lat: float, lon: float, cache_dir: Path | str, consulta: Callable) -> dict | None:
    """Consulta o ponto (ou o vizinho válido mais próximo) com cache por tipo de consulta."""
    cache_dir = Path(cache_dir)
    arquivo = cache_dir / f"{nome}_{lat:+.3f}_{lon:+.3f}.json"
    if arquivo.exists():
        return json.loads(arquivo.read_text(encoding="utf-8")) or None
    candidatos = [(0.0, lat, lon)] + [
        (r, lat + dy * r, lon + dx * r) for r in RAIOS for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1))
    ]
    resultado = None
    for dist, la, lo in candidatos:
        v = consulta(la, lo)
        if v is not None:
            resultado = v | {"distancia_graus": dist}
            break
    if resultado is None:
        log.warning("SoilGrids (%s): sem dado em até %.2f° de (%.3f, %.3f)", nome, RAIOS[-1], lat, lon)
    cache_dir.mkdir(parents=True, exist_ok=True)
    arquivo.write_text(json.dumps(resultado or {}), encoding="utf-8")
    return resultado


def textura(lat: float, lon: float, cache_dir: Path | str = CACHE_PADRAO, consulta=consultar) -> dict | None:
    return _com_vizinhos("textura", lat, lon, cache_dir, consulta)


def quimica(lat: float, lon: float, cache_dir: Path | str = CACHE_PADRAO, consulta=consultar_quimica) -> dict | None:
    return _com_vizinhos("quimica", lat, lon, cache_dir, consulta)


def classe_wrb(lat: float, lon: float, cache_dir: Path | str = CACHE_PADRAO, consulta=consultar_classe) -> dict | None:
    return _com_vizinhos("classe", lat, lon, cache_dir, consulta)
