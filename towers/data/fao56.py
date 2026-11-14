"""Parâmetros de cultura para o balanço hídrico (FAO-56 / FAO-33).

``parametros_fao56.csv`` tem duas camadas:

- linhas ``grupo:<nome>``: valores típicos de cada grupo de culturas (curadoria a partir das
  tabelas da FAO-56 e da FAO-33), usados por toda cultura sem valor específico;
- linhas ``<id_cultura>``: valores específicos das principais culturas.

Colunas: ``kc_ini``, ``kc_mid``, ``kc_end`` (FAO-56 Tab. 12); ``frac_ini/dev/mid/late`` (fração do
ciclo em cada fase, a partir das durações da FAO-56 Tab. 11; a duração total vem do ciclo avaliado);
``raiz_m`` e ``p`` (FAO-56 Tab. 22: profundidade efetiva de raiz e fração de depleção sem estresse);
``ky`` (FAO-33: resposta do rendimento ao déficit hídrico); ``duracao_fao`` (duração total típica da
FAO-56 Tab. 11, só para as culturas específicas anuais: limita os ciclos avaliados pela T2); ``fonte``.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import polars as pl

from .ecocrop import _contem_algum

CAMINHO = Path(__file__).resolve().parent / "parametros_fao56.csv"
PARAMS = ["kc_ini", "kc_mid", "kc_end", "frac_ini", "frac_dev", "frac_mid", "frac_late", "raiz_m", "p", "ky"]


def grupo_fao(df: pl.DataFrame) -> pl.Expr:
    """Grupo FAO de cada cultura, a partir de uso, modo, categoria e tipo de colheita."""
    cat = lambda *t: _contem_algum("CAT", t)  # noqa: E731
    return (
        pl.when(pl.col("uso") == "silvicultura").then(pl.lit("silvicultura"))
        .when(pl.col("modo") == "implantacao").then(
            pl.when(cat("fruits & nuts")).then(pl.lit("frutiferas_perenes"))
            .when(cat("forage/pasture", "cover crop")).then(pl.lit("forrageiras"))
            .otherwise(pl.lit("perenes_outras")))
        .when(cat("cereals & pseudocereals")).then(pl.lit("cereais"))
        .when(cat("pulses (grain legumes)")).then(pl.lit("leguminosas_grao"))
        .when(cat("roots/tubers")).then(pl.lit("raizes_tuberculos"))
        .when(cat("vegetables") & (pl.col("colheita") == "vegetativa")).then(pl.lit("hortalicas_folhosas"))
        .when(cat("vegetables")).then(pl.lit("hortalicas_fruto"))
        .when(cat("forage/pasture", "cover crop")).then(pl.lit("forrageiras"))
        .otherwise(pl.lit("outras_anuais"))
    )


def ler_parametros(caminho: Path | str = CAMINHO) -> pl.DataFrame:
    df = pl.read_csv(caminho)
    soma = df.select(pl.sum_horizontal("frac_ini", "frac_dev", "frac_mid", "frac_late").alias("s"))["s"]
    if ((soma - 1).abs() > 0.01).any():
        raise ValueError("parametros_fao56.csv: frações de fase não somam 1")
    return df


def parametros_t2(culturas: pl.DataFrame, caminho: Path | str = CAMINHO) -> pl.DataFrame:
    """``culturas`` + parâmetros FAO-56 (específicos ou do grupo) + ``grupo_fao`` + ``parametros_t2_origem``."""
    par = ler_parametros(caminho)
    especificos = par.filter(~pl.col("chave").str.starts_with("grupo:")).rename({"chave": "id_cultura"})
    grupos = par.filter(pl.col("chave").str.starts_with("grupo:")).with_columns(
        grupo_fao=pl.col("chave").str.strip_prefix("grupo:")).drop("chave")

    base = culturas.with_columns(grupo_fao=grupo_fao(culturas))
    com_grupo = base.join(grupos.select("grupo_fao", *PARAMS), on="grupo_fao", how="left")
    com_esp = com_grupo.join(especificos.select("id_cultura", *PARAMS, "duracao_fao", "fonte"), on="id_cultura",
                             how="left", suffix="_esp")
    return com_esp.with_columns(
        *[pl.coalesce(f"{c}_esp", c).alias(c) for c in PARAMS],
        parametros_t2_origem=pl.when(pl.col("kc_mid_esp").is_not_null()).then(pl.lit("cultura")).otherwise(pl.lit("grupo")),
    ).drop([f"{c}_esp" for c in PARAMS] + ["fonte"])


def curva_kc(kc_ini: float, kc_mid: float, kc_end: float, fracs: tuple[float, float, float, float],
             dur: int) -> tuple[np.ndarray, tuple[int, int]]:
    """Kc diário do ciclo (FAO-56 fig. 25) e o intervalo [início, fim) da fase intermediária."""
    li = max(1, round(fracs[0] * dur))
    ld = max(1, round(fracs[1] * dur))
    lm = max(1, round(fracs[2] * dur))
    ll = dur - li - ld - lm
    if ll < 1:                      # arredondamento em ciclos curtos: tira da fase intermediária
        lm = max(1, lm - (1 - ll))
        ll = dur - li - ld - lm
    kc = np.concatenate([
        np.full(li, kc_ini),
        np.linspace(kc_ini, kc_mid, ld, endpoint=False),
        np.full(lm, kc_mid),
        np.linspace(kc_mid, kc_end, ll),
    ])[:dur]
    return kc, (li + ld, li + ld + lm)
