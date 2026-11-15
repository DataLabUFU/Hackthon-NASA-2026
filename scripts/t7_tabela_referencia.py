"""Gera as tabelas de referência da Torre 7 para os 20 pontos (anos até 2021).

Uso, a partir da raiz::

    python -m scripts.t7_tabela_referencia              # só em artifacts/ (fora do git)
    python -m scripts.t7_tabela_referencia --publicar   # também em towers/t7_extremos/tabelas/ (vai no push)

Saída em ``artifacts/t7/referencia/`` (ignorada pelo git), em CSV separado por vírgula:
``indicadores_decendio.csv``, ``referencia_decendio.csv``, ``referencia_safra.csv`` e
``metadata.json`` (limiares, hash do CSV, anos, versões).

Com ``--publicar``, copia para ``towers/t7_extremos/tabelas/`` o que o ML usa:
``referencia_safra.csv``, ``referencia_decendio.csv``, ``gpd_por_ponto.csv`` e
``metadata.json``. O ``indicadores_decendio.csv`` (~600 KB) não é publicado; dá para gerar.
"""
from __future__ import annotations

import argparse
import json
import platform
import shutil
from datetime import datetime
from importlib.metadata import version
from pathlib import Path

from omegaconf import OmegaConf

from towers.t7_extremos import config, dados, referencia

ROOT = Path(__file__).resolve().parents[1]
SAIDA_PADRAO = ROOT / "artifacts" / "t7" / "referencia"
PUBLICAR_EM = ROOT / "towers" / "t7_extremos" / "tabelas"
PUBLICADOS = ("referencia_safra.csv", "referencia_decendio.csv", "metadata.json")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Tabelas de referência da Torre 7")
    ap.add_argument("--config", default=None, help="YAML (padrão: configs/extremos.yaml)")
    ap.add_argument("--saida", default=str(SAIDA_PADRAO))
    ap.add_argument("--publicar", action="store_true", help=f"copia as tabelas do ML para {PUBLICAR_EM}")
    args = ap.parse_args(argv)

    cfg = config.carregar_config(args.config)
    caminho = ROOT / cfg.referencia.arquivo
    ref = dados.filtrar_referencia(dados.ler_dados_unificados(caminho), cfg.referencia.ano_inicio, cfg.referencia.ano_fim)

    diarios = referencia.indicadores_diarios(ref, cfg)
    ind = referencia.tabela_indicadores(ref, diarios)
    dec = referencia.tabela_decendio(ind, cfg)
    saf = referencia.tabela_safra(ref, diarios, cfg)
    if cfg.gpd.usar_na_chuva:
        res_gpd = referencia.ler_resultado_gpd(ROOT / cfg.gpd.resultado)
        saf = referencia.aplicar_gpd_chuva(saf, res_gpd, float(cfg.limiares.chuva_extrema.valor),
                                           cfg.gpd.exigir_concordancia)

    saida = Path(args.saida)
    saida.mkdir(parents=True, exist_ok=True)
    referencia.com_coordenadas(ind).to_csv(saida / "indicadores_decendio.csv", index=False)
    referencia.com_coordenadas(dec.round(4)).to_csv(saida / "referencia_decendio.csv", index=False)
    referencia.com_coordenadas(saf.round(4)).to_csv(saida / "referencia_safra.csv", index=False)
    meta = {
        "gerado_em": datetime.now().isoformat(timespec="seconds"),
        "arquivo_dados": cfg.referencia.arquivo,
        "sha256_dados": dados.hash_arquivo(caminho),
        "anos": [int(ref["YEAR"].min()), int(ref["YEAR"].max())],
        "limiares": OmegaConf.to_container(cfg.limiares, resolve=True),
        "gpd_na_chuva": bool(cfg.gpd.usar_na_chuva),
        "gpd_exigir_concordancia": bool(cfg.gpd.exigir_concordancia),
        "pontos_chuva_gpd": sorted(saf.query("evento == 'chuva_extrema' and metodo == 'gpd'")["PONTO"]),
        "bootstrap": OmegaConf.to_container(cfg.bootstrap, resolve=True),
        "versoes": {"python": platform.python_version(),
                    **{p: version(p) for p in ("pandas", "numpy", "omegaconf")}},
    }
    (saida / "metadata.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    resumo = saf.pivot(index="PONTO", columns="evento", values="p_clim")[list(referencia.EVENTOS)]
    print("P(>=1 evento na safra out–mar), por ponto:")
    print(resumo.round(2).to_string())
    print("método da chuva:", saf[saf["evento"] == "chuva_extrema"]["metodo"].value_counts().to_dict())
    print(f"\nTabelas em {saida}")

    if args.publicar:
        PUBLICAR_EM.mkdir(parents=True, exist_ok=True)
        for nome in PUBLICADOS:
            shutil.copy2(saida / nome, PUBLICAR_EM / nome)
        if cfg.gpd.usar_na_chuva:
            shutil.copy2(ROOT / cfg.gpd.resultado, PUBLICAR_EM / "gpd_por_ponto.csv")
        print(f"Publicadas em {PUBLICAR_EM} (entram no próximo commit/push)")


if __name__ == "__main__":
    main()
