"""Validação da Torre 7: tendência por ponto e sensibilidade à janela de referência.

1. Tendência (Mann-Kendall + Sen, Holm por ponto) em seis séries anuais, 2000–2021.
2. Janela: P(>=1 evento na safra out–mar) com 2000–2021, 2007–2021, 2000–2010 e 2011–2021.
   Se houver tendência, janelas diferentes dão probabilidades diferentes.

Uso, a partir da raiz: ``python -m scripts.t7_validacao``
Saída em ``artifacts/t7/validacao/`` (ignorada pelo git).
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from towers.t7_extremos import config, dados, referencia, tendencia
from towers.t7_extremos import probabilidade as prob

ROOT = Path(__file__).resolve().parents[1]
SAIDA_PADRAO = ROOT / "artifacts" / "t7" / "validacao"
JANELAS = {"2000-2021": (2000, 2021), "2007-2021": (2007, 2021), "2000-2010": (2000, 2010), "2011-2021": (2011, 2021)}


def janelas(df: pd.DataFrame, cfg) -> pd.DataFrame:
    """p_clim por ponto, evento e janela de anos (safras inteiramente dentro da janela)."""
    b = cfg.bootstrap
    partes = []
    for nome, (a, z) in JANELAS.items():
        ref = dados.filtrar_referencia(df, a, z)
        diarios = referencia.indicadores_diarios(ref, cfg)
        por_ano = {k: prob.indicador_por_safra(ref, v, *referencia.SAFRA).set_index(["PONTO", "ano_safra"])["evento"]
                   for k, v in diarios.items()}
        por_ano["algum"] = prob.combinar_algum(por_ano["chuva_extrema"], por_ano["queda_brusca"])
        for ev, s in por_ano.items():
            t = prob.tabela_por_safra(s.rename("evento").reset_index(), b.repeticoes, b.semente, b.nivel_ic)
            t.insert(1, "evento", ev)
            t.insert(2, "janela", nome)
            partes.append(t)
    return pd.concat(partes, ignore_index=True)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Validação da Torre 7")
    ap.add_argument("--config", default=None)
    ap.add_argument("--saida", default=str(SAIDA_PADRAO))
    args = ap.parse_args(argv)

    cfg = config.carregar_config(args.config)
    caminho = ROOT / cfg.referencia.arquivo
    df = dados.ler_dados_unificados(caminho)
    ref = dados.filtrar_referencia(df, cfg.referencia.ano_inicio, cfg.referencia.ano_fim)
    saida = Path(args.saida)
    saida.mkdir(parents=True, exist_ok=True)

    # 1. tendência
    anuais = tendencia.series_anuais(ref, cfg.limiares.chuva_extrema.janela_dias)
    tend = tendencia.tendencias_por_ponto(anuais)
    anuais.to_csv(saida / "series_anuais.csv", index=False)
    tend.round(5).to_csv(saida / "tendencia_por_ponto.csv", index=False)
    resumo_t = tend.groupby("serie").agg(
        media=("media", "median"),
        sen_mediana=("sen_por_ano", "median"),
        pontos_sig_holm=("significativo", "sum"),
        pontos_sig_subindo=("significativo", lambda s: int((s & (tend.loc[s.index, "sen_por_ano"] > 0)).sum())),
        pontos_sig_descendo=("significativo", lambda s: int((s & (tend.loc[s.index, "sen_por_ano"] < 0)).sum())),
        pontos_p_bruto_05=("p", lambda p: int((p < 0.05).sum())),
        autocorr_resid_mediana=("autocorr_resid", "median"),
    ).round(3)
    resumo_t.to_csv(saida / "tendencia_resumo.csv")

    # 2. janelas
    jan = janelas(df, cfg)
    jan.round(4).to_csv(saida / "janelas_por_ponto.csv", index=False)
    w = jan.pivot_table(index=["evento", "PONTO"], columns="janela", values="p_clim")
    w["dif_2011_menos_2000"] = w["2011-2021"] - w["2000-2010"]
    resumo_j = w.groupby("evento").agg(["median", "min", "max"]).round(3)
    resumo_j.to_csv(saida / "janelas_resumo.csv")
    n_por_janela = jan.groupby("janela")["n_anos"].median().to_dict()

    (saida / "metadata.json").write_text(json.dumps({
        "gerado_em": datetime.now().isoformat(timespec="seconds"),
        "sha256_dados": dados.hash_arquivo(caminho),
        "janelas": JANELAS, "safras_por_janela": n_por_janela,
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    pd.set_option("display.width", 160)
    print("Tendência 2000–2021 (20 pontos; Holm por ponto, 6 séries):")
    print(resumo_t.to_string())
    print("\nP06:")
    print(tend.query("PONTO == 'P06'")[["serie", "sen_por_ano", "sen_ic_inf", "sen_ic_sup", "p", "p_holm",
                                        "variacao_periodo", "media", "autocorr_resid"]].round(3).to_string(index=False))
    print("\nJanela de referência (P na safra out–mar; mediana entre pontos):")
    print(w.groupby("evento").median().round(3).to_string())
    print("safras por janela:", n_por_janela)
    print(f"\nTabelas em {saida}")


if __name__ == "__main__":
    main()
