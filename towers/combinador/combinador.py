"""Combinação dos scores das torres em um score final por (cultura × data de plantio).

    score_final = Π sᵢ^(wᵢ / Σw_disponíveis)     (média geométrica ponderada)

- sᵢ = score da torre i, com piso ``PISO_SCORE``; torre sem score (nulo) fica fora e o peso dela é
  redistribuído entre as demais (neutra).
- Eliminatório: ``gate_t1`` falso (clima inapto na maioria dos anos) → ``eliminada``.
- ``somente_financiaveis``: candidatos não financiáveis (T6) também são eliminados.
- Objetivo "estabilidade": T1 usa o P20 (pior ano típico) e T2 usa 1 − P(perda > 20%).
- Peso da evidência (``peso_evidencia``, padrão 0,1): o score é multiplicado por um fator de 0,9 a 1,0
  conforme a cobertura de torres e a qualidade dos parâmetros (ver ``pesos.py``).

Entradas: as saídas das torres sem colapsar variantes. T1, T2, T4 e T6 são por (id_cultura, plantio);
T3 e T5 são por id_cultura. ``extras`` permite plugar outras torres (ex.: a de extremos de temperatura):
{"nome": (DataFrame com id_cultura[, plantio] e score_<nome>, peso)}.
"""
from __future__ import annotations

import polars as pl

from .pesos import OBJETIVOS, PESO_COBERTURA, PESO_EVIDENCIA, PISO_SCORE


def combinar(t1: pl.DataFrame, t2: pl.DataFrame | None = None, t3: pl.DataFrame | None = None,
             t4: pl.DataFrame | None = None, t5: pl.DataFrame | None = None, t6: pl.DataFrame | None = None,
             objetivo: str = "equilibrado", somente_financiaveis: bool | None = None,
             extras: dict[str, tuple[pl.DataFrame, float]] | None = None,
             peso_evidencia: float = PESO_EVIDENCIA, pesos: dict[str, float] | None = None) -> pl.DataFrame:
    """``pesos`` (opcional) sobrescreve os pesos do objetivo (ex.: combinação de vários objetivos do front)."""
    if objetivo not in OBJETIVOS:
        raise ValueError(f"objetivo desconhecido: {objetivo!r} (válidos: {sorted(OBJETIVOS)})")
    cfg = OBJETIVOS[objetivo]
    pesos = dict(pesos or cfg["pesos"])
    conservador = cfg.get("conservador", False)
    if somente_financiaveis is None:
        somente_financiaveis = cfg.get("somente_financiaveis", False)

    chave = ["id_cultura", "plantio"]
    df = t1.select(
        *chave, "nome_pt", "uso", "modo", "colheita", "obrigatoria", "escala_cultivo", "gate_t1", "fator_limitante",
        "ciclo_dias", "alerta_foto_mensagem", "alerta_ciclo_extremo",
        *[c for c in ("fonte_parametros", "tipo_cultura", "prob_apta") if c in t1.columns],
        s_t1=pl.col("apt_p20") if conservador else pl.col("score_t1"),
    )
    if t2 is not None:
        df = df.join(t2.select(*chave, s_t2=(1 - pl.col("prob_perda20")) if conservador else pl.col("score_t2"),
                               irrigacao_mm=pl.col("irrigacao_mm_med"), ciclo_t2=pl.col("ciclo_dias"),
                               *[c for c in ("parametros_t2_origem",) if c in t2.columns]),
                     on=chave, how="left")
    if t3 is not None:
        df = df.join(t3.select("id_cultura", s_t3=pl.col("score_t3"), alertas_solo=pl.col("alertas_solo"),
                               fator_limitante_solo=pl.col("fator_limitante_solo")), on="id_cultura", how="left")
    if t4 is not None:
        df = df.join(t4.select(*chave, s_t4=pl.col("score_t4"), zarc_status=pl.col("zarc_status"),
                               risco_zarc_pct=pl.col("risco_pct")), on=chave, how="left")
    if t5 is not None:
        df = df.join(t5.select("id_cultura", s_t5=pl.col("score_t5"), explicacao_rotacao=pl.col("explicacao_rotacao")),
                     on="id_cultura", how="left")
    if t6 is not None:
        df = df.join(t6.select(*chave, "status_elegibilidade", "financiavel", "elegivel_proagro", "portaria_zarc",
                               motivos_elegibilidade=pl.col("motivos")), on=chave, how="left")
    for nome, (extra, peso) in (extras or {}).items():
        k = [c for c in chave if c in extra.columns]
        df = df.join(extra.select(*k, pl.col(f"score_{nome}").alias(f"s_{nome}")), on=k, how="left")
        pesos[nome] = peso

    presentes = [t for t in pesos if f"s_{t}" in df.columns]
    # média geométrica ponderada só com as torres que têm score (as demais são neutras)
    w = {t: pl.when(pl.col(f"s_{t}").is_not_null()).then(pesos[t]).otherwise(0.0) for t in presentes}
    soma_w = pl.sum_horizontal(*w.values())
    log_soma = pl.sum_horizontal(*[
        pl.when(pl.col(f"s_{t}").is_not_null())
        .then(w[t] * pl.col(f"s_{t}").clip(lower_bound=PISO_SCORE).log()).otherwise(0.0)
        for t in presentes
    ])
    df = df.with_columns(
        score_combinado=(log_soma / soma_w).exp(),
        torres_com_score=pl.sum_horizontal(*[pl.col(f"s_{t}").is_not_null().cast(pl.Int8) for t in presentes]),
        torres_avaliadas=pl.lit(len(presentes), pl.Int8),
    )
    # peso da evidência: cobertura de torres + qualidade dos parâmetros
    qualidades = []
    if "parametros_t2_origem" in df.columns:
        qualidades.append(pl.when(pl.col("parametros_t2_origem") == "cultura").then(1.0).otherwise(0.5))
    if "fonte_parametros" in df.columns:
        qualidades.append(pl.when(pl.col("fonte_parametros") == "ECOCROP (FAO)").then(1.0).otherwise(0.5))
    qualidade = pl.mean_horizontal(*qualidades) if qualidades else pl.lit(1.0)
    df = df.with_columns(
        evidencia=PESO_COBERTURA * pl.col("torres_com_score") / pl.col("torres_avaliadas")
        + (1 - PESO_COBERTURA) * qualidade,
    ).with_columns(
        fator_confianca=1 - peso_evidencia * (1 - pl.col("evidencia")),
    ).with_columns(score_combinado=pl.col("score_combinado") * pl.col("fator_confianca"))

    eliminada = ~pl.col("gate_t1")
    motivo = pl.when(~pl.col("gate_t1")).then(pl.concat_str(pl.lit("clima inapto (T1: "), pl.col("fator_limitante"), pl.lit(")")))
    if somente_financiaveis and "financiavel" in df.columns:
        eliminada = eliminada | ~pl.col("financiavel").fill_null(False)
        motivo = motivo.when(~pl.col("financiavel").fill_null(False)).then(pl.lit("não financiável (T6)"))
    return df.with_columns(
        eliminada=eliminada,
        motivo_eliminacao=motivo.otherwise(None),
        score_final=pl.when(eliminada).then(0.0).otherwise(pl.col("score_combinado")),
        objetivo=pl.lit(objetivo),
    )
