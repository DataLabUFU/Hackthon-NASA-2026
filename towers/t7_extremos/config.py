"""Configuração da Torre 7: limiares e parâmetros lidos de ``configs/extremos.yaml``.

As classes abaixo descrevem quais campos o YAML pode ter, com seus tipos e valores padrão
(é o "schema"). O OmegaConf junta o schema com o YAML e acusa erro se aparecer um campo
desconhecido ou de tipo errado, o que pega erros de digitação cedo.

Cada limiar registra valor, unidade, fonte, data de vigência e status:

- ``PROVISORIO``: valor de trabalho, ainda não confirmado pela equipe de agronomia;
- ``DEFINIDO``: valor fechado, com fonte.

Valor ``null`` significa "ainda não escolhido": as funções que precisam do limiar param com
uma mensagem clara, em vez de usar um número qualquer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

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
class Limiares:
    chuva_extrema: ChuvaExtrema = field(default_factory=ChuvaExtrema)
    queda_temperatura: QuedaTemperatura = field(default_factory=QuedaTemperatura)
    estiagem: Estiagem = field(default_factory=Estiagem)


@dataclass
class ConfigExtremos:
    referencia: Referencia = field(default_factory=Referencia)
    bootstrap: Bootstrap = field(default_factory=Bootstrap)
    limiares: Limiares = field(default_factory=Limiares)


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
