"""Torre 7 no recomendador: chance de extremos climáticos no ciclo de cada cultura, em qualquer ponto do Brasil.

    avaliar_t7(lat, lon, data_plantio) → uma linha por (cultura, data de plantio)

A consulta original (``consulta.py``) lê o CSV dos 20 pontos do Triângulo Mineiro. Aqui os eventos são
calculados sobre a série diária do NASA POWER da célula do local (a mesma de T1 e T2), em qualquer ponto do país.

Eventos e fases vêm de ``configs/extremos.yaml`` (seção ``culturas``):

- por cultura (soja, milho, feijão, arroz, trigo, algodão): limiar de frio na fase sensível (``T2M_MIN`` abaixo
  de ``frio_tmin``, ex.: feijão < 12 °C na floração) e chuva persistente na colheita (N dias seguidos com chuva);
- demais culturas (``padrao``): os eventos gerais da T7, chuva extrema (> 80 mm em 3 dias, ``PRECTOTCORR`` como
  na calibração) e queda brusca de temperatura (≥ 5 °C em 2 dias);
- todas: chuva forte no estabelecimento (≥ 50 mm em um dia, nível "perigo" do INMET).
- Perenes e silvicultura: só o estabelecimento (a decisão é a implantação).

Probabilidade: fração de anos com evento nas janelas, repetindo a data de plantio em cada ano da série (anos
completos desde 2001), com IC por bootstrap de anos (``probabilidade_bootstrap`` da T7). Agrupada em
``p_chuva`` (chuva forte, persistente ou extrema), ``p_frio`` (frio ou queda brusca) e ``p_algum``.

ENSO (RONI da NOAA, baixado na hora): cada ano recebe a fase do trimestre centrado no mês do plantio; a fase
atual é a do último trimestre publicado (ou ``enso.fase_atual``). ``p_algum`` final = ``(n·p_enso + k·p_clim) /
(n + k)``, com ``n`` anos da mesma fase (``enso.p_final``). Sem o índice, fica a climatologia.

Score: ``score_t7 = 1 − p_algum`` (a conversão sugerida no README); as probabilidades seguem na saída.
"""
from __future__ import annotations

import logging
import warnings
from datetime import date, timedelta
from typing import Iterable

import numpy as np
import pandas as pd
import polars as pl

from towers.data.culturas import carregar_culturas, culturas_exibiveis
from towers.data.power import PARAMS_T1, clima_diario

from . import config as cfg_mod
from . import enso as enso_mod
from .probabilidade import probabilidade_bootstrap, semente_do_ponto
from .referencia import indicadores_diarios

log = logging.getLogger(__name__)

DESLOCAMENTOS_PADRAO = (-30, -20, -10, 0, 10, 20, 30)
CICLO_PADRAO = 120
CHUVA = ("chuva_dia", "chuva_persistente", "chuva_extrema")
FRIO = ("frio", "queda_brusca")
NOMES_EVENTOS = {"chuva_dia": "chuva forte", "chuva_persistente": "chuva persistente",
                 "chuva_extrema": "chuva extrema", "frio": "frio", "queda_brusca": "queda brusca de temperatura"}


def _ciclo(r: dict) -> int:
    lo, hi = r.get("ciclo_min"), r.get("ciclo_max")
    if lo and hi:
        return int(round((lo + hi) / 2))
    return int(lo or hi or CICLO_PADRAO)


def fases_da_cultura(id_cultura: str, ciclo: int, modo: str | None, uso: str | None, cfg) -> tuple[list[dict], dict]:
    """Fases com janelas em dias após o plantio e eventos (o ``frio`` já com o limiar), e os metadados."""
    cc = cfg.culturas
    propria = cc.por_cultura.get(id_cultura)
    fases = propria.fases if propria is not None else cc.padrao
    meta = {"fonte": (propria.fonte if propria is not None else "eventos gerais da T7 (sem limiar da cultura)"),
            "frio_tmin": propria.frio_tmin if propria is not None else None}
    perene = modo == "implantacao" or uso == "silvicultura"
    ciclo = max(int(ciclo), 40)
    saida = []
    for f in fases:
        if perene and f.nome != "estabelecimento":
            continue
        if f.dias is not None:
            ini, fim = int(f.dias[0]), int(f.dias[1])
        elif f.ciclo is not None:
            ini, fim = round(f.ciclo[0] * ciclo), round(f.ciclo[1] * ciclo)
        elif f.ultimos_dias is not None:
            ini, fim = ciclo - int(f.ultimos_dias), ciclo
        else:
            raise ValueError(f"fase {f.nome!r} sem janela (dias, ciclo ou ultimos_dias)")
        eventos = []
        for ev in f.eventos:
            if ev == "frio":
                if meta["frio_tmin"] is None:
                    raise ValueError(f"{id_cultura}: evento 'frio' sem frio_tmin")
                eventos.append(("frio", float(meta["frio_tmin"])))
            elif ev in NOMES_EVENTOS:
                eventos.append((ev, None))
            else:
                raise ValueError(f"{id_cultura}: evento desconhecido {ev!r}")
        saida.append({"nome": f.nome, "inicio": ini, "fim": fim, "eventos": tuple(eventos)})
    return saida, meta


class _Series:
    """Indicadores diários (1/0/NaN) da célula, com somas acumuladas para janelas em O(1)."""

    def __init__(self, serie: pd.DataFrame, cfg):
        self.cfg, self.n = cfg, len(serie)
        self.d0 = serie["data"].iloc[0].date()
        t7 = indicadores_diarios(serie, cfg)
        chuva, tmin = serie["PRECTOTCORR"], serie["T2M_MIN"]
        cd, cp = cfg.culturas.chuva_dia, cfg.culturas.chuva_persistente
        molhado = (chuva >= cp.chuva_minima_mm).astype(float).where(chuva.notna())
        self._ind = {
            ("chuva_extrema", None): t7["chuva_extrema"].to_numpy(float),
            ("queda_brusca", None): t7["queda_brusca"].to_numpy(float),
            ("chuva_dia", None): (chuva >= cd.valor).astype(float).where(chuva.notna()).to_numpy(float),
            ("chuva_persistente", None): molhado.rolling(cp.dias, min_periods=cp.dias).min().to_numpy(float),
        }
        self._tmin = tmin
        self._somas: dict = {}

    def somas(self, chave: tuple) -> tuple[np.ndarray, np.ndarray]:
        if chave not in self._somas:
            if chave[0] == "frio":
                ind = (self._tmin < chave[1]).astype(float).where(self._tmin.notna()).to_numpy(float)
            else:
                ind = self._ind[chave]
            nan = np.isnan(ind)
            self._somas[chave] = (np.concatenate([[0], np.cumsum(np.where(nan, 0, ind))]),
                                  np.concatenate([[0], np.cumsum(nan)]))
        return self._somas[chave]

    def houve(self, chave: tuple, a: int, z: int) -> float:
        """1/0 se houve o evento entre os dias a e z (índices), NaN se faltar dia."""
        if a < 0 or z >= self.n:
            return np.nan
        ev, nan = self.somas(chave)
        if nan[z + 1] - nan[a] > 0:
            return np.nan
        return 1.0 if ev[z + 1] - ev[a] > 0 else 0.0


def _fase_enso_por_ano(cfg, anos: list[int], plantios: list[date]) -> tuple[dict, dict]:
    """({plantio: [fase de cada ano]}, info da fase atual) pelo índice da NOAA; vazio se indisponível."""
    e = cfg.enso
    if not e.url:
        return {}, {"enso": "nao_calculado", "motivo": "enso.url vazio"}
    idx = enso_mod.ler_indice_noaa(e.url, cache_dias=e.cache_dias)
    if idx is None or idx.empty:
        return {}, {"enso": "nao_calculado", "motivo": "índice da NOAA indisponível"}
    valor = {(r.ano, r.mes_centro): r.anom for r in idx.itertuples()}
    ultimo = idx.iloc[-1]
    fases = {}
    for p in plantios:
        fases[p] = [enso_mod.fase_do_indice(valor.get((a, p.month)), e.limiar_el_nino, e.limiar_la_nina) for a in anos]
    atual_anom = valor.get((plantios[0].year, plantios[0].month), float(ultimo["anom"]))
    fase_atual = e.fase_atual or enso_mod.fase_do_indice(atual_anom, e.limiar_el_nino, e.limiar_la_nina)
    estacao = enso_mod.ESTACOES[int(ultimo["mes_centro"]) - 1]
    return fases, {"enso": fase_atual, "indice": e.indice, "anomalia": round(float(atual_anom), 2),
                   "referencia": f"{estacao} {int(ultimo['ano'])}" if (plantios[0].year, plantios[0].month)
                   not in valor else f"trimestre do plantio"}


def avaliar_t7(lat: float, lon: float, data_plantio: date,
               deslocamentos: Iterable[int] = DESLOCAMENTOS_PADRAO,
               culturas: pl.DataFrame | None = None, clima: pl.DataFrame | None = None, cfg=None,
               incluir_silvicultura: bool = True, colapsar_variantes: bool = True,
               usar_enso: bool = True) -> pl.DataFrame:
    """Probabilidades de extremos no ciclo e ``score_t7`` para cada cultura e data de plantio."""
    cfg = cfg or cfg_mod.carregar_config()
    if culturas is None:
        culturas = culturas_exibiveis(carregar_culturas(), incluir_silvicultura=incluir_silvicultura)
    if clima is None:
        clima = clima_diario(lat, lon, params=PARAMS_T1)
    serie = clima.select("data", "PRECTOTCORR", "T2M", "T2M_MIN").sort("data").to_pandas()
    serie.insert(0, "PONTO", "local")
    serie["data"] = pd.to_datetime(serie["data"])
    s = _Series(serie, cfg)
    anos = list(range(s.d0.year, serie["data"].iloc[-1].year + 1))
    plantios = [data_plantio + timedelta(days=d) for d in deslocamentos]

    # combinações únicas de (plantio, fases): culturas com as mesmas janelas compartilham o cálculo
    combos: dict[tuple, int] = {}
    por_cultura = []
    for r in culturas.iter_rows(named=True):
        fases, meta = fases_da_cultura(r["id_cultura"], _ciclo(r), r.get("modo"), r.get("uso"), cfg)
        k_fases = tuple((f["inicio"], f["fim"], f["eventos"]) for f in fases)
        for p in plantios:
            j = combos.setdefault((p, k_fases), len(combos))
            por_cultura.append((r["id_cultura"], p, j, fases, meta))

    mats = {g: np.full((len(anos), len(combos)), np.nan) for g in ("chuva", "frio", "algum")}
    for (p, k_fases), j in combos.items():
        for i, ano in enumerate(anos):
            try:
                p0 = p.replace(year=ano)
            except ValueError:          # 29/02
                p0 = date(ano, 2, 28)
            base = (p0 - s.d0).days
            vals: dict[str, list[float]] = {"chuva": [], "frio": []}
            for ini, fim, eventos in k_fases:
                for chave in eventos:
                    grupo = "chuva" if chave[0] in CHUVA else "frio"
                    vals[grupo].append(s.houve(chave, base + ini, base + fim))
            todos = vals["chuva"] + vals["frio"]
            if not todos or any(np.isnan(x) for x in todos):
                continue                 # ano incompleto sai de todos os grupos (mesmos anos nas três)
            for g in ("chuva", "frio"):
                if vals[g]:
                    mats[g][i, j] = max(vals[g])
            mats["algum"][i, j] = max(todos)

    b = cfg.bootstrap
    semente = semente_do_ponto(b.semente, f"{lat:.3f},{lon:.3f}")
    with warnings.catch_warnings():   # combinação sem nenhum ano com dado: p fica NaN (vira nulo), sem aviso
        warnings.simplefilter("ignore", RuntimeWarning)
        res = {g: probabilidade_bootstrap(m, b.repeticoes, semente, b.nivel_ic) for g, m in mats.items()}

    # ENSO: frequência nos anos da mesma fase, misturada com a climatologia
    fases_enso, info_enso = _fase_enso_por_ano(cfg, anos, plantios) if usar_enso else ({}, {"enso": "nao_calculado"})
    p_final, n_fase = {}, {}
    for (p, _), j in combos.items():
        p_clim = res["algum"]["p"][j]
        fase_atual = info_enso.get("enso")
        if p in fases_enso and fase_atual in enso_mod.FASES and not np.isnan(p_clim):
            col = mats["algum"][:, j]
            mask = np.array([f == fase_atual for f in fases_enso[p]]) & ~np.isnan(col)
            n = int(mask.sum())
            p_final[j] = enso_mod.p_final(float(col[mask].mean()) if n else np.nan, n, float(p_clim), cfg.enso.k)
            n_fase[j] = n
        else:
            p_final[j], n_fase[j] = float(p_clim), None

    saida = []
    for id_c, p, j, fases, meta in por_cultura:
        eventos = [f"{f['nome']} ({f['inicio']}–{f['fim']} dias): "
                   + ", ".join(NOMES_EVENTOS[c] + (f" < {lim:g} °C" if c == "frio" else "") for c, lim in f["eventos"])
                   for f in fases]
        saida.append({
            "id_cultura": id_c, "plantio": p,
            "p_chuva": float(res["chuva"]["p"][j]), "p_frio": float(res["frio"]["p"][j]),
            "p_algum_clim": float(res["algum"]["p"][j]), "p_algum": p_final[j],
            "p_algum_ic_inf": float(res["algum"]["ic_inf"][j]), "p_algum_ic_sup": float(res["algum"]["ic_sup"][j]),
            "n_anos_t7": int(res["algum"]["n_anos"][j]), "n_anos_fase_enso": n_fase[j],
            "eventos_t7": eventos, "fonte_t7": meta["fonte"],
        })
    floats = ("p_chuva", "p_frio", "p_algum_clim", "p_algum", "p_algum_ic_inf", "p_algum_ic_sup")
    df = pl.DataFrame(saida, schema_overrides={c: pl.Float64 for c in floats} | {"n_anos_fase_enso": pl.Int64})
    df = df.with_columns([pl.col(c).fill_nan(None) for c in floats]).with_columns(
        score_t7=(1 - pl.col("p_algum")).cast(pl.Float64),
        enso_fase=pl.lit(info_enso.get("enso"), pl.String),
        enso_anomalia=pl.lit(info_enso.get("anomalia"), pl.Float64),
        enso_referencia=pl.lit(info_enso.get("referencia"), pl.String),
    ).join(culturas.select("id_cultura", "nome_pt", "uso", "modo", "obrigatoria", "escala_cultivo"), on="id_cultura")

    ordenar = dict(by=["score_t7", "escala_cultivo", "nome_pt", "plantio"], descending=[True, False, False, False],
                   nulls_last=True)
    df = df.sort(**ordenar).with_columns(n_variantes=pl.len().over("nome_pt", "plantio"))
    if colapsar_variantes:
        df = df.group_by("nome_pt", "plantio", maintain_order=True).first()
    log.info("T7: %d culturas × %d datas; %d combinações de fases; anos %d–%d; ENSO %s", culturas.height,
             len(plantios), len(combos), anos[0], anos[-1], info_enso)
    ordem = ["id_cultura", "nome_pt", "uso", "modo", "plantio", "score_t7", "p_algum", "p_algum_clim",
             "p_algum_ic_inf", "p_algum_ic_sup", "p_chuva", "p_frio", "n_anos_t7", "enso_fase", "enso_anomalia",
             "enso_referencia", "n_anos_fase_enso", "eventos_t7", "fonte_t7", "n_variantes", "obrigatoria",
             "escala_cultivo"]
    return df.select(ordem).sort(**ordenar)
