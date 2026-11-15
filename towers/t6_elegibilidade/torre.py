"""Torre 6: elegibilidade a crédito de custeio, Proagro e seguro rural (PSR).

    avaliar_t6(lat, lon, data_plantio, imovel={...}) → uma linha por (cultura × data de plantio)

Não é qualidade agronômica: é **restrição**. Por isso não entra na média do combinador; vira filtro
("só opções financiáveis") e selo. Independente das outras torres: consulta o ZARC e o solo pelos
clientes de dados.

Status por candidato:
- ``elegivel``: ZARC indica a cultura no município, data e solo; sem impedimento socioambiental conhecido;
- ``condicional``: elegível dependendo de condição (ex.: embargo com CAR ativo, até 2027);
- ``inelegivel``: fora da janela do ZARC, ou impedimento socioambiental;
- ``a_verificar``: cultura sem ZARC no município (outro zoneamento), perenes/silvicultura (crédito de
  investimento) ou falta de dado.

``imovel`` (opcional, informado pelo produtor): {"car": "ativo|pendente|cancelado|suspenso|inexistente",
"embargo_ibama": bool, "terra_indigena": bool, "unidade_conservacao": bool}.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Iterable

import polars as pl

from towers.data.culturas import carregar_culturas, culturas_exibiveis
from towers.data.municipios import municipio_mais_proximo
from towers.data.zarc import CAMINHO_PADRAO, codigos_solo, decendio, solo_local, tabua

from .regras import AVISO_GERAL, AVISO_RNC, AVISO_SOCIOAMBIENTAL, FONTES, SITUACOES_CAR, VIGENCIA

log = logging.getLogger(__name__)

DESLOCAMENTOS_PADRAO = (-30, -20, -10, 0, 10, 20, 30)
SCORE = {"elegivel": 1.0, "condicional": 0.5, "a_verificar": None, "inelegivel": 0.0}


def impedimentos_socioambientais(imovel: dict | None) -> tuple[str | None, list[str], list[str]]:
    """(status, motivos, avisos) do imóvel. Status None = sem impedimento conhecido."""
    if not imovel:
        return None, [], [AVISO_SOCIOAMBIENTAL]
    car = imovel.get("car")
    if car is not None and car not in SITUACOES_CAR:
        raise ValueError(f"situação do CAR inválida: {car!r} (válidas: {sorted(SITUACOES_CAR)})")
    motivos, avisos = [], []
    if car in ("cancelado", "suspenso", "inexistente"):
        motivos.append(f"CAR {car}: {FONTES['car']}")
    if imovel.get("terra_indigena"):
        motivos.append(f"imóvel em terra indígena: {FONTES['terra_indigena']}")
    if motivos:
        return "inelegivel", motivos, avisos
    if imovel.get("embargo_ibama"):
        if car == "ativo":
            return "condicional", [f"área embargada: {FONTES['embargo']}"], avisos
        return "inelegivel", [f"área embargada sem CAR ativo: {FONTES['embargo']}"], avisos
    if imovel.get("unidade_conservacao"):
        avisos.append(f"sobreposição com unidade de conservação: {FONTES['uc']}")
    if car is None:
        avisos.append(AVISO_SOCIOAMBIENTAL)
    return None, [], avisos


def avaliar_t6(lat: float, lon: float, data_plantio: date,
               deslocamentos: Iterable[int] = DESLOCAMENTOS_PADRAO,
               culturas: pl.DataFrame | None = None, geocodigo: str | None = None, solo: dict | None = None,
               imovel: dict | None = None, irrigado: bool = False, caminho_zarc=CAMINHO_PADRAO,
               incluir_silvicultura: bool = True, colapsar_variantes: bool = True) -> pl.DataFrame:
    if culturas is None:
        culturas = culturas_exibiveis(carregar_culturas(), incluir_silvicultura=incluir_silvicultura)
    if geocodigo is None:
        geocodigo = municipio_mais_proximo(lat, lon)["geocodigo"]
    if solo is None:
        solo = solo_local(lat, lon)
    cods = codigos_solo(solo)
    plantios = [data_plantio + timedelta(days=d) for d in deslocamentos]
    status_imovel, motivos_imovel, avisos_imovel = impedimentos_socioambientais(imovel)

    zarc = tabua([geocodigo], caminho_zarc, incluir_irrigado=irrigado).collect()
    zoneadas = set(zarc["id_cultura"].unique().to_list())

    linhas = []
    for r in culturas.select("id_cultura", "modo", "uso").iter_rows(named=True):
        z = zarc.filter(pl.col("id_cultura") == r["id_cultura"])
        for p in plantios:
            dec = decendio(p)
            motivos, avisos, portaria = list(motivos_imovel), [AVISO_GERAL, *avisos_imovel], None
            proagro = psr = None
            if r["modo"] == "implantacao" or r["uso"] == "silvicultura":
                status = "a_verificar"
                motivos.append(FONTES["investimento"])
            elif r["id_cultura"] not in zoneadas:
                status = "a_verificar"
                proagro = psr = False
                motivos.append(f"cultura sem ZARC no município: {FONTES['sem_zarc']}; Proagro e PSR indisponíveis")
            else:
                zd = z.select("Cod_Solo", "Portaria", pl.col(f"dec{dec}").alias("risco"))
                portaria = zd["Portaria"][0]
                no_solo = zd.filter(pl.col("Cod_Solo").is_in(list(cods))) if cods else zd
                indicado = bool((no_solo["risco"] > 0).any()) if no_solo.height else bool((zd["risco"] > 0).any())
                if not cods:
                    avisos.append("solo do local não identificado: considerado o melhor solo do ZARC")
                if indicado:
                    status, proagro, psr = "elegivel", True, True
                    avisos.append(AVISO_RNC)
                else:
                    status, proagro, psr = "inelegivel", False, False
                    motivos.append(f"plantio fora da janela do ZARC ({portaria}): {FONTES['zarc_custeio']}")
            # impedimentos do imóvel prevalecem
            if status_imovel == "inelegivel":
                status, proagro, psr = "inelegivel", False, False
            elif status_imovel == "condicional" and status == "elegivel":
                status = "condicional"
            linhas.append({
                "id_cultura": r["id_cultura"], "plantio": p, "decendio": dec, "status_elegibilidade": status,
                "elegivel_credito_custeio": {"elegivel": True, "condicional": True, "inelegivel": False}.get(status),
                "elegivel_proagro": proagro, "elegivel_psr": psr, "motivos": motivos, "avisos": avisos,
                "portaria_zarc": portaria,
            })

    res = pl.DataFrame(linhas, schema_overrides={"elegivel_credito_custeio": pl.Boolean, "elegivel_proagro": pl.Boolean,
                                                 "elegivel_psr": pl.Boolean, "portaria_zarc": pl.String}).with_columns(
        score_t6=pl.col("status_elegibilidade").replace_strict(SCORE, return_dtype=pl.Float64),
        financiavel=pl.col("status_elegibilidade").is_in(["elegivel", "condicional"]),
        geocodigo=pl.lit(geocodigo), vigencia_regras=pl.lit(VIGENCIA),
    ).join(culturas.select("id_cultura", "nome_pt", "uso", "modo", "obrigatoria", "escala_cultivo"), on="id_cultura")

    ordenar = dict(by=["score_t6", "escala_cultivo", "nome_pt", "plantio"],
                   descending=[True, False, False, False], nulls_last=True)
    res = res.sort(**ordenar).with_columns(n_variantes=pl.len().over("nome_pt", "plantio"))
    if colapsar_variantes:
        res = res.group_by("nome_pt", "plantio", maintain_order=True).first()
    ordem = ["id_cultura", "nome_pt", "uso", "modo", "plantio", "decendio", "score_t6", "status_elegibilidade",
             "financiavel", "elegivel_credito_custeio", "elegivel_proagro", "elegivel_psr", "motivos", "avisos",
             "portaria_zarc", "geocodigo", "vigencia_regras", "n_variantes", "obrigatoria", "escala_cultivo"]
    return res.select(ordem).sort(**ordenar)
