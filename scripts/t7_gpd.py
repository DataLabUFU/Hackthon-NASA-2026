"""GPD nos 20 pontos (safra out–mar, 2000–2021): ajuste, diagnóstico, tendência e estabilidade.

Para chuva em 3 dias e queda de T2M em 2 dias, por ponto:
- limiar u (quantil da safra), declustering, λ (grupos por safra) e θ (índice extremal);
- σ, ξ, diagnóstico (correlação do gráfico de probabilidade, KS);
- P(máximo da safra passar do limiar da torre) pela GPD e pela contagem empírica, com IC;
- níveis de retorno (GPD, com IC; e empírico);
- teste de tendência na escala (σ(t)) e teste de estabilidade GPD × empírico;
- sensibilidade de ξ ao limiar.

Uso, a partir da raiz: ``python -m scripts.t7_gpd``  (leva alguns minutos)
Saída em ``artifacts/t7/gpd/`` (ignorada pelo git).
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from towers.t7_extremos import config, dados, eventos, gpd
from towers.t7_extremos.probabilidade import semente_do_ponto

ROOT = Path(__file__).resolve().parents[1]
SAIDA_PADRAO = ROOT / "artifacts" / "t7" / "gpd"


def analisar(serie: pd.DataFrame, nome: str, z_evento: float, inclusivo: bool, r: int, cfg) -> tuple[pd.DataFrame, pd.DataFrame]:
    g = cfg.gpd
    linhas, sens = [], []
    for ponto, sp in serie.groupby("PONTO", sort=True):
        sem = semente_do_ponto(cfg.bootstrap.semente, ponto)
        a = gpd.ajustar_ponto(sp, g.quantil_limiar, r)
        y = a["picos"]["pico"].to_numpy() - a["u"]
        maximos = sp.groupby("ano_safra")["valor"].max()
        acima = (maximos >= z_evento) if inclusivo else (maximos > z_evento)
        linha = {"variavel": nome, "PONTO": ponto, **{k: a[k] for k in
                 ("u", "n_safras", "n_excedencias", "n_grupos", "theta", "lam", "sigma", "xi", "ok")},
                 "limite_superior": a["u"] - a["sigma"] / a["xi"] if a["xi"] < 0 else np.inf,
                 "z_evento": z_evento, "p_empirico": float(acima.mean()),
                 "max_observado": float(maximos.max())}
        if a["ok"]:
            linha.update(gpd.diagnostico(y, a["sigma"], a["xi"]))
            linha["p_gpd"] = gpd.prob_safra(z_evento, a["u"], a["sigma"], a["xi"], a["lam"]) if z_evento >= a["u"] else np.nan
            T0 = g.periodos_retorno[0]
            bs = gpd.bootstrap_safras(sp, g.quantil_limiar, r, z_evento, T0, g.repeticoes_bootstrap, sem, cfg.bootstrap.nivel_ic)
            linha["p_gpd_ic_inf"], linha["p_gpd_ic_sup"] = bs["p_ic"]
            linha[f"z{int(T0)}_ic_inf"], linha[f"z{int(T0)}_ic_sup"] = bs["z_ic"]
            linha["falhas_bootstrap"] = bs["falhas"]
            for T in g.periodos_retorno:
                linha[f"z{int(T)}_gpd"] = gpd.nivel_retorno(T, a["u"], a["sigma"], a["xi"], a["lam"])
                linha[f"z{int(T)}_empirico"] = gpd.nivel_retorno_empirico(maximos.to_numpy(), T)
            tt = gpd.teste_tendencia_escala(y, a["picos"]["ano_safra"].to_numpy())
            linha.update({"tend_b1": tt["b1"], "tend_deviance": tt["deviance"], "tend_p": tt["p"]})
            est = gpd.estabilidade_gpd_empirico(sp, g.quantil_limiar, r, g.estabilidade_T,
                                                g.estabilidade_repeticoes, g.estabilidade_fracao, sem)
            linha.update({f"estab_{k}": v for k, v in est.items()})
            linha["gpd_aprovada"] = bool(est["razao"] <= g.criterio_razao and est["dp_xi"] <= g.criterio_dp_xi
                                         and est["falhas"] == 0)
        linhas.append(linha)
        s = gpd.estabilidade_limiar(sp, list(g.grade_quantis), r)
        s.insert(0, "PONTO", ponto)
        s.insert(0, "variavel", nome)
        sens.append(s)
    return pd.DataFrame(linhas), pd.concat(sens, ignore_index=True)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="GPD da Torre 7")
    ap.add_argument("--config", default=None)
    ap.add_argument("--saida", default=str(SAIDA_PADRAO))
    args = ap.parse_args(argv)

    cfg = config.carregar_config(args.config)
    caminho = ROOT / cfg.referencia.arquivo
    ref = dados.filtrar_referencia(dados.ler_dados_unificados(caminho), cfg.referencia.ano_inicio, cfg.referencia.ano_fim)
    lc, lq = cfg.limiares.chuva_extrema, cfg.limiares.queda_temperatura

    chuva = gpd.serie_safra(ref, eventos.chuva_acumulada(ref, lc.janela_dias))
    queda = gpd.serie_safra(ref, eventos.queda_temperatura(ref, lq.janela_dias, lq.absoluto))
    r1, s1 = analisar(chuva, "chuva_3d", float(lc.valor), False, cfg.gpd.r_chuva, cfg)
    r2, s2 = analisar(queda, "queda_2d", float(lq.valor), True, cfg.gpd.r_queda, cfg)
    res = pd.concat([r1, r2], ignore_index=True)
    sens = pd.concat([s1, s2], ignore_index=True)

    saida = Path(args.saida)
    saida.mkdir(parents=True, exist_ok=True)
    referencia_cols = ["PONTO", "LAT", "LON"]
    res = res.merge(dados.ler_pontos(), on="PONTO", how="left")
    res = res[["variavel", *referencia_cols] + [c for c in res.columns if c not in ("variavel", *referencia_cols)]]
    res.round(4).to_csv(saida / "gpd_por_ponto.csv", index=False)
    sens.round(4).to_csv(saida / "gpd_sensibilidade_limiar.csv", index=False)
    (saida / "metadata.json").write_text(json.dumps({
        "gerado_em": datetime.now().isoformat(timespec="seconds"),
        "sha256_dados": dados.hash_arquivo(caminho),
        "safra": "01/10 a 31/03", "anos": [int(ref["YEAR"].min()), int(ref["YEAR"].max())],
        "gpd": dict(cfg.gpd),
    }, indent=2, ensure_ascii=False, default=list), encoding="utf-8")

    pd.set_option("display.width", 200)
    cols = ["n_grupos", "theta", "xi", "corr_pp", "ks_p", "p_empirico", "p_gpd", "z10_gpd", "z10_empirico",
            "tend_p", "estab_razao", "estab_dp_xi", "estab_falhas"]
    print(res.groupby("variavel")[cols].median().round(3).T.to_string())
    print("\nGPD aprovada no teste de estabilidade (pontos):", res.groupby("variavel")["gpd_aprovada"].sum().to_dict())
    print("Tendência na escala com p < 0,05 (pontos):", res.assign(t=res["tend_p"] < 0.05).groupby("variavel")["t"].sum().to_dict())
    print("KS com p < 0,05 (pontos):", res.assign(t=res["ks_p"] < 0.05).groupby("variavel")["t"].sum().to_dict())
    print(f"\nTabelas em {saida}")


if __name__ == "__main__":
    main()
