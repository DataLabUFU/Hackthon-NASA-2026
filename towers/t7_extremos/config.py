"""Limiares e parâmetros da Torre 7, lidos de ``configs/extremos.yaml``.

As classes abaixo são o schema: o OmegaConf rejeita campos desconhecidos ou de tipo errado.
Status de cada limiar: ``PROVISORIO`` (valor de trabalho) ou ``DEFINIDO`` (fechado, com
fonte). Valor ``null`` = ainda não escolhido; o cálculo para em vez de inventar um número.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from omegaconf import DictConfig, OmegaConf

from .dados import ANO_FIM_REFERENCIA

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PADRAO = ROOT / "configs" / "extremos.yaml"

STATUS = ("PROVISORIO", "DEFINIDO")


@dataclass
class Referencia:
    arquivo: str = "data/raw/power/dados_unificados.csv"
    ano_inicio: int = 2000
    ano_fim: int = ANO_FIM_REFERENCIA
    fonte_dados: str = ""
    data_download: Optional[str] = None


@dataclass
class Bootstrap:
    repeticoes: int = 1000
    semente: int = 42
    nivel_ic: float = 0.95


@dataclass
class ChuvaExtrema:
    valor: Optional[float] = None
    unidade: str = "mm"
    janela_dias: int = 3
    fonte: str = ""
    vigencia: Optional[str] = None
    status: str = "PROVISORIO"
    grade_sensibilidade: List[float] = field(default_factory=list)


@dataclass
class QuedaTemperatura:
    valor: Optional[float] = None
    unidade: str = "°C"
    janela_dias: int = 2
    absoluto: bool = False
    """False = só resfriamento; True = |variação| (inclui aquecimento brusco)."""
    fonte: str = ""
    vigencia: Optional[str] = None
    status: str = "PROVISORIO"
    grade_sensibilidade: List[float] = field(default_factory=list)


@dataclass
class Estiagem:
    n_dias: int = 10
    n_dias_status: str = "PROVISORIO"
    limiar_amplitude_alta: Optional[float] = None
    """Anomalia da amplitude térmica (°C) a partir da qual o dia conta como 'amplitude alta'."""
    limiar_amplitude_alta_status: str = "PROVISORIO"
    janela_climatologia_dias: int = 31
    fonte: str = ""


@dataclass
class Enso:
    indice: Optional[str] = None
    """Índice usado para classificar as fases (ex.: RONI ou ONI, da NOAA)."""
    url: Optional[str] = None
    """Arquivo do índice baixado na hora (texto ``SEAS YR ANOM`` da NOAA/CPC); null = ENSO não calculado."""
    limiar_el_nino: float = 0.5
    limiar_la_nina: float = -0.5
    cache_dias: int = 7
    tabela: Optional[str] = None
    """CSV com colunas ``ano`` e ``fase``; null = ENSO não calculado."""
    fase_atual: Optional[str] = None
    k: float = 10.0
    k_status: str = "PROVISORIO"
    repeticoes_permutacao: int = 10_000
    fonte: str = ""


@dataclass
class Gpd:
    quantil_limiar: float = 0.95
    """Limiar u = este quantil da série da safra (por ponto)."""
    grade_quantis: List[float] = field(default_factory=lambda: [0.90, 0.95, 0.975])
    r_chuva: int = 3
    """Dias seguidos abaixo de u que encerram um grupo (>= janela da soma, que é 3)."""
    r_queda: int = 2
    repeticoes_bootstrap: int = 200
    periodos_retorno: List[float] = field(default_factory=lambda: [10.0, 20.0])
    estabilidade_repeticoes: int = 200
    estabilidade_fracao: float = 0.85
    estabilidade_T: float = 10.0
    criterio_razao: float = 1.5
    """Reprova a GPD se ela oscilar mais que isso vezes o empírico."""
    criterio_dp_xi: float = 0.20
    usar_na_chuva: bool = False
    """True: na safra out–mar, a chuva extrema usa a GPD nos pontos aprovados."""
    exigir_concordancia: bool = True
    """Só usa a GPD se o valor empírico cair dentro do IC dela."""
    resultado: str = "artifacts/t7/gpd/gpd_por_ponto.csv"


@dataclass
class ChuvaDia:
    valor: Optional[float] = None
    unidade: str = "mm"
    fonte: str = ""
    status: str = "PROVISORIO"


@dataclass
class ChuvaPersistente:
    dias: int = 3
    chuva_minima_mm: float = 1.0
    fonte: str = ""
    status: str = "PROVISORIO"


@dataclass
class Fase:
    nome: str = ""
    dias: Optional[List[float]] = None
    """[início, fim] em dias após o plantio."""
    ciclo: Optional[List[float]] = None
    """[início, fim] em fração do ciclo (0 = plantio, 1 = colheita)."""
    ultimos_dias: Optional[int] = None
    """Os N últimos dias do ciclo."""
    eventos: List[str] = field(default_factory=list)


@dataclass
class CulturaExtremos:
    frio_tmin: Optional[float] = None
    """Evento ``frio``: temperatura mínima do dia (T2M_MIN) abaixo deste valor na fase."""
    frio_status: str = "PROVISORIO"
    fonte: str = ""
    fases: List[Fase] = field(default_factory=list)


@dataclass
class Culturas:
    """Eventos e fases por cultura usados pelo recomendador (``torre.py``)."""
    chuva_dia: ChuvaDia = field(default_factory=ChuvaDia)
    chuva_persistente: ChuvaPersistente = field(default_factory=ChuvaPersistente)
    padrao: List[Fase] = field(default_factory=list)
    por_cultura: Dict[str, CulturaExtremos] = field(default_factory=dict)


@dataclass
class Limiares:
    chuva_extrema: ChuvaExtrema = field(default_factory=ChuvaExtrema)
    queda_temperatura: QuedaTemperatura = field(default_factory=QuedaTemperatura)
    estiagem: Estiagem = field(default_factory=Estiagem)


@dataclass
class ConfigExtremos:
    referencia: Referencia = field(default_factory=Referencia)
    bootstrap: Bootstrap = field(default_factory=Bootstrap)
    limiares: Limiares = field(default_factory=Limiares)
    enso: Enso = field(default_factory=Enso)
    gpd: Gpd = field(default_factory=Gpd)
    culturas: Culturas = field(default_factory=Culturas)


def carregar_config(caminho: str | Path | None = None, overrides: list[str] | None = None) -> DictConfig:
    """Schema ← YAML ← overrides ``chave=valor``. Chaves desconhecidas ou tipos errados dão erro."""
    caminho = Path(caminho) if caminho else CONFIG_PADRAO
    if not caminho.exists():
        raise FileNotFoundError(f"Config não encontrada: {caminho}")
    cfg = OmegaConf.merge(
        OmegaConf.structured(ConfigExtremos),
        OmegaConf.load(caminho),
        OmegaConf.from_dotlist(overrides or []),
    )
    validar(cfg)
    return cfg


def validar(cfg: DictConfig) -> None:
    ref = cfg.referencia
    if ref.ano_fim > ANO_FIM_REFERENCIA:
        raise ValueError(f"referencia.ano_fim={ref.ano_fim}: a referência termina em {ANO_FIM_REFERENCIA}")
    if ref.ano_inicio > ref.ano_fim:
        raise ValueError("referencia.ano_inicio maior que ano_fim")
    if not 0 < cfg.bootstrap.nivel_ic < 1:
        raise ValueError("bootstrap.nivel_ic deve estar entre 0 e 1")
    if cfg.bootstrap.repeticoes < 1:
        raise ValueError("bootstrap.repeticoes deve ser >= 1")
    lim = cfg.limiares
    for nome, status in [
        ("chuva_extrema.status", lim.chuva_extrema.status),
        ("queda_temperatura.status", lim.queda_temperatura.status),
        ("estiagem.n_dias_status", lim.estiagem.n_dias_status),
        ("estiagem.limiar_amplitude_alta_status", lim.estiagem.limiar_amplitude_alta_status),
        ("enso.k_status", cfg.enso.k_status),
    ]:
        if status not in STATUS:
            raise ValueError(f"limiares.{nome}={status!r}: use {STATUS}")
    for nome, bloco in [("chuva_extrema", lim.chuva_extrema), ("queda_temperatura", lim.queda_temperatura)]:
        if bloco.status == "DEFINIDO" and (bloco.valor is None or not bloco.fonte):
            raise ValueError(f"limiares.{nome}: status DEFINIDO exige valor e fonte")
    if lim.estiagem.janela_climatologia_dias % 2 == 0:
        raise ValueError("estiagem.janela_climatologia_dias deve ser ímpar (janela centrada)")


def limiar_obrigatorio(bloco, nome: str) -> float:
    """Valor do limiar ou erro claro se ainda estiver pendente (``null``)."""
    if bloco.valor is None:
        raise ValueError(f"Limiar {nome!r} pendente (valor null em configs/extremos.yaml). "
                         "Defina o valor (status PROVISORIO ou DEFINIDO) antes de calcular.")
    return float(bloco.valor)
