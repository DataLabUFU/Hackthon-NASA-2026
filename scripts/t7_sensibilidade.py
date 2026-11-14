"""Sensibilidade dos limiares da Torre 7 nos 20 pontos.

Para cada limiar de uma grade, calcula por ponto P(pelo menos um evento na safra out–mar)
com IC de 95%. Um bom limiar deixa p longe de 0 e de 1. Para a queda de temperatura, também
descreve os eventos (sazonalidade, agrupamento, dias secos e chuvosos).

Uso, a partir da raiz: ``python -m scripts.t7_sensibilidade``

Saída em ``artifacts/t7/sensibilidade/`` (ignorada pelo git). Só usa anos até 2021.
"""
from __future__ import annotations

import argparse
import json
import platform
from datetime import datetime
from importlib.metadata import version
from pathlib import Path

import numpy as np
import pandas as pd

from towers.t7_extremos import config, dados, eventos, probabilidade as prob

ROOT = Path(__file__).resolve().parents[1]
SAIDA_PADRAO = ROOT / "artifacts" / "t7" / "sensibilidade"

SAFRA = ((10, 1), (3, 31))                                  # outubro a março
GRADE_CHUVA_MM = [50, 60, 70, 80, 90, 100, 110, 120, 130]   # pontos de análise, não limiares escolhidos
DIA_SECO_MM = 1.0       # dia com menos de 1 mm conta como seco
DIA_CHUVOSO_MM = 10.0   # dia com 10 mm ou mais conta como chuvoso


def sensibilidade_safra(ref, medida, grade, cfg, inclusivo) -> pd.DataFrame:
    """Probabilidade por ponto (safra out–mar) para cada limiar da grade."""
    b = cfg.bootstrap
    partes = []
    for limiar in grade:
        ind = eventos.indicador_evento(medida, limiar, inclusivo=inclusivo)
        safra = prob.indicador_por_safra(ref, ind, *SAFRA)
        tab = prob.tabela_por_safra(safra, b.repeticoes, b.semente, b.nivel_ic)
        tab.insert(1, "limiar", limiar)
        partes.append(tab)
    return pd.concat(partes, ignore_index=True)


def resumo_grade(tab: pd.DataFrame) -> pd.DataFrame:
    """Resumo entre pontos: mediana, mínimo e máximo de p e quantos ficam entre 0,1 e 0,9."""
    g = tab.groupby("limiar")
    return pd.DataFrame({
        "p_mediana": g["p_clim"].median(),
        "p_min": g["p_clim"].min(),
        "p_max": g["p_clim"].max(),
        "pontos_p_entre_0.1_e_0.9": g["p_clim"].apply(lambda p: int(((p >= 0.1) & (p <= 0.9)).sum())),
        "largura_ic_mediana": (g["ic_sup"].median() - g["ic_inf"].median()),
        "n_anos": g["n_anos"].median(),
    }).round(3)


def caracteristicas_queda(ref, queda, limiares) -> pd.DataFrame:
    """Por ponto e limiar, nos dias de out–mar:

    - ``r2_mes``: quanto o mês explica da queda diária (0 = sem sazonalidade);
    - ``autocorr_eventos``: correlação entre evento hoje e ontem (0 = não se agrupam);
    - ``frac_dia_seco`` / ``frac_dia_chuvoso``: eventos em dias com < 1 mm / >= 10 mm;
    - ``limiar_5pct_dias`` / ``p_safra_limiar_5pct``: queda superada em 5% dos dias e a
      probabilidade por safra com esse limiar.
    """
    mes = ref["data"].dt.month
    na_safra = mes.isin([10, 11, 12, 1, 2, 3])
    linhas = []
    for ponto, idx in ref[na_safra].groupby("PONTO").groups.items():
        q = queda.loc[idx]
        m = mes.loc[idx]
        chuva = ref.loc[idx, "PRECTOTCORR"]
        ok = q.notna()
        media_mes = q[ok].groupby(m[ok]).transform("mean")
        r2_mes = 1 - ((q[ok] - media_mes) ** 2).sum() / ((q[ok] - q[ok].mean()) ** 2).sum()
        lim5 = float(q[ok].quantile(0.95))
        for limiar in limiares:
            ev = (q >= limiar) & ok
            n_ev = int(ev.sum())
            linhas.append({
                "PONTO": ponto, "limiar": limiar, "n_eventos": n_ev,
                "r2_mes": r2_mes,
                "autocorr_eventos": ev.astype(float).autocorr(1) if n_ev else np.nan,
                "frac_dia_seco": (chuva[ev] < DIA_SECO_MM).mean() if n_ev else np.nan,
                "frac_dia_chuvoso": (chuva[ev] >= DIA_CHUVOSO_MM).mean() if n_ev else np.nan,
                "limiar_5pct_dias": lim5,
            })
    out = pd.DataFrame(linhas)
    # probabilidade por safra usando, em cada ponto, o limiar superado em 5% dos dias
    p5 = []
    for ponto, lim5 in out.groupby("PONTO")["limiar_5pct_dias"].first().items():
        sub = ref["PONTO"] == ponto
        ind = eventos.indicador_evento(queda[sub], lim5)
        s = prob.indicador_por_safra(ref[sub], ind, *SAFRA)
        p5.append({"PONTO": ponto, "p_safra_limiar_5pct": s["evento"].mean()})
    return out.merge(pd.DataFrame(p5), on="PONTO")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", default=None, help="YAML de configuração (padrão: configs/extremos.yaml)")
    ap.add_argument("--saida", default=str(SAIDA_PADRAO))
    args = ap.parse_args(argv)

    cfg = config.carregar_config(args.config)
    caminho = ROOT / cfg.referencia.arquivo
    ref = dados.filtrar_referencia(dados.ler_dados_unificados(caminho), cfg.referencia.ano_inicio, cfg.referencia.ano_fim)
    saida = Path(args.saida)
    saida.mkdir(parents=True, exist_ok=True)

    lq = cfg.limiares.queda_temperatura
    grade_queda = list(lq.grade_sensibilidade)
    queda = eventos.queda_temperatura(ref, lq.janela_dias, lq.absoluto)
    chuva = eventos.chuva_acumulada(ref, cfg.limiares.chuva_extrema.janela_dias)
    grade_chuva = list(cfg.limiares.chuva_extrema.grade_sensibilidade) or GRADE_CHUVA_MM

    tq = sensibilidade_safra(ref, queda, grade_queda, cfg, inclusivo=True)
    tc = sensibilidade_safra(ref, chuva, grade_chuva, cfg, inclusivo=False)
    car = caracteristicas_queda(ref, queda, grade_queda)

    tq.to_csv(saida / "queda_por_ponto.csv", index=False)
    tc.to_csv(saida / "chuva_por_ponto.csv", index=False)
    car.to_csv(saida / "queda_caracteristicas.csv", index=False)
    rq, rc = resumo_grade(tq), resumo_grade(tc)
    rq.to_csv(saida / "queda_resumo.csv")
    rc.to_csv(saida / "chuva_resumo.csv")

    meta = {
        "gerado_em": datetime.now().isoformat(timespec="seconds"),
        "arquivo_dados": str(cfg.referencia.arquivo),
        "sha256_dados": dados.hash_arquivo(caminho),
        "anos": [int(ref["YEAR"].min()), int(ref["YEAR"].max())],
        "safra": "01/10 a 31/03",
        "bootstrap": dict(cfg.bootstrap),
        "versoes": {"python": platform.python_version(),
                    **{p: version(p) for p in ("pandas", "numpy", "omegaconf")}},
    }
    (saida / "metadata.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    pd.set_option("display.width", 140)
    print(f"\nQueda de T2M em {lq.janela_dias} dias (>= limiar, °C), P(>=1 evento na safra out–mar):")
    print(rq.to_string())
    print(f"\nChuva em {cfg.limiares.chuva_extrema.janela_dias} dias (> limiar, mm), P(>=1 evento na safra out–mar):")
    print(rc.to_string())
    print("\nCaracterísticas dos eventos de queda (mediana entre pontos):")
    print(car.groupby("limiar")[["n_eventos", "r2_mes", "autocorr_eventos", "frac_dia_seco", "frac_dia_chuvoso",
                                  "limiar_5pct_dias", "p_safra_limiar_5pct"]].median().round(3).to_string())
    print(f"\nTabelas em {saida}")


if __name__ == "__main__":
    main()
