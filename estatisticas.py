"""Dados do painel "Acessar estatísticas": o que está por trás das recomendações, explicado ao produtor.

    painel(e, resultado) → {"clima": ..., "agua": ..., "solo": ..., "zarc": ..., "notas": ..., "fontes": [...]}

Cada bloco traz os dados do gráfico e frases prontas (``leitura``) que dizem o que o número significa para o
plantio. Um bloco sem dado vem como None e o app simplesmente não o mostra. Nada aqui recalcula as torres:
clima e solo vêm dos mesmos caches (NASA POWER, SoilGrids) e as notas vêm do resultado já gerado.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

import polars as pl

log = logging.getLogger(__name__)

MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
MESES_LONGOS = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro",
                "outubro", "novembro", "dezembro"]
MES_SECO_MM = 50
# classe WRB (SoilGrids) → nome mais próximo no Sistema Brasileiro de Classificação de Solos (aproximação)
WRB_PARA_SIBCS = {
    "Ferralsols": "Latossolo", "Acrisols": "Argissolo", "Lixisols": "Argissolo", "Alisols": "Argissolo",
    "Arenosols": "Neossolo Quartzarênico", "Cambisols": "Cambissolo", "Gleysols": "Gleissolo",
    "Fluvisols": "Neossolo Flúvico", "Leptosols": "Neossolo Litólico", "Regosols": "Neossolo Regolítico",
    "Nitisols": "Nitossolo", "Plinthosols": "Plintossolo", "Vertisols": "Vertissolo", "Planosols": "Planossolo",
    "Podzols": "Espodossolo", "Histosols": "Organossolo", "Luvisols": "Luvissolo", "Phaeozems": "Chernossolo",
    "Chernozems": "Chernossolo", "Kastanozems": "Chernossolo", "Solonetz": "Planossolo Nátrico",
    "Solonchaks": "Gleissolo Sálico", "Stagnosols": "Planossolo", "Umbrisols": "Cambissolo Húmico",
    "Andosols": "Andossolo", "Calcisols": "Cambissolo", "Durisols": "Cambissolo", "Gypsisols": "Cambissolo",
    "Cryosols": "Criossolo", "Albeluvisols": "Luvissolo",
}
FONTES = [
    "Clima: NASA POWER (chuva do satélite GPM IMERG desde 2001; temperatura e umidade do solo do MERRA-2).",
    "Solo: SoilGrids 2.0 (ISRIC), mapas globais de 250 m a 1 km; não substitui a análise de solo da sua área.",
    "Zoneamento: ZARC/MAPA, Tábua de Risco da safra vigente (decêndios de 10 dias).",
    "Exigências das culturas: ECOCROP/FAO e FAO-56 (consumo de água), com ajustes da Embrapa.",
    "Extremos (Torre 7): chuva > 80 mm em 3 dias e queda de 5 °C em 2 dias (limiares provisórios), NASA POWER.",
]


def _mm(v: float) -> str:
    """1540.3 → '1.540' (milhar com ponto, como no Brasil)."""
    return f"{v:,.0f}".replace(",", ".")


def _lista_meses(idx: list[int]) -> str:
    nomes = [MESES_LONGOS[i - 1] for i in idx]
    return nomes[0] if len(nomes) == 1 else ", ".join(nomes[:-1]) + " e " + nomes[-1]


def _meses_do_ciclo(plantio: date, ciclo_dias: int) -> list[int]:
    meses, d = [], plantio
    while d <= plantio + timedelta(days=ciclo_dias):
        if d.month not in meses:
            meses.append(d.month)
        d += timedelta(days=10)
    return meses


# --- clima -------------------------------------------------------------------------------------

def clima(lat: float, lon: float, ciclo: dict | None = None) -> dict | None:
    """Médias mensais (chuva, temperatura média, mínima e máxima) e a leitura para o produtor."""
    from towers.data.power import CHUVA, PARAMS_T2, clima_diario
    c = clima_diario(lat, lon, params=PARAMS_T2)
    ano_fim = c.filter(pl.col(CHUVA).is_not_null())["data"].max().year
    completos = c.filter(pl.col("data").dt.year().is_between(c["data"].min().year, ano_fim - 1))
    chuva = (completos.group_by(a=pl.col("data").dt.year(), m=pl.col("data").dt.month()).agg(pl.col(CHUVA).sum())
             .group_by("m").agg(chuva=pl.col(CHUVA).mean()))
    temp = c.group_by(m=pl.col("data").dt.month()).agg(
        t=pl.col("T2M").mean(), tmin=pl.col("T2M_MIN").mean(), tmax=pl.col("T2M_MAX").mean())
    mensal = chuva.join(temp, on="m").sort("m")
    a0, a1 = completos["data"].min().year, completos["data"].max().year

    v = {r["m"]: r for r in mensal.iter_rows(named=True)}
    anual = sum(r["chuva"] for r in v.values())
    secos = [m for m in range(1, 13) if v[m]["chuva"] < MES_SECO_MM]
    chuvosos = sorted(range(1, 13), key=lambda m: -v[m]["chuva"])[:6]
    pct_6 = 100 * sum(v[m]["chuva"] for m in chuvosos) / anual
    frio = min(v, key=lambda m: v[m]["t"])
    quente = max(v, key=lambda m: v[m]["t"])
    leitura = [
        f"Chove em média {_mm(anual)} mm por ano."
        + (f" {len(secos)} meses são secos (menos de {MES_SECO_MM} mm): {_lista_meses(sorted(secos))}."
           if secos else " Nenhum mês tem menos de 50 mm: chuva bem distribuída no ano."),
        f"Os 6 meses mais chuvosos concentram {pct_6:.0f}% da chuva do ano.",
        f"O mês mais frio é {MESES_LONGOS[frio - 1]} (mínimas médias de {v[frio]['tmin']:.0f} °C) e o mais quente "
        f"é {MESES_LONGOS[quente - 1]} (máximas médias de {v[quente]['tmax']:.0f} °C).",
    ]

    # últimos 12 meses completos x média
    fim = c.filter(pl.col(CHUVA).is_not_null())["data"].max()
    fim_mes = fim.replace(day=1) - timedelta(days=1)
    ini = (fim_mes.replace(day=1) - timedelta(days=330)).replace(day=1)
    ult = c.filter(pl.col("data").is_between(ini, fim_mes))[CHUVA].sum()
    desvio = 100 * (ult - anual) / anual
    leitura.append(f"De {MESES[ini.month - 1]}/{ini.year} a {MESES[fim_mes.month - 1]}/{fim_mes.year} choveu "
                   f"{_mm(ult)} mm, {abs(desvio):.0f}% {'acima' if desvio >= 0 else 'abaixo'} da média.")

    meses_ciclo = []
    if ciclo and ciclo.get("plantio") and ciclo.get("ciclo_dias"):
        meses_ciclo = _meses_do_ciclo(ciclo["plantio"], int(ciclo["ciclo_dias"]))
        mm = sum(v[m]["chuva"] for m in meses_ciclo)
        leitura.append(f"O ciclo de {ciclo['cultura']} (plantio em {ciclo['plantio']:%d/%m}, cerca de "
                       f"{ciclo['ciclo_dias']} dias) passa por {_lista_meses(meses_ciclo)}, meses que somam em média "
                       f"{_mm(mm)} mm de chuva.")
    tabela = mensal.select(
        mes=pl.col("m").map_elements(lambda m: MESES[m - 1], return_dtype=pl.String), num=pl.col("m"),
        chuva_mm=pl.col("chuva").round(0), temp_c=pl.col("t").round(1), tmin_c=pl.col("tmin").round(1),
        tmax_c=pl.col("tmax").round(1), no_ciclo=pl.col("m").is_in(meses_ciclo))
    return {"mensal": tabela.to_dicts(), "anos": f"{a0}–{a1}", "chuva_anual": round(anual),
            "meses_secos": len(secos), "temp_media": round(sum(r["t"] for r in v.values()) / 12, 1),
            "leitura": leitura, "ciclo": ciclo}


def agua_no_solo(lat: float, lon: float) -> dict | None:
    """Umidade do solo na zona das raízes hoje x o normal para esta época (GWETROOT, NASA POWER)."""
    from towers.data.power import PARAMS_T2, clima_diario
    c = clima_diario(lat, lon, params=PARAMS_T2).drop_nulls("GWETROOT")
    if c.is_empty():
        return None
    hoje = c["data"].max()
    atual = c.filter(pl.col("data") > hoje - timedelta(days=7))["GWETROOT"].mean()
    doy = hoje.timetuple().tm_yday
    janela = c.filter(
        ((pl.col("data").dt.ordinal_day() - doy).abs() <= 15) & (pl.col("data").dt.year() < hoje.year)
    ).group_by(pl.col("data").dt.year()).agg(pl.col("GWETROOT").mean())["GWETROOT"]
    if janela.is_empty():
        return None
    pct_anos_mais_secos = 100 * (janela < atual).mean()
    normal = janela.median()
    if pct_anos_mais_secos <= 25:
        situacao = "mais seco que o normal"
        conselho = "Plantar no seco aumenta o risco de falha na germinação: espere chuvas que reponham o solo."
    elif pct_anos_mais_secos >= 75:
        situacao = "mais úmido que o normal"
        conselho = "Boa reserva de água para o início do ciclo."
    else:
        situacao = "perto do normal"
        conselho = "Reserva de água dentro do esperado para a época."
    return {"data": hoje, "atual_pct": round(100 * atual), "normal_pct": round(100 * normal),
            "pct_anos_mais_secos": round(pct_anos_mais_secos), "situacao": situacao,
            "leitura": [f"Na semana até {hoje:%d/%m/%Y}, o solo na zona das raízes está {situacao} para esta época "
                        f"(umidade {100 * atual:.0f}%, contra {100 * normal:.0f}% num ano típico; "
                        + ("o mais seco para a época desde 2001)." if pct_anos_mais_secos == 0 else
                           "o mais úmido para a época desde 2001)." if pct_anos_mais_secos == 100 else
                           f"mais seco do que em {100 - pct_anos_mais_secos:.0f}% dos anos desde 2001)."),
                        conselho]}


# --- solo --------------------------------------------------------------------------------------

def solo(lat: float, lon: float) -> dict | None:
    from towers.data import soilgrids
    from towers.data.ptf_zarc import agua_disponivel
    t, q, c = soilgrids.textura(lat, lon), soilgrids.quimica(lat, lon), soilgrids.classe_wrb(lat, lon)
    if not (t or q or c):
        return None
    leitura = []
    out: dict = {"textura": None, "quimica": q, "classe": None}
    if t:
        ad = agua_disponivel(t["areia"], t["silte"], t["argila"])
        out["textura"] = {k: round(t[k]) for k in ("areia", "silte", "argila")} | {
            "classe_ad": ad.get("classe_ad"), "ad_mm_cm": ad.get("ad_mm_cm")}
        if t["argila"] >= 35:
            leitura.append(f"Solo argiloso ({t['argila']:.0f}% de argila): guarda bem água e nutrientes, mas compacta "
                           "com máquinas em solo úmido.")
        elif t["areia"] >= 70:
            leitura.append(f"Solo arenoso ({t['areia']:.0f}% de areia): drena rápido e guarda pouca água; a palhada e "
                           "a matéria orgânica fazem muita diferença.")
        else:
            leitura.append(f"Textura média ({t['argila']:.0f}% de argila, {t['areia']:.0f}% de areia): bom equilíbrio "
                           "entre drenagem e retenção de água.")
        if ad.get("ad_mm_cm"):
            classe = str(ad.get("classe_ad") or "").split(" (")[0]
            leitura.append(f"Água disponível: cerca de {10 * ad['ad_mm_cm']:.0f} mm a cada 10 cm de solo "
                           f"(classe {classe} no zoneamento oficial).")
    if q:
        ph, ctc = q["ph"], q["ctc"]
        leitura.append(f"pH {ph:.1f}: " + ("ácido; em geral precisa de calagem (confirme com análise de solo)."
                                          if ph < 5.5 else "adequado para a maioria das culturas." if ph <= 6.8
                                          else "alcalino; atenção à disponibilidade de micronutrientes."))
        leitura.append(f"CTC {ctc:.1f} cmol/kg: " + ("baixa; o solo segura poucos nutrientes, prefira adubar em "
                                                     "parcelas." if ctc < 5 else "média." if ctc <= 15
                                                     else "alta; boa capacidade de reter nutrientes."))
    if c:
        nome = WRB_PARA_SIBCS.get(c["wrb"], c["wrb"])
        prob = (c.get("wrb_probabilidades") or [[None, None]])[0][1]
        out["classe"] = {"wrb": c["wrb"], "sibcs": nome, "prob": prob}
        leitura.append(f"Tipo de solo mais provável: {nome} ({c['wrb']} na classificação internacional"
                       + (f", {prob}% de probabilidade" if prob else "") + ").")
    out["leitura"] = leitura
    return out


# --- ZARC --------------------------------------------------------------------------------------

def calendario_zarc(geocodigo: str, culturas: list[dict], data_plantio: date) -> dict | None:
    """Risco do ZARC por decêndio para as culturas zoneadas entre as recomendadas."""
    from towers.data.zarc import decendio, indicacao_por_decendio, zarc_disponivel
    if not zarc_disponivel():
        return None
    ids = {c["id_cultura"]: c["nome_pt"] for c in culturas}
    ind = indicacao_por_decendio([geocodigo]).filter(pl.col("id_cultura").is_in(list(ids)))
    if ind.is_empty():
        return None
    linhas = [{"cultura": ids[r["id_cultura"]], "dec": int(r["dec"]),
               "risco": int(r["melhor_risco"]) if r["indicado"] else 0} for r in ind.iter_rows(named=True)]
    dec = decendio(data_plantio)
    nomes = list(dict.fromkeys(ids[i] for i in ids if i in set(ind["id_cultura"])))[:6]
    linhas = [x for x in linhas if x["cultura"] in nomes]
    leitura = ["Cada quadrado é um decêndio (10 dias). Quanto mais escuro o verde, menor o risco de perda de "
               "produção; bege = plantio não indicado pelo zoneamento oficial nesta época.",
               "Plantar dentro da janela do ZARC é exigido para o Proagro e o seguro rural com subvenção."]
    for n in nomes:
        r = next((x["risco"] for x in linhas if x["cultura"] == n and x["dec"] == dec), 0)
        leitura.append(f"{n} na data planejada: " + (f"indicado, risco de até {r}%." if r else "fora da janela."))
    return {"linhas": linhas, "decendio_plantio": dec, "culturas": nomes, "leitura": leitura}


# --- painel ------------------------------------------------------------------------------------

def _culturas_zarc(e, notas: list[dict]) -> list[dict]:
    """Culturas do calendário: recomendadas e desejada, depois as do histórico do produtor, depois as demais."""
    from towers.data.culturas import carregar_culturas
    from towers.t5_rotacao.torre import resolver_cultura
    ordem = [n for n in notas if n["setor"] in ("desejada", "melhores")]
    lista = [{"id_cultura": n["id_cultura"], "nome_pt": n["cultura"]} for n in ordem]
    cat = None
    for nome in (e.ultimo, e.penultimo):
        if nome and nome.casefold() != "pousio":
            cat = cat if cat is not None else carregar_culturas().filter("exibivel")
            try:
                c = resolver_cultura(nome, cat)
                lista.append({"id_cultura": c["id_cultura"], "nome_pt": c["nome_pt"]})
            except ValueError:
                pass
    lista += [{"id_cultura": n["id_cultura"], "nome_pt": n["cultura"]} for n in notas if n not in ordem]
    vistos, saida = set(), []
    for c in lista:
        if c["id_cultura"] not in vistos:
            vistos.add(c["id_cultura"])
            saida.append(c)
    return saida


def painel(e, resultado=None) -> dict:
    """Todos os blocos do painel para a entrada ``e`` (e o resultado, se já houver)."""
    from motor import localizar_municipio
    mun = localizar_municipio(e.uf, e.cidade)
    if mun is None:
        return {"erro": "Escolha o estado e o município para ver as estatísticas da região."}
    det = (getattr(resultado, "detalhes", None) or {}) if resultado is not None else {}
    notas = det.get("notas") or []
    # ciclo mostrado no gráfico de chuva: a cultura desejada (se viável), senão a 1ª recomendada
    primeira = next((n for n in notas if n["desejada"] and not n["eliminada"]), None) or         next((n for n in notas if n["setor"] == "melhores"), None)
    ciclo = ({"cultura": primeira["cultura"], "plantio": primeira["plantio"], "ciclo_dias": primeira["ciclo_dias"]}
             if primeira and primeira.get("ciclo_dias") else None)
    blocos: dict = {"municipio": f"{mun['nome']} - {mun['uf']}", "fontes": FONTES, "notas": notas}
    for nome, f in (("clima", lambda: clima(mun["lat"], mun["lon"], ciclo)),
                    ("agua", lambda: agua_no_solo(mun["lat"], mun["lon"])),
                    ("solo", lambda: solo(mun["lat"], mun["lon"])),
                    ("zarc", lambda: calendario_zarc(mun["geocodigo"], _culturas_zarc(e, notas),
                                                     e.data_plantio or date.today()))):
        try:
            blocos[nome] = f()
        except Exception as erro:     # um bloco sem dado não derruba o painel
            log.warning("Estatísticas: bloco %s indisponível (%s)", nome, erro)
            blocos[nome] = None
    return blocos
