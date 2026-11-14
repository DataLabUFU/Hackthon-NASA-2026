"""Leitura do ``dados_unificados.csv`` e recorte do período de referência.

O arquivo traz 20 pontos (P01–P20) × 8.401 dias (2000–2022) da NASA POWER (MERRA-2), com as
colunas ``YEAR;DOY;T2M;T2M_MAX;T2M_MIN;RH2M;WS2M;PRECTOTCORR;PONTO``. Cuidados de leitura:
separador ``;`` e BOM no início (por isso ``encoding="utf-8-sig"``).

Regra anti-vazamento: limiares, climatologias e probabilidades históricas usam só anos até
``ANO_FIM_REFERENCIA`` (2021). 2022 em diante é período do time de ML.
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
CAMINHO_PADRAO = ROOT / "data" / "raw" / "power" / "dados_unificados.csv"

COLUNAS = ["YEAR", "DOY", "T2M", "T2M_MAX", "T2M_MIN", "RH2M", "WS2M", "PRECTOTCORR", "PONTO"]
COLUNAS_NUMERICAS = COLUNAS[2:-1]
VALOR_AUSENTE = -999.0

ANO_INICIO_REFERENCIA = 2000
ANO_FIM_REFERENCIA = 2021  # nunca maior que 2021 (contrato com o ML, §6 do briefing)


def decendio(datas) -> np.ndarray:
    """Decêndio do ano (1–36), como no ZARC: dias 1–10, 11–20 e 21–fim de cada mês."""
    d = pd.DatetimeIndex(datas)
    return ((d.month - 1) * 3 + np.minimum((d.day - 1) // 10, 2) + 1).to_numpy()


def ler_dados_unificados(caminho: str | Path | None = None) -> pd.DataFrame:
    """Lê o CSV, cria a coluna ``data`` e ``decendio`` e valida a série.

    Devolve as linhas ordenadas por ponto e data. Valores -999 viram NaN (não há nenhum no
    arquivo conferido, mas a POWER usa esse código para ausente).
    """
    caminho = Path(caminho) if caminho else CAMINHO_PADRAO
    if not caminho.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {caminho} (copie o dados_unificados.csv para data/raw/power/)")

    df = pd.read_csv(caminho, sep=";", encoding="utf-8-sig")
    faltando = [c for c in COLUNAS if c not in df.columns]
    if faltando:
        raise ValueError(f"Colunas ausentes em {caminho.name}: {faltando}")

    df[COLUNAS_NUMERICAS] = df[COLUNAS_NUMERICAS].mask(df[COLUNAS_NUMERICAS] == VALOR_AUSENTE)
    df["PONTO"] = df["PONTO"].astype(str)
    # YEAR + DOY → data (ex.: 2000 + 060 → 29/02/2000)
    df["data"] = pd.to_datetime(df["YEAR"].astype(str) + df["DOY"].astype(str).str.zfill(3), format="%Y%j")
    df = df.sort_values(["PONTO", "data"], kind="stable").reset_index(drop=True)
    _validar(df)
    df["decendio"] = decendio(df["data"])
    return df


def _validar(df: pd.DataFrame) -> None:
    """Duplicatas e lacunas de datas quebram as somas móveis: são erro, não aviso."""
    dup = df.duplicated(["PONTO", "data"]).sum()
    if dup:
        raise ValueError(f"{dup} linhas duplicadas (PONTO, data)")
    passos = df.groupby("PONTO", sort=False)["data"].diff().dropna()
    if (passos != pd.Timedelta(days=1)).any():
        raise ValueError("Série com datas faltando ou fora de ordem em algum ponto")
    ordem = (df["T2M_MIN"] <= df["T2M"]) & (df["T2M"] <= df["T2M_MAX"])
    n_fora = int((~ordem & df[["T2M", "T2M_MIN", "T2M_MAX"]].notna().all(axis=1)).sum())
    if n_fora:
        log.warning("%d linhas com T2M fora de [T2M_MIN, T2M_MAX]", n_fora)


def filtrar_referencia(df: pd.DataFrame, ano_inicio: int = ANO_INICIO_REFERENCIA,
                       ano_fim: int = ANO_FIM_REFERENCIA) -> pd.DataFrame:
    """Recorte dos anos de referência. Recusa ``ano_fim`` > 2021 (período do ML)."""
    if ano_fim > ANO_FIM_REFERENCIA:
        raise ValueError(f"ano_fim={ano_fim}: a referência termina em {ANO_FIM_REFERENCIA} (2022+ é do ML)")
    return df[(df["YEAR"] >= ano_inicio) & (df["YEAR"] <= ano_fim)].reset_index(drop=True)


def hash_arquivo(caminho: str | Path | None = None) -> str:
    """SHA-256 do arquivo de dados, para registrar exatamente qual versão gerou cada tabela."""
    caminho = Path(caminho) if caminho else CAMINHO_PADRAO
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()
