"""Leitura do arquivo de clima e separação do período de referência.

O arquivo ``dados_unificados.csv`` traz dados diários da NASA POWER para 20 pontos
(``P01`` a ``P20``), de 01/01/2000 a 31/12/2022. Todas as variáveis vêm da reanálise MERRA-2
(um modelo que combina observações e física da atmosfera numa grade de cerca de 50 km):

============  ======================================================  ========
Coluna        Descrição                                               Unidade
============  ======================================================  ========
YEAR, DOY     ano e dia do ano (1 a 366)                              —
T2M           temperatura do ar a 2 metros (média do dia)             °C
T2M_MAX       temperatura máxima do dia a 2 metros                    °C
T2M_MIN       temperatura mínima do dia a 2 metros                    °C
RH2M          umidade relativa do ar a 2 metros                       %
WS2M          velocidade do vento a 2 metros                          m/s
PRECTOTCORR   chuva do dia, corrigida                                 mm/dia
PONTO         identificador do ponto (P01 a P20)                      —
============  ======================================================  ========

Detalhes do arquivo: as colunas são separadas por ``;`` e o arquivo começa com um caractere
invisível (BOM). Por isso a leitura usa ``encoding="utf-8-sig"``; sem isso, a primeira coluna
viria com o nome ``\\ufeffYEAR``.

Período de referência
---------------------
As probabilidades históricas e os limiares usam só os anos até 2021. Os dados de 2022 em
diante são usados pelo time de ML para testar previsões; se entrassem na referência, a
"resposta" do teste já estaria embutida na média histórica e o teste ficaria otimista.
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
VALOR_AUSENTE = -999.0  # código que a NASA POWER usa para "sem dado"

ANO_INICIO_REFERENCIA = 2000
ANO_FIM_REFERENCIA = 2021  # último ano da referência; 2022 em diante fica para o ML


def decendio(datas) -> np.ndarray:
    """Decêndio do ano (1 a 36), o mesmo calendário usado no zoneamento agrícola (ZARC).

    Cada mês tem três decêndios: dias 1–10, 11–20 e 21 até o fim do mês.
    Ex.: 15/02 está no decêndio 5; 31/12 está no decêndio 36.
    """
    d = pd.DatetimeIndex(datas)
    return ((d.month - 1) * 3 + np.minimum((d.day - 1) // 10, 2) + 1).to_numpy()


def ler_dados_unificados(caminho: str | Path | None = None) -> pd.DataFrame:
    """Lê o CSV e devolve uma tabela pronta para os cálculos.

    Acrescenta as colunas ``data`` (a partir de ``YEAR`` e ``DOY``) e ``decendio``, ordena
    por ponto e data e confere se não falta nenhum dia. Valores -999 viram ``NaN`` (ausente).
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
    # ano + dia do ano → data. Ex.: 2000 e 060 → 29/02/2000 (2000 é bissexto)
    df["data"] = pd.to_datetime(df["YEAR"].astype(str) + df["DOY"].astype(str).str.zfill(3), format="%Y%j")
    df = df.sort_values(["PONTO", "data"], kind="stable").reset_index(drop=True)
    _validar(df)
    df["decendio"] = decendio(df["data"])
    return df


def _validar(df: pd.DataFrame) -> None:
    """Confere a série antes dos cálculos.

    As somas de vários dias (chuva em 3 dias, por exemplo) supõem que as linhas são dias
    consecutivos. Um dia faltando ou repetido faria a soma misturar dias errados sem avisar,
    então isso é tratado como erro. Temperatura média fora do intervalo [mínima, máxima]
    só gera um aviso.
    """
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
    """Mantém só os anos de referência. Não aceita ``ano_fim`` depois de 2021."""
    if ano_fim > ANO_FIM_REFERENCIA:
        raise ValueError(f"ano_fim={ano_fim}: a referência termina em {ANO_FIM_REFERENCIA} (2022 em diante é do ML)")
    return df[(df["YEAR"] >= ano_inicio) & (df["YEAR"] <= ano_fim)].reset_index(drop=True)


def hash_arquivo(caminho: str | Path | None = None) -> str:
    """Impressão digital (SHA-256) do arquivo de dados.

    Gravada junto de cada tabela gerada, permite saber depois exatamente qual versão do
    arquivo produziu aqueles números.
    """
    caminho = Path(caminho) if caminho else CAMINHO_PADRAO
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()
