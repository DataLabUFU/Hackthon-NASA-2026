"""Configuração dos experimentos via YAML, resolvida com ``OmegaConf.merge``.

Ordem de precedência (a última vence):

1. Schema ``ExperimentConfig`` (defaults + validação de tipos e de chaves)
2. Arquivo YAML (``--config``, padrão ``configs/<modelo>.yaml``)
3. Overrides opcionais no terminal no formato ``chave=valor`` (ex.: ``params.learning_rate=0.03``)

Os hiperparâmetros (``params``) ainda passam por mais um merge, por cima dos padrões do
``model.py`` de cada modelo (ver ``merge_params``).
"""
import argparse
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from omegaconf import DictConfig, OmegaConf

from .spec import TASKS, ModelSpec


@dataclass
class DataConfig:
    path: Optional[str] = None
    """Dataset de treino (.csv ou .parquet)."""
    target: Optional[str] = None
    drop: List[str] = field(default_factory=list)
    """Colunas a descartar (ids, vazamentos...)."""
    task: str = "auto"
    """auto | classification | regression"""
    demo: bool = False
    """Usa um dataset sintético no lugar de ``path`` (smoke test)."""


@dataclass
class TrainConfig:
    test_size: float = 0.2
    """Fração de holdout (0 = treina com tudo)."""


@dataclass
class BenchmarkConfig:
    folds: int = 5
    n_jobs: int = 1
    """Folds em paralelo (os boosters já são multi-thread)."""


@dataclass
class InferenceConfig:
    input: Optional[str] = None
    output: Optional[str] = None
    model: Optional[str] = None
    """model.joblib ou pasta do run (padrão: último treino)."""
    proba: bool = False
    keep: List[str] = field(default_factory=list)
    """Colunas do input copiadas para a saída (ex.: id)."""


@dataclass
class ExperimentConfig:
    seed: int = 42
    output_dir: str = "artifacts"
    data: DataConfig = field(default_factory=DataConfig)
    params: Dict[str, Any] = field(default_factory=dict)
    """Override dos hiperparâmetros do estimador (nomes de cada lib)."""
    train: TrainConfig = field(default_factory=TrainConfig)
    benchmark: BenchmarkConfig = field(default_factory=BenchmarkConfig)
    inference: InferenceConfig = field(default_factory=InferenceConfig)


def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s", datefmt="%H:%M:%S")


def load_config(spec: ModelSpec, stage: str, argv=None) -> DictConfig:
    p = argparse.ArgumentParser(description=f"{stage.capitalize()} {spec.display_name}")
    p.add_argument("--config", default=f"configs/{spec.name}.yaml", help="Arquivo YAML do experimento")
    p.add_argument("overrides", nargs="*", help="Overrides opcionais chave=valor (ex.: params.learning_rate=0.03)")
    args = p.parse_args(argv)

    path = Path(args.config)
    if not path.exists():
        raise SystemExit(f"Config não encontrada: {path}")

    cfg = OmegaConf.merge(
        OmegaConf.structured(ExperimentConfig),
        OmegaConf.load(path),
        OmegaConf.from_dotlist(args.overrides),
    )
    _validate(cfg, stage)
    logging.getLogger(__name__).info("Config: %s%s", path, f" | overrides: {args.overrides}" if args.overrides else "")
    return cfg


def merge_params(spec: ModelSpec, task: str, cfg: DictConfig) -> dict[str, Any]:
    """Hiperparâmetros finais: padrões do ``model.py`` ← ``params`` do YAML."""
    defaults = OmegaConf.create(spec.default_params(task, cfg.seed))
    return OmegaConf.to_container(OmegaConf.merge(defaults, cfg.params), resolve=True)


def to_yaml(cfg: DictConfig) -> str:
    return OmegaConf.to_yaml(cfg, resolve=True)


def _validate(cfg: DictConfig, stage: str) -> None:
    if cfg.data.task not in ("auto", *TASKS):
        raise SystemExit(f"data.task inválido: {cfg.data.task!r} (use auto, {', '.join(TASKS)})")
    if stage in ("train", "benchmark") and not cfg.data.demo and not (cfg.data.path and cfg.data.target):
        raise SystemExit("Defina data.path e data.target na config (ou data.demo: true).")
    if stage == "inference" and not (cfg.inference.input and cfg.inference.output):
        raise SystemExit("Defina inference.input e inference.output na config.")
