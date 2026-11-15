"""Componente 5: aptidão climática por ano, agregação entre anos e alertas.

Aptidão de uma cultura em um ano (modelo Ecocrop, lei do fator limitante):

    s_temp  = min(trap(t_mes_frio), trap(t_mes_quente))         TMIN/TOPMN/TOPMX/TMAX
    s_chuva = trap(chuva, RMIN, ROPMN, ROPMX, RMAX)              1,0 se irrigado ou sem dado
    s_peg   = min(trap(t_pegamento), chuva_pegamento / chuva_ideal_90d)    só modo implantação
    letal   = tmin_inicial ≤ KTMP + margem   ou   tmin_resto ≤ (KTMPR ou, sem ele, KTMP) + margem
              ou (safra, colheita reprodutiva) tmin_floracao ≤ KTMP + margem
              (KTMP = letal na fase inicial; KTMPR = letal na planta estabelecida/dormente;
               na floração/enchimento o grão/fruto volta a ser sensível como a planta jovem)
    aptidao = min(s_temp, s_chuva[, s_peg]) × (0 se letal)

Agregação entre anos com peso de recência ``w = 0,5^((ano_ref − ano) / meia_vida)``:
média, P20, ``prob_apta`` (aptidão ≥ 0,5) e ``prob_letal``, todos ponderados.
"""
from __future__ import annotations

import numpy as np
import polars as pl

from towers.utils.astronomia import comprimento_dia, dia_do_ano

from .janelas import DIAS_ANO, DIAS_PEGAMENTO

MEIA_VIDA_PADRAO = 10.0
MARGEM_GEADA_PADRAO = 1.0   # calibrado contra o ZARC (ver calibracao.py): melhor acurácia balanceada
LIMIAR_APTA = 0.5
QUANTIL_ESTABILIDADE = 0.2

# Fotoperíodo (classes ECOCROP): curto < 12 h | neutro 12–14 h | longo > 14 h
LIMITE_CURTO, LIMITE_LONGO = 12.0, 14.0
TOLERANCIA_FOTO_H = 0.5
FASE_INDUTIVA = (0.2, 0.5)  # fração do ciclo em que a planta "lê" o fotoperíodo


def trapezio(x: pl.Expr, amin: pl.Expr, omin: pl.Expr, omax: pl.Expr, amax: pl.Expr) -> pl.Expr:
    """0 fora de [amin, amax]; 1 dentro de [omin, omax]; linear nas rampas."""
    return (
        pl.when((x <= amin) | (x >= amax)).then(0.0)
        .when(x < omin).then((x - amin) / (omin - amin))
        .when(x > omax).then((amax - x) / (amax - omax))
        .otherwise(1.0)
    )


def _param(c: str) -> pl.Expr:
    return pl.col(c).cast(pl.Float64)


def aptidao_por_ano(janelas: pl.DataFrame, safra: pl.DataFrame, implantacao: pl.DataFrame,
                    irrigado: bool = False, modo_chuva: str = "ciclo",
                    margem_geada: float = MARGEM_GEADA_PADRAO) -> pl.DataFrame:
    """Uma linha por (cultura × plantio × ciclo × ano).

    ``safra``: culturas em modo safra já expandidas por ciclo (``expandir_ciclos``).
    ``implantacao``: culturas perenes (avaliadas na janela de 365 dias).
    """
    if modo_chuva not in ("ciclo", "anual"):
        raise ValueError("modo_chuva deve ser 'ciclo' ou 'anual'")

    a = safra.join(janelas, on="ciclo_dias", how="inner").with_columns(
        chuva_avaliada=pl.col("chuva_365") if modo_chuva == "anual" else pl.col("chuva"),
        s_pegamento=pl.lit(1.0),
    )
    b = implantacao.join(janelas.filter(pl.col("ciclo_dias") == DIAS_ANO), how="cross").with_columns(
        chuva_avaliada=pl.col("chuva"),
    )
    # Pegamento: temperatura dos 90 dias iniciais no trapézio e chuva relativa ao mínimo ótimo proporcional.
    chuva_ideal_90 = _param("ROPMN") * DIAS_PEGAMENTO / DIAS_ANO
    peg_chuva = (
        pl.lit(1.0) if irrigado else
        pl.when(pl.col("chuva_conhecida")).then((pl.col("chuva_pegamento") / chuva_ideal_90).clip(0.0, 1.0))
        .otherwise(1.0)
    )
    b = b.with_columns(
        s_pegamento=pl.min_horizontal(
            trapezio(pl.col("t_pegamento"), _param("TMIN"), _param("TOPMN"), _param("TOPMX"), _param("TMAX")),
            peg_chuva,
        ),
    )
    df = pl.concat([a, b], how="diagonal_relaxed")

    s_chuva = (
        pl.lit(1.0) if irrigado else
        pl.when(pl.col("chuva_conhecida") & pl.col("chuva_avaliada").is_not_null())
        .then(trapezio(pl.col("chuva_avaliada"), _param("RMIN"), _param("ROPMN"), _param("ROPMX"), _param("RMAX")))
        .otherwise(1.0)
    )
    return df.with_columns(
        s_temp=pl.min_horizontal(
            trapezio(pl.col("t_mes_frio"), _param("TMIN"), _param("TOPMN"), _param("TOPMX"), _param("TMAX")),
            trapezio(pl.col("t_mes_quente"), _param("TMIN"), _param("TOPMN"), _param("TOPMX"), _param("TMAX")),
        ),
        s_chuva=s_chuva,
        letal=(
            (pl.col("tmin_inicial") <= _param("KTMP") + margem_geada)
            | (pl.col("tmin_resto") <= pl.coalesce(_param("KTMPR"), _param("KTMP")) + margem_geada).fill_null(False)
            # floração/enchimento de culturas colhidas pelo grão/fruto (modo safra): volta a valer o KTMP
            | ((pl.col("modo") == "safra") & (pl.col("colheita") == "reprodutiva")
               & (pl.col("tmin_floracao") <= _param("KTMP") + margem_geada)).fill_null(False)
        ),
    ).with_columns(
        aptidao=pl.when(pl.col("letal")).then(0.0)
        .otherwise(pl.min_horizontal("s_temp", "s_chuva", "s_pegamento")),
    )


def agregar_anos(apt: pl.DataFrame, ano_referencia: int, meia_vida: float = MEIA_VIDA_PADRAO,
                 chaves: tuple[str, ...] = ("id_cultura", "plantio", "ciclo_dias")) -> pl.DataFrame:
    """Resumo ponderado pela recência de cada (cultura × plantio × ciclo)."""
    w = pl.col("_w")
    tot = w.sum()
    ordem = pl.col("aptidao").arg_sort()
    return (
        apt.with_columns(_w=pl.lit(0.5) ** ((ano_referencia - pl.col("ano")) / meia_vida))
        .group_by(list(chaves))
        .agg(
            apt_media=(w * pl.col("aptidao")).sum() / tot,
            apt_p20=pl.col("aptidao").gather(ordem).filter(
                (w.gather(ordem).cum_sum() / tot) >= QUANTIL_ESTABILIDADE).first(),
            prob_apta=(w * (pl.col("aptidao") >= LIMIAR_APTA)).sum() / tot,
            prob_letal=(w * pl.col("letal")).sum() / tot,
            s_temp_med=(w * pl.col("s_temp")).sum() / tot,
            s_chuva_med=(w * pl.col("s_chuva")).sum() / tot,
            s_pegamento_med=(w * pl.col("s_pegamento")).sum() / tot,
            n_anos=pl.len(),
            n_anos_efetivos=tot ** 2 / (w ** 2).sum(),
        )
    )


def melhor_ciclo(agg: pl.DataFrame, ciclos: pl.DataFrame) -> pl.DataFrame:
    """Por (cultura × plantio): o ciclo de maior aptidão média, o score no ciclo típico e o alerta
    de ciclo extremo (melhor ciclo no quarto inferior/superior da faixa da espécie).

    ``ciclos``: (id_cultura, ciclo_dias, ciclo_tipico, ciclo_min, ciclo_max) das culturas em modo safra.
    """
    df = agg.join(ciclos, on=["id_cultura", "ciclo_dias"], how="left")
    tipico = df.filter(pl.col("ciclo_tipico").fill_null(False)).select(
        "id_cultura", "plantio", score_t1_tipico=pl.col("apt_media"))
    melhor = (
        df.sort(["apt_media", "ciclo_tipico", "ciclo_dias"], descending=[True, True, False], nulls_last=True)
        .group_by(["id_cultura", "plantio"], maintain_order=True).first()
    )
    faixa = pl.col("ciclo_max") - pl.col("ciclo_min")
    return melhor.join(tipico, on=["id_cultura", "plantio"], how="left").with_columns(
        score_t1_tipico=pl.coalesce("score_t1_tipico", "apt_media"),
        alerta_ciclo_extremo=(
            pl.col("ciclo_min").is_not_null() & (faixa > 0)
            & ((pl.col("ciclo_dias") < pl.col("ciclo_min") + 0.25 * faixa)
               | (pl.col("ciclo_dias") > pl.col("ciclo_max") - 0.25 * faixa))
        ).fill_null(False),
    ).drop("ciclo_tipico", "ciclo_min", "ciclo_max")


# --- fotoperíodo -------------------------------------------------------------------------------

def faixa_aceita(curto: bool, neutro: bool, longo: bool, tol: float = TOLERANCIA_FOTO_H) -> tuple[float, float]:
    """Faixa de horas de luz aceita pela espécie (com tolerância nas bordas)."""
    inferior = 0.0 if curto else (LIMITE_CURTO if neutro else LIMITE_LONGO)
    superior = float("inf") if longo else (LIMITE_LONGO if neutro else LIMITE_CURTO)
    return inferior - tol, superior + tol


def dia_fase_indutiva(lat: float, plantio, ciclo_dias: int) -> float:
    """Comprimento médio do dia (h) entre 20% e 50% do ciclo."""
    j0 = dia_do_ano(plantio)
    dias = np.arange(int(ciclo_dias * FASE_INDUTIVA[0]), int(ciclo_dias * FASE_INDUTIVA[1]) + 1)
    return float(comprimento_dia(lat, (j0 + dias - 1) % 365 + 1).mean())


def alerta_fotoperiodo(lat: float, modo: str, colheita: str, sensivel: bool, curto: bool, neutro: bool,
                       longo: bool, plantio, ciclo_dias: int | None, indicada_zarc: bool = False
                       ) -> tuple[bool, str | None, float | None]:
    """(alerta, tipo, horas na fase indutiva) para UM plantio.

    Só avalia espécies sensíveis e sem evidência de cultivar adaptada (indicada pelo ZARC).

    - Colheita reprodutiva (grão/fruto): alerta se o dia está FORA da faixa aceita (com tolerância):
      abaixo → ``floracao_impedida``; acima → ``floracao_atrasada``.
    - Colheita vegetativa (folha/raiz): o problema é florescer antes da colheita. Alerta
      ``pendoamento`` se a espécie é de dia longo e o dia está DENTRO da faixa que induz a floração.
    - Perenes: usa o ano inteiro; floração: alerta se o dia NUNCA entra na faixa; pendoamento: se
      o dia chega à faixa longa em alguma época.
    """
    inf, sup = faixa_aceita(curto, neutro, longo)
    if modo == "implantacao":
        horas_ano = comprimento_dia(lat, np.arange(1, 366))
        horas, h_min, h_max = float(horas_ano.mean()), float(horas_ano.min()), float(horas_ano.max())
    else:
        horas = h_min = h_max = dia_fase_indutiva(lat, plantio, ciclo_dias)

    if not sensivel or indicada_zarc:
        return False, None, horas
    if colheita == "reprodutiva":
        if h_max < inf:
            return True, "floracao_impedida", horas
        if h_min > sup:
            return True, "floracao_atrasada", horas
        return False, None, horas
    dia_longo = longo and not curto
    if colheita == "vegetativa" and dia_longo and h_max >= LIMITE_LONGO - TOLERANCIA_FOTO_H:
        return True, "pendoamento", horas
    return False, None, horas


MENSAGENS_FOTO = {
    "floracao_impedida": "Dias curtos demais para esta cultura florescer ou espigar. Use cultivar insensível ao fotoperíodo.",
    "floracao_atrasada": "Dias longos nesta época: floração atrasada, ciclo mais longo e porte maior. Escolha cultivar adaptada à sua latitude.",
    "pendoamento": "Risco de pendoamento precoce. Prefira outra data ou uma cultivar resistente ao pendoamento.",
}
