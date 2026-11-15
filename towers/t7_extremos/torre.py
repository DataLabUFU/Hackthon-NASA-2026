"""Torre 7 no recomendador: chance de extremos climáticos no ciclo de cada cultura, em qualquer ponto do Brasil.

    avaliar_t7(lat, lon, data_plantio) → uma linha por (cultura, data de plantio)

A consulta original (``consulta.py``) lê o CSV dos 20 pontos do Triângulo Mineiro. Aqui os mesmos eventos, com
os mesmos limiares (``configs/extremos.yaml``) e as mesmas funções (``eventos.py``,
``referencia.indicadores_diarios``), são calculados sobre a série diária do NASA POWER da célula do local, a
mesma que T1 e T2 usam (``PRECTOTCORR`` para a chuva, como na calibração dos limiares; ``T2M`` para a queda).

- Eventos: chuva extrema (> 80 mm em 3 dias) e queda brusca (T2M cai ≥ 5 °C em 2 dias); ``algum`` = um dos dois.
- Fases (genéricas; as janelas por cultura são pendência do README da T7), em dias após o plantio:
  estabelecimento 0–20 (chuva e queda), floração 40–65% do ciclo (queda), colheita últimos 20 dias (chuva).
  Perenes e silvicultura: só o estabelecimento (a decisão é a implantação).
- Ciclo: ponto médio de ``ciclo_min``–``ciclo_max`` do catálogo (independente da T1).
- Probabilidade: fração de anos com evento nas janelas, repetindo a data de plantio em cada ano da série (todos
  os anos completos desde 2001), com IC por bootstrap de anos (``probabilidade_bootstrap`` da T7).
- Score: ``score_t7 = 1 − p_algum`` (a conversão sugerida no README); as probabilidades seguem na saída.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Iterable

import numpy as np
import pandas as pd
import polars as pl

from towers.data.culturas import carregar_culturas, culturas_exibiveis
from towers.data.power import PARAMS_T1, clima_diario

from . import config as cfg_mod
from .probabilidade import probabilidade_bootstrap, semente_do_ponto
from .referencia import indicadores_diarios

log = logging.getLogger(__name__)

DESLOCAMENTOS_PADRAO = (-30, -20, -10, 0, 10, 20, 30)
CICLO_PADRAO = 120
DIAS_ESTABELECIMENTO = 20
DIAS_COLHEITA = 20
FLORACAO = (0.40, 0.65)
EVENTOS = ("chuva_extrema", "queda_brusca")


def fases_da_cultura(ciclo: int, modo: str | None, uso: str | None) -> list[dict]:
    """Janelas (dias após o plantio) e eventos que contam em cada uma."""
    estab = {"nome": "estabelecimento", "inicio": 0, "fim": DIAS_ESTABELECIMENTO, "eventos": list(EVENTOS)}
    if modo == "implantacao" or uso == "silvicultura":
        return [estab]
    ciclo = max(int(ciclo), DIAS_ESTABELECIMENTO + DIAS_COLHEITA + 10)
    return [
        estab,
        {"nome": "floracao", "inicio": round(FLORACAO[0] * ciclo), "fim": round(FLORACAO[1] * ciclo),
         "eventos": ["queda_brusca"]},
        {"nome": "colheita", "inicio": ciclo - DIAS_COLHEITA, "fim": ciclo, "eventos": ["chuva_extrema"]},
    ]


def _ciclo(r: dict) -> int:
    lo, hi = r.get("ciclo_min"), r.get("ciclo_max")
    if lo and hi:
        return int(round((lo + hi) / 2))
    return int(lo or hi or CICLO_PADRAO)


def _somas(ind: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Somas acumuladas (com zero à frente) de eventos e de dias sem dado: janela em O(1)."""
    nan = np.isnan(ind)
    return (np.concatenate([[0], np.cumsum(np.where(nan, 0, ind))]),
            np.concatenate([[0], np.cumsum(nan)]))


def _houve(somas, a: int, z: int, n: int) -> float:
    """1/0 se houve evento entre os dias a e z (índices da série), NaN se faltar dia."""
    if a < 0 or z >= n:
        return np.nan
    ev, nan = somas
    if nan[z + 1] - nan[a] > 0:
        return np.nan
    return 1.0 if ev[z + 1] - ev[a] > 0 else 0.0


def avaliar_t7(lat: float, lon: float, data_plantio: date,
               deslocamentos: Iterable[int] = DESLOCAMENTOS_PADRAO,
               culturas: pl.DataFrame | None = None, clima: pl.DataFrame | None = None, cfg=None,
               incluir_silvicultura: bool = True, colapsar_variantes: bool = True) -> pl.DataFrame:
    """Probabilidades de extremos no ciclo e ``score_t7`` para cada cultura e data de plantio."""
    cfg = cfg or cfg_mod.carregar_config()
    if culturas is None:
        culturas = culturas_exibiveis(carregar_culturas(), incluir_silvicultura=incluir_silvicultura)
    if clima is None:
        clima = clima_diario(lat, lon, params=PARAMS_T1)
    serie = clima.select("data", "PRECTOTCORR", "T2M").sort("data").to_pandas()
    serie.insert(0, "PONTO", "local")
    serie["data"] = pd.to_datetime(serie["data"])
    ind = indicadores_diarios(serie, cfg)
    d0 = serie["data"].iloc[0].date()
    n = len(serie)
    somas = {ev: _somas(ind[ev].to_numpy(float)) for ev in EVENTOS}
    anos = list(range(d0.year, serie["data"].iloc[-1].year + 1))
    plantios = [data_plantio + timedelta(days=d) for d in deslocamentos]

    # combinações únicas de (plantio, fases): culturas com o mesmo ciclo e modo compartilham o cálculo
    linhas_cult = [(r["id_cultura"], fases_da_cultura(_ciclo(r), r.get("modo"), r.get("uso")))
                   for r in culturas.iter_rows(named=True)]
    combos: dict[tuple, int] = {}
    chave_cult = []
    for id_c, fases in linhas_cult:
        k_fases = tuple((f["inicio"], f["fim"], tuple(f["eventos"])) for f in fases)
        for p in plantios:
            chave = (p, k_fases)
            combos.setdefault(chave, len(combos))
            chave_cult.append((id_c, p, combos[chave], fases))

    mats = {ev: np.full((len(anos), len(combos)), np.nan) for ev in (*EVENTOS, "algum")}
    for (p, k_fases), j in combos.items():
        for i, ano in enumerate(anos):
            try:
                p0 = p.replace(year=ano)
            except ValueError:          # 29/02
                p0 = date(ano, 2, 28)
            base = (p0 - d0).days
            vals = {}
            for ev in EVENTOS:
                janelas = [(base + ini, base + fim) for ini, fim, evs in k_fases if ev in evs]
                if not janelas:
                    continue
                v = [_houve(somas[ev], a, z, n) for a, z in janelas]
                vals[ev] = np.nan if any(np.isnan(x) for x in v) else max(v)
            if any(np.isnan(x) for x in vals.values()):
                continue                 # ano incompleto sai de todos os eventos (mesmos anos nas três)
            for ev, x in vals.items():
                mats[ev][i, j] = x
            mats["algum"][i, j] = max(vals.values())

    b = cfg.bootstrap
    semente = semente_do_ponto(b.semente, f"{lat:.3f},{lon:.3f}")
    res = {ev: probabilidade_bootstrap(m, b.repeticoes, semente, b.nivel_ic) for ev, m in mats.items()}

    saida = []
    for id_c, p, j, fases in chave_cult:
        saida.append({
            "id_cultura": id_c, "plantio": p,
            "p_chuva_extrema": float(res["chuva_extrema"]["p"][j]),
            "p_queda_brusca": float(res["queda_brusca"]["p"][j]),
            "p_algum": float(res["algum"]["p"][j]),
            "p_algum_ic_inf": float(res["algum"]["ic_inf"][j]), "p_algum_ic_sup": float(res["algum"]["ic_sup"][j]),
            "n_anos_t7": int(res["algum"]["n_anos"][j]),
            "fases_t7": [f"{f['nome']} ({f['inicio']}–{f['fim']} dias)" for f in fases],
        })
    lc, lq = cfg.limiares.chuva_extrema, cfg.limiares.queda_temperatura
    df = pl.DataFrame(saida).with_columns(
        [pl.col(c).fill_nan(None) for c in ("p_chuva_extrema", "p_queda_brusca", "p_algum", "p_algum_ic_inf",
                                            "p_algum_ic_sup")]
    ).with_columns(
        score_t7=(1 - pl.col("p_algum")).cast(pl.Float64),
        limiares_t7=pl.lit(f"chuva > {lc.valor:g} {lc.unidade} em {lc.janela_dias} dias; queda ≥ {lq.valor:g} "
                           f"{lq.unidade} em {lq.janela_dias} dias ({lc.status})"),
    ).join(culturas.select("id_cultura", "nome_pt", "uso", "modo", "obrigatoria", "escala_cultivo"), on="id_cultura")

    ordenar = dict(by=["score_t7", "escala_cultivo", "nome_pt", "plantio"], descending=[True, False, False, False],
                   nulls_last=True)
    df = df.sort(**ordenar).with_columns(n_variantes=pl.len().over("nome_pt", "plantio"))
    if colapsar_variantes:
        df = df.group_by("nome_pt", "plantio", maintain_order=True).first()
    log.info("T7: %d culturas × %d datas; %d combinações de fases; anos %d–%d", culturas.height, len(plantios),
             len(combos), anos[0], anos[-1])
    ordem = ["id_cultura", "nome_pt", "uso", "modo", "plantio", "score_t7", "p_algum", "p_algum_ic_inf",
             "p_algum_ic_sup", "p_chuva_extrema", "p_queda_brusca", "n_anos_t7", "fases_t7", "limiares_t7",
             "n_variantes", "obrigatoria", "escala_cultivo"]
    return df.select(ordem).sort(**ordenar)
