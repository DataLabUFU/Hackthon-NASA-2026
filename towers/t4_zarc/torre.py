"""Torre 4: zoneamento oficial (ZARC/MAPA).

    avaliar_t4(lat, lon, data_plantio) → uma linha por (cultura × data de plantio candidata)

Pergunta: o zoneamento oficial indica esta cultura, neste município, nesta data, neste solo?

- Município: o geocódigo informado ou o de sede mais próxima da coordenada.
- Solo: a T4 estima sozinha a classe do local (SoilGrids → PTF do ZARC/Embrapa → classe AD 11–16; e o
  tipo antigo 1/2/3 pela argila: < 15% = 1, 15–35% = 2, ≥ 35% = 3). Também informa o resultado no
  melhor solo, como referência.
- Ciclo, clima e manejo do ZARC: vale a melhor combinação (o produtor escolhe a cultivar).
- Irrigado: só linhas de sequeiro, a menos que ``irrigado`` = True (aí vale a melhor entre as duas).

Score: a melhor classe do ZARC (risco ≤ 20%) vale 1,0; 30% → 0,85; 40% → 0,7; não indicado → 0;
(1 − risco penalizaria toda cultura zoneada, mesmo na melhor classe, frente às culturas sem zoneamento,
que ficam neutras no combinador);
sem zoneamento para a cultura no município → nulo (o combinador trata como neutro).
A ``portaria`` vem junto: é a referência que o crédito rural e o Proagro exigem.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Iterable

import polars as pl

from towers.data.culturas import carregar_culturas, culturas_exibiveis
from towers.data.municipios import municipio_mais_proximo
from towers.data.zarc import CAMINHO_PADRAO, codigos_solo, decendio, solo_local as solo_do_local, tabua  # noqa: F401

log = logging.getLogger(__name__)

DESLOCAMENTOS_PADRAO = (-30, -20, -10, 0, 10, 20, 30)
SCORE_POR_RISCO = {20: 1.0, 30: 0.85, 40: 0.70}


def _melhor(df: pl.DataFrame) -> dict:
    """Melhor combinação (menor risco indicado) de um conjunto de linhas do ZARC já filtradas por decêndio."""
    ind = df.filter(pl.col("risco") > 0).sort("risco")
    if ind.is_empty():
        return {"indicado": False, "risco": None, "ciclo": None}
    r = ind.row(0, named=True)
    return {"indicado": True, "risco": int(r["risco"]), "ciclo": r["Cod_Ciclo"]}


def avaliar_t4(lat: float, lon: float, data_plantio: date,
               deslocamentos: Iterable[int] = DESLOCAMENTOS_PADRAO,
               culturas: pl.DataFrame | None = None, geocodigo: str | None = None, solo: dict | None = None,
               irrigado: bool = False, caminho_zarc=CAMINHO_PADRAO,
               incluir_silvicultura: bool = True, colapsar_variantes: bool = True) -> pl.DataFrame:
    if culturas is None:
        culturas = culturas_exibiveis(carregar_culturas(), incluir_silvicultura=incluir_silvicultura)
    if geocodigo is None:
        m = municipio_mais_proximo(lat, lon)
        geocodigo, nome_mun = m["geocodigo"], f"{m['nome']}-{m['uf']}"
    else:
        nome_mun = None
    if solo is None:
        solo = solo_do_local(lat, lon)
    cods = codigos_solo(solo)
    plantios = [data_plantio + timedelta(days=d) for d in deslocamentos]

    linhas_zarc = tabua([geocodigo], caminho_zarc, incluir_irrigado=irrigado).collect()
    if nome_mun is None and linhas_zarc.height:
        nome_mun = f"{linhas_zarc['municipio'][0]}-{linhas_zarc['UF'][0]}"
    zoneadas = set(linhas_zarc["id_cultura"].unique().to_list())

    saida = []
    for id_c in culturas["id_cultura"].to_list():
        z = linhas_zarc.filter(pl.col("id_cultura") == id_c)
        for p in plantios:
            dec = decendio(p)
            base = {"id_cultura": id_c, "plantio": p, "decendio": dec}
            if id_c not in zoneadas:
                saida.append(base | {"zarc_status": "sem_zoneamento"})
                continue
            zd = z.select("Cod_Solo", "Cod_Ciclo", "Portaria", "SafraIni", pl.col(f"dec{dec}").alias("risco"))
            no_solo = zd.filter(pl.col("Cod_Solo").is_in(list(cods))) if cods else zd.clear()
            melhor_geral = _melhor(zd)
            if no_solo.height:
                m, solo_usado, solo_cod = _melhor(no_solo), "local", ",".join(sorted(set(no_solo["Cod_Solo"])))
            else:   # solo desconhecido ou sistema de classes sem correspondência: usa o melhor solo
                m, solo_usado, solo_cod = melhor_geral, "melhor_solo", None
            saida.append(base | {
                "zarc_status": "indicado" if m["indicado"] else "nao_indicado",
                "risco_pct": m["risco"], "ciclo_zarc": m["ciclo"], "solo_zarc": solo_cod, "solo_usado": solo_usado,
                "risco_melhor_solo": melhor_geral["risco"], "indicado_melhor_solo": melhor_geral["indicado"],
                "portaria": zd["Portaria"][0], "safra_zarc": f"{zd['SafraIni'][0]}/{zd['SafraIni'][0] + 1}",
            })

    schema = {"id_cultura": pl.String, "plantio": pl.Date, "decendio": pl.Int8, "zarc_status": pl.String,
              "risco_pct": pl.Int64, "ciclo_zarc": pl.String, "solo_zarc": pl.String, "solo_usado": pl.String,
              "risco_melhor_solo": pl.Int64, "indicado_melhor_solo": pl.Boolean, "portaria": pl.String,
              "safra_zarc": pl.String}
    res = pl.DataFrame(saida, schema=schema).with_columns(
        score_t4=pl.when(pl.col("zarc_status") == "indicado")
        .then(pl.col("risco_pct").replace_strict(SCORE_POR_RISCO, default=None, return_dtype=pl.Float64))
        .when(pl.col("zarc_status") == "nao_indicado").then(0.0),
        geocodigo=pl.lit(geocodigo), municipio_zarc=pl.lit(nome_mun),
        classe_ad_local=pl.lit(solo.get("classe_ad") if solo else None),
    ).join(culturas.select("id_cultura", "nome_pt", "uso", "modo", "obrigatoria", "escala_cultivo"), on="id_cultura")

    ordenar = dict(by=["score_t4", "escala_cultivo", "nome_pt", "plantio"],
                   descending=[True, False, False, False], nulls_last=True)
    res = res.sort(**ordenar).with_columns(n_variantes=pl.len().over("nome_pt", "plantio"))
    if colapsar_variantes:
        res = res.group_by("nome_pt", "plantio", maintain_order=True).first()
    ordem = ["id_cultura", "nome_pt", "uso", "modo", "plantio", "decendio", "score_t4", "zarc_status", "risco_pct",
             "ciclo_zarc", "solo_zarc", "solo_usado", "classe_ad_local", "risco_melhor_solo", "indicado_melhor_solo",
             "portaria", "safra_zarc", "geocodigo", "municipio_zarc", "n_variantes", "obrigatoria", "escala_cultivo"]
    res = res.select(ordem).sort(**ordenar)
    log.info("T4: %s (%s), solo %s; %d culturas zoneadas no município", nome_mun, geocodigo,
             solo.get("classe_ad") if solo else "desconhecido", len(zoneadas))
    return res
