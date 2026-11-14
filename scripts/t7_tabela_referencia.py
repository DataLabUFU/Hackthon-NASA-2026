"""Gera as tabelas de referência da Torre 7 para os 20 pontos (anos até 2021).

Uso, a partir da raiz: ``python -m scripts.t7_tabela_referencia``

Saída em ``artifacts/t7/referencia/`` (ignorada pelo git), em CSV separado por vírgula:
``indicadores_decendio.csv``, ``referencia_decendio.csv``, ``referencia_safra.csv`` e
``metadata.json`` (limiares, hash do CSV, anos, versões).
"""
from __future__ import annotations

import argparse
import json
import platform
from datetime import datetime
from importlib.metadata import version
from pathlib import Path

from omegaconf import OmegaConf

from towers.t7_extremos import config, dados, referencia

ROOT = Path(__file__).resolve().parents[1]
SAIDA_PADRAO = ROOT / "artifacts" / "t7" / "referencia"


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Tabelas de referência da Torre 7")
    ap.add_argument("--config", default=None, help="YAML (padrão: configs/extremos.yaml)")
    ap.add_argument("--saida", default=str(SAIDA_PADRAO))
    args = ap.parse_args(argv)

    cfg = config.carregar_config(args.config)
    caminho = ROOT / cfg.referencia.arquivo
    ref = dados.filtrar_referencia(dados.ler_dados_unificados(caminho), cfg.referencia.ano_inicio, cfg.referencia.ano_fim)

    diarios = referencia.indicadores_diarios(ref, cfg)
    ind = referencia.tabela_indicadores(ref, diarios)
    dec = referencia.tabela_decendio(ind, cfg)
    saf = referencia.tabela_safra(ref, diarios, cfg)

    saida = Path(args.saida)
    saida.mkdir(parents=True, exist_ok=True)
    ind.to_csv(saida / "indicadores_decendio.csv", index=False)
    dec.round(4).to_csv(saida / "referencia_decendio.csv", index=False)
    saf.round(4).to_csv(saida / "referencia_safra.csv", index=False)
    meta = {
        "gerado_em": datetime.now().isoformat(timespec="seconds"),
        "arquivo_dados": cfg.referencia.arquivo,
        "sha256_dados": dados.hash_arquivo(caminho),
        "anos": [int(ref["YEAR"].min()), int(ref["YEAR"].max())],
        "limiares": OmegaConf.to_container(cfg.limiares, resolve=True),
        "bootstrap": OmegaConf.to_container(cfg.bootstrap, resolve=True),
        "versoes": {"python": platform.python_version(),
                    **{p: version(p) for p in ("pandas", "numpy", "omegaconf")}},
    }
    (saida / "metadata.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    resumo = saf.pivot(index="PONTO", columns="evento", values="p_clim")[list(referencia.EVENTOS)]
    print("P(>=1 evento na safra out–mar), por ponto:")
    print(resumo.round(2).to_string())
    print(f"\nTabelas em {saida}")


if __name__ == "__main__":
    main()
