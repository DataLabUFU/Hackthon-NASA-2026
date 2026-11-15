"""Recomendador: roda as seis torres, combina os scores e devolve os setores.

    from towers.combinador import recomendar
    rec = recomendar(lat=-23.3, lon=-51.2, data_plantio=date(2026, 11, 20), cultura_desejada="Soja",
                     ultimo="Soja", penultimo="Milho", objetivo="equilibrado")
    rec.setores["melhores"], rec.desejada, rec.ranking

Cada torre roda de forma independente (mesmo catálogo de culturas). O resultado traz o ranking completo,
os três setores (``top_n`` culturas cada, padrão 3) e a posição da cultura desejada.
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from dataclasses import dataclass, field
from datetime import date, timedelta

import polars as pl

from towers.data.culturas import carregar_culturas, culturas_exibiveis
from towers.data.municipios import municipio_mais_proximo
from towers.data.power import PARAMS_T2, clima_diario
from towers.data.zarc import solo_local
from towers.t2_hidrica.torre import AD_PADRAO
from towers.t1_aptidao import avaliar_t1
from towers.t2_hidrica import avaliar_t2
from towers.t3_solo import avaliar_t3
from towers.t4_zarc import avaliar_t4
from towers.t5_rotacao import avaliar_t5
from towers.t5_rotacao.torre import resolver_cultura
from towers.t6_elegibilidade import avaliar_t6

from .combinador import combinar
from .ordenador import localizar, ordenar, setores
from .pesos import OBJETIVOS

log = logging.getLogger(__name__)

TOP_N_PADRAO = 3
TIMEOUT_TORRE_S = 30.0
DESLOCAMENTOS_PADRAO = (-30, -20, -10, 0, 10, 20, 30)   # o mesmo das torres


def base_sem_t1(culturas: pl.DataFrame, plantios: list[date]) -> pl.DataFrame:
    """Candidatos (cultura × data) quando a T1 não responde: clima neutro, ninguém eliminado pelo clima."""
    return culturas.select(
        "id_cultura", "nome_pt", "uso", "modo", "colheita", "obrigatoria", "escala_cultivo",
        *[c for c in ("tipo_cultura", "fonte_parametros") if c in culturas.columns],
    ).join(pl.DataFrame({"plantio": plantios}), how="cross").with_columns(
        score_t1=pl.lit(None, pl.Float64), apt_p20=pl.lit(None, pl.Float64), gate_t1=pl.lit(True),
        fator_limitante=pl.lit(None, pl.String), ciclo_dias=pl.lit(None, pl.Int64),
        alerta_foto_mensagem=pl.lit(None, pl.String), alerta_ciclo_extremo=pl.lit(False),
    )


@dataclass
class Recomendacao:
    ranking: pl.DataFrame
    setores: dict[str, pl.DataFrame]
    desejada: dict | None
    objetivo: str
    entrada: dict
    tempos_s: dict[str, float] = field(default_factory=dict)
    candidatos: pl.DataFrame | None = None   # todas as (cultura × data) combinadas, antes de escolher a melhor data
    torres: dict[str, pl.DataFrame] = field(default_factory=dict)   # saída bruta de cada torre (detalhes na interface)
    torres_ausentes: dict[str, str] = field(default_factory=dict)    # torre -> motivo (timeout/erro), fora da nota


def recomendar(lat: float, lon: float, data_plantio: date, cultura_desejada: str | None = None,
               ultimo: str | None = None, penultimo: str | None = None,
               problemas_solo: tuple[str, ...] | list[str] = (), analise_solo: dict | None = None,
               imovel: dict | None = None, objetivo: str = "equilibrado", irrigado: bool = False,
               somente_financiaveis: bool | None = None, incluir_silvicultura: bool = True,
               top_n: int = TOP_N_PADRAO, geocodigo: str | None = None, tipos_cultura: list[str] | None = None,
               peso_evidencia: float | None = None, pesos: dict[str, float] | None = None,
               universo_piores: pl.Expr | None = None,
               extras: dict[str, tuple[pl.DataFrame, float]] | None = None,
               timeout_torre_s: float = TIMEOUT_TORRE_S) -> Recomendacao:
    """``tipos_cultura``: o que o produtor considera plantar (chaves de ``TIPOS_CULTURA``); None = todos.
    A cultura desejada é sempre avaliada, mesmo fora dos tipos escolhidos.
    ``timeout_torre_s``: prazo de cada torre; a que não responder fica fora da nota (``torres_ausentes``)."""
    if objetivo not in OBJETIVOS:
        raise ValueError(f"objetivo desconhecido: {objetivo!r} (válidos: {sorted(OBJETIVOS)})")
    tempos: dict[str, float] = {}
    t0 = time.perf_counter()
    catalogo = carregar_culturas()
    tempos["catalogo"] = round(time.perf_counter() - t0, 2)
    desejada_nome = resolver_cultura(cultura_desejada, catalogo.filter("exibivel"))["nome_pt"] if cultura_desejada else None
    culturas = culturas_exibiveis(catalogo, incluir_silvicultura=incluir_silvicultura, tipos=tipos_cultura)
    if desejada_nome and desejada_nome not in culturas["nome_pt"].to_list():
        culturas = pl.concat([culturas, catalogo.filter(pl.col("exibivel") & (pl.col("nome_pt") == desejada_nome))])
    geocodigo = geocodigo or municipio_mais_proximo(lat, lon)["geocodigo"]
    comum = dict(culturas=culturas, colapsar_variantes=False)
    plantios = [data_plantio + timedelta(days=d) for d in DESLOCAMENTOS_PADRAO]

    # As torres rodam em paralelo, cada uma com prazo de ``timeout_torre_s``. Quem não responde (ou falha)
    # fica fora da nota (neutra no combinador). O clima da POWER, usado por T1 e T2, conta no prazo delas.
    executor = ThreadPoolExecutor(max_workers=7, thread_name_prefix="torre")
    f_clima = executor.submit(clima_diario, lat, lon, params=PARAMS_T2)
    # solo (SoilGrids → classe AD do ZARC) buscado uma vez para T2, T4 e T6; sem resposta, cada uma usa
    # o seu padrão (T2: AD4; T4/T6: melhor solo do ZARC) e continua contribuindo com a nota
    f_solo = executor.submit(solo_local, lat, lon)

    def solo_compartilhado() -> dict:
        try:
            return f_solo.result() or {}
        except Exception:
            return {}

    tarefas = {
        "t1": lambda: avaliar_t1(lat, lon, data_plantio, clima=f_clima.result(), geocodigo=geocodigo,
                                 irrigado=irrigado, **comum),
        "t2": lambda: avaliar_t2(lat, lon, data_plantio, clima=f_clima.result(), irrigado=irrigado,
                                 solo=solo_compartilhado() or dict(AD_PADRAO), **comum),
        "t3": lambda: avaliar_t3(lat, lon, problemas_solo=problemas_solo, analise=analise_solo, **comum),
        "t4": lambda: avaliar_t4(lat, lon, data_plantio, geocodigo=geocodigo, irrigado=irrigado,
                                 solo=solo_compartilhado(), **comum),
        "t5": lambda: avaliar_t5(ultimo, penultimo, catalogo_historico=catalogo.filter("exibivel"), **comum),
        "t6": lambda: avaliar_t6(lat, lon, data_plantio, geocodigo=geocodigo, imovel=imovel, irrigado=irrigado,
                                 solo=solo_compartilhado(), **comum),
    }
    inicio = time.perf_counter()
    futuros = {nome: executor.submit(f) for nome, f in tarefas.items()}
    saidas: dict[str, pl.DataFrame | None] = {}
    ausentes: dict[str, str] = {}
    for nome, fut in futuros.items():
        restante = max(0.0, timeout_torre_s - (time.perf_counter() - inicio))
        try:
            saidas[nome] = fut.result(timeout=restante)
            tempos[nome] = round(time.perf_counter() - inicio, 2)
        except FuturesTimeout:
            saidas[nome], ausentes[nome] = None, f"não respondeu em {timeout_torre_s:.0f} s"
            log.warning("Torre %s: sem resposta em %.0f s; fica fora da nota", nome, timeout_torre_s)
        except Exception as e:  # erro de rede/API/dados: a torre não contribui, o resto segue
            saidas[nome], ausentes[nome] = None, f"erro: {e}"
            log.warning("Torre %s falhou (%s); fica fora da nota", nome, e)
    executor.shutdown(wait=False, cancel_futures=True)   # torres atrasadas seguem em segundo plano, ignoradas

    t1 = saidas["t1"] if saidas["t1"] is not None else base_sem_t1(culturas, plantios)
    t2, t3, t4, t5, t6 = (saidas[n] for n in ("t2", "t3", "t4", "t5", "t6"))

    kw = {} if peso_evidencia is None else {"peso_evidencia": peso_evidencia}
    comb = combinar(t1, t2, t3, t4, t5, t6, objetivo=objetivo, somente_financiaveis=somente_financiaveis,
                    extras=extras, pesos=pesos, **kw)
    ranking = ordenar(comb)
    sets = setores(ranking, top_n=top_n, universo_piores=universo_piores)
    desejada = localizar(ranking, desejada_nome, sets) if desejada_nome else None
    entrada = dict(lat=lat, lon=lon, geocodigo=geocodigo, data_plantio=data_plantio, cultura_desejada=desejada_nome,
                   ultimo=ultimo, penultimo=penultimo, problemas_solo=list(problemas_solo), objetivo=objetivo,
                   irrigado=irrigado, top_n=top_n, tipos_cultura=tipos_cultura)
    log.info("Recomendação: %d culturas ranqueadas; tempos %s; fora da nota: %s", ranking.height, tempos, ausentes)
    return Recomendacao(ranking, sets, desejada, objetivo, entrada, tempos, comb,
                        {n: v for n, v in saidas.items() if v is not None}, ausentes)
