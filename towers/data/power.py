"""Cliente da NASA POWER (dados diários por ponto), com cache local em parquet.

API: https://power.larc.nasa.gov/docs/services/api/
Endpoint: https://power.larc.nasa.gov/api/temporal/daily/point (sem autenticação)

Decisões:

- **Chuva = GPM IMERG** (``IMERG_PRECTOT``, disponível desde 06/2000). A chuva da reanálise
  MERRA-2 (``PRECTOTCORR``) subestima ~13% em média e o viés piora nos anos recentes; ela é
  baixada só como diagnóstico.
- **Horário UTC** em todas as consultas (o IMERG só existe em UTC). No Brasil (UTC−3) o "dia"
  vai das 21 h às 21 h locais; mínima e máxima diárias continuam no mesmo dia.
- **Série a partir de 2001**, a mesma janela de anos para todas as variáveis.
- **Lacunas:** chuva nunca é preenchida; as demais variáveis são interpoladas só em lacunas
  de até ``LIMITE_INTERPOLACAO`` dias. O restante fica nulo, e quem consome a série deve
  descartar janelas incompletas (não tratar nulo como zero).
- **Defasagens:** a MERRA-2 chega a ~2 dias de hoje (provisória); o IMERG, a ~2 meses (final).
  A cada atualização, os últimos ``DIAS_REPROCESSAR`` dias são baixados de novo para trocar
  valores provisórios por consolidados.

O cache é por célula da grade da POWER (MERRA-2: 0,5° lat × 0,625° lon); municípios vizinhos
reaproveitam o mesmo arquivo.
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable

import polars as pl
import requests

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
CACHE_PADRAO = ROOT / "data" / "cache" / "power"

POWER_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
USER_AGENT = "towers-power-client/0.1 (python-requests)"
PADRAO_HORARIO = "UTC"

PASSO_LAT, PASSO_LON = 0.5, 0.625
INICIO_PADRAO = date(2001, 1, 1)
DEFASAGEM_DIAS = 2          # a MERRA-2 é publicada com ~2 dias de atraso
DIAS_REPROCESSAR = 120      # cobre a defasagem do IMERG (~60 dias) e a revisão da MERRA-2
LIMITE_INTERPOLACAO = 3     # dias

CHUVA = "IMERG_PRECTOT"
CHUVA_DIAGNOSTICO = "PRECTOTCORR"
PARAMS_CHUVA = frozenset({CHUVA, CHUVA_DIAGNOSTICO})

# Parâmetros por torre (a T2 acrescenta os seus ao chamar com params=...).
PARAMS_T1 = ("T2M", "T2M_MIN", "T2M_MAX", CHUVA, CHUVA_DIAGNOSTICO)
PARAMS_T2 = PARAMS_T1 + ("GWETROOT", "ALLSKY_SFC_SW_DWN", "RH2M", "WS2M", "PS")

VALOR_AUSENTE = -999.0


def celula_grade(lat: float, lon: float) -> tuple[float, float]:
    """Centro da célula da grade da POWER que contém (lat, lon)."""
    return round(round(lat / PASSO_LAT) * PASSO_LAT, 4), round(round(lon / PASSO_LON) * PASSO_LON, 4)


def _arquivo_cache(cache_dir: Path, lat_c: float, lon_c: float) -> Path:
    return Path(cache_dir) / f"power_{PADRAO_HORARIO.lower()}_{lat_c:+08.3f}_{lon_c:+09.3f}.parquet"


def baixar_power(lat: float, lon: float, inicio: date, fim: date, params: Iterable[str],
                 tentativas: int = 3, sessao: requests.Session | None = None) -> pl.DataFrame:
    """Uma chamada à API. Devolve colunas ``data`` + parâmetros, com -999 → nulo."""
    params = list(params)
    sessao = sessao or requests.Session()
    consulta = {
        "parameters": ",".join(params),
        "community": "AG",
        "latitude": lat,
        "longitude": lon,
        "start": inicio.strftime("%Y%m%d"),
        "end": fim.strftime("%Y%m%d"),
        "format": "JSON",
        "time-standard": PADRAO_HORARIO,
    }
    for tentativa in range(1, tentativas + 1):
        try:
            r = sessao.get(POWER_URL, params=consulta, headers={"User-Agent": USER_AGENT}, timeout=(30, 300))
            r.raise_for_status()
            break
        except requests.RequestException as e:
            log.warning("POWER: tentativa %d/%d falhou: %s", tentativa, tentativas, e)
            if tentativa == tentativas:
                raise
            time.sleep(5 * tentativa)

    dados = r.json()["properties"]["parameter"]
    datas = sorted(dados[params[0]].keys())
    df = pl.DataFrame(
        {"data": datas, **{p: [dados[p].get(d) for d in datas] for p in params}},
        schema={"data": pl.String, **{p: pl.Float64 for p in params}},
    )
    return df.with_columns(
        pl.col("data").str.to_date("%Y%m%d"),
        *[pl.when(pl.col(p) <= VALOR_AUSENTE).then(None).otherwise(pl.col(p)).alias(p) for p in params],
    )


def _remover_cauda_vazia(df: pl.DataFrame, params: list[str]) -> pl.DataFrame:
    """Remove os dias finais em que nenhum parâmetro foi publicado ainda."""
    tem_dado = pl.any_horizontal([pl.col(p).is_not_null() for p in params])
    ultimo = df.filter(tem_dado)["data"].max()
    return df if ultimo is None else df.filter(pl.col("data") <= ultimo)


def interpolar_lacunas_curtas(df: pl.DataFrame, params: Iterable[str], limite: int = LIMITE_INTERPOLACAO) -> pl.DataFrame:
    """Interpolação linear só em lacunas internas de até ``limite`` dias. Chuva nunca é preenchida.

    Lacunas no início ou no fim da série não são extrapoladas.
    """
    for p in params:
        if p in PARAMS_CHUVA:
            continue
        df = (
            df.with_columns(_bloco=pl.col(p).is_null().rle_id())
            .with_columns(_tam=pl.len().over("_bloco"))
            .with_columns(
                pl.when(pl.col(p).is_null() & (pl.col("_tam") <= limite))
                .then(pl.col(p).interpolate()).otherwise(pl.col(p)).alias(p)
            )
            .drop("_bloco", "_tam")
        )
    return df


def ultimo_dia_valido(df: pl.DataFrame, params: Iterable[str] | None = None) -> dict[str, date | None]:
    """Último dia com dado de cada parâmetro (o IMERG termina ~2 meses antes da temperatura)."""
    params = params or _params_do(df)
    return {p: df.filter(pl.col(p).is_not_null())["data"].max() for p in params}


def clima_diario(lat: float, lon: float, inicio: date = INICIO_PADRAO, fim: date | None = None,
                 params: Iterable[str] = PARAMS_T1, cache_dir: Path | str = CACHE_PADRAO,
                 usar_cache: bool = True) -> pl.DataFrame:
    """Série diária da POWER para a célula que contém (lat, lon), de ``inicio`` a ``fim``.

    - ``fim`` padrão: hoje − 2 dias. Dias finais sem nenhum parâmetro publicado são removidos;
      parâmetros com defasagem maior (IMERG) ficam nulos no fim da série.
    - Colunas: ``data``, parâmetros pedidos, ``lat_celula``, ``lon_celula``.
    """
    params = list(dict.fromkeys(params))
    fim = fim or (date.today() - timedelta(days=DEFASAGEM_DIAS))
    lat_c, lon_c = celula_grade(lat, lon)
    arquivo = _arquivo_cache(Path(cache_dir), lat_c, lon_c)

    cache = pl.read_parquet(arquivo) if usar_cache and arquivo.exists() else None
    if cache is not None:
        faltam = [p for p in params if p not in cache.columns]
        c_ini, c_fim = cache["data"].min(), cache["data"].max()
        atualizado_hoje = datetime.fromtimestamp(arquivo.stat().st_mtime).date() == date.today()

        if faltam:
            # Parâmetro novo: baixa o período inteiro do cache + o pedido, só para os que faltam.
            novo = baixar_power(lat_c, lon_c, min(inicio, c_ini), max(fim, c_fim), faltam)
            cache = cache.join(novo, on="data", how="full", coalesce=True)
        partes = [cache]
        if inicio < c_ini:
            partes.append(baixar_power(lat_c, lon_c, inicio, c_ini - timedelta(days=1), _params_do(cache)))
        if fim > c_fim and not atualizado_hoje:
            # Reprocessa os últimos dias do cache: troca valores provisórios por consolidados e
            # preenche o IMERG que ainda não tinha sido publicado.
            desde = max(c_ini, c_fim - timedelta(days=DIAS_REPROCESSAR))
            partes.append(baixar_power(lat_c, lon_c, desde, fim, _params_do(cache)))
        df = pl.concat(partes, how="diagonal_relaxed") if len(partes) > 1 else cache
        mudou = bool(faltam) or len(partes) > 1
    else:
        df = baixar_power(lat_c, lon_c, inicio, fim, params)
        mudou = True

    todos = _params_do(df)
    # concat na ordem [cache, novos]: keep="last" faz os dados recém-baixados prevalecerem.
    df = _remover_cauda_vazia(df.unique("data", keep="last").sort("data"), todos)
    if usar_cache and mudou:
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        df.write_parquet(arquivo)
        log.info("POWER: cache salvo em %s (%d dias)", arquivo, df.height)

    df = df.filter(pl.col("data").is_between(inicio, fim)).select("data", *params)
    df = interpolar_lacunas_curtas(df, params)

    ultimo = ultimo_dia_valido(df, params)
    nulos_internos = {
        p: n for p in params
        if ultimo[p] and (n := df.filter(pl.col("data") <= ultimo[p])[p].null_count())
    }
    if nulos_internos:
        log.warning("POWER (%s, %s): dias sem dado no meio da série: %s", lat_c, lon_c, nulos_internos)

    return df.with_columns(lat_celula=pl.lit(lat_c), lon_celula=pl.lit(lon_c))


def _params_do(df: pl.DataFrame) -> list[str]:
    return [c for c in df.columns if c not in ("data", "lat_celula", "lon_celula")]
