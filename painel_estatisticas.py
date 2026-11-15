"""Painel "Acessar estatísticas" do RotaSafra (Streamlit + Altair). Os dados vêm de ``estatisticas.painel``.

Regras visuais: um eixo por gráfico; uma cor por medida (chuva azul, temperatura laranja, risco do ZARC em
verdes do app, do escuro = menor risco ao bege = não indicado); textos e eixos nas cores de texto do app;
tooltip em todas as marcas; cada gráfico vem com a leitura em frases (o que o número significa para o plantio).
"""
from __future__ import annotations

from html import escape

import altair as alt
import pandas as pd
import streamlit as st

import estatisticas as es

TEXTO, TEXTO_2, GRADE = "#283b2b", "#5b6b5c", "#e5dccb"
CHUVA, CHUVA_FORA = "#2a78d6", "#a9c7ee"
TEMP = "#eb6834"
MARCA = "#e9bd45"        # amarelo do app: marca a data do produtor
RISCO = {"Até 20%": "#23452f", "Até 30%": "#477b43", "Até 40%": "#8db38a", "Até 50%": "#c3d9bf",
         "Não indicado": "#efe6d3"}
NOMES_CRITERIOS = {"t1": "Clima", "t2": "Água", "t3": "Solo", "t4": "ZARC", "t5": "Rotação",
                   "aderencia": "Seus objetivos", "aptidao_local": "Aptidão do local", "nota": "Nota final"}

CSS = """<style>
.st-key-painel_stats{background:#fffdf7;border:1px solid #d8c9a8;border-radius:16px;padding:26px 30px 30px;
  margin-top:18px}
.ps-titulo{font-size:26px;font-weight:800;color:#23452f;margin:0 0 4px}
.ps-sub{font-size:15px;color:#5b6b5c;margin:0 0 18px;line-height:1.55}
.ps-tiles{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:4px 0 8px}
.ps-tile{background:#f7f1e3;border:1px solid #e5dccb;border-radius:12px;padding:14px 16px}
.ps-tile-rot{font-size:13px;color:#5b6b5c;font-weight:600;margin-bottom:4px}
.ps-tile-val{font-size:26px;font-weight:800;color:#283b2b;line-height:1.15}
.ps-tile-det{font-size:13px;color:#5b6b5c;margin-top:4px;line-height:1.4}
.ps-bloco{font-size:19px;font-weight:800;color:#23452f;margin:26px 0 2px;padding-top:18px;
  border-top:1px solid #e5dccb}
.ps-pergunta{font-size:14px;color:#5b6b5c;margin:0 0 10px}
.ps-graf-tit{font-size:14px;font-weight:700;color:#283b2b;margin:6px 0 0}
.ps-leitura{background:#f4f8f1;border-left:4px solid #477b43;border-radius:8px;padding:10px 14px;margin:8px 0 4px}
.ps-leitura ul{margin:0;padding-left:18px}.ps-leitura li{font-size:14.5px;color:#283b2b;line-height:1.6}
.ps-legenda{display:flex;flex-wrap:wrap;gap:14px;font-size:13px;color:#5b6b5c;margin:4px 0}
.ps-legenda span{display:inline-flex;align-items:center;gap:6px}
.ps-legenda i{width:14px;height:14px;border-radius:3px;display:inline-block;border:1px solid #d8c9a8}
.ps-fontes{font-size:13px;color:#5b6b5c;line-height:1.6;margin-top:22px;padding-top:14px;border-top:1px solid #e5dccb}
.ps-aviso{font-size:15px;color:#5b6b5c;padding:8px 0}
@media (max-width:760px){.ps-tiles{grid-template-columns:repeat(2,minmax(0,1fr))}.st-key-painel_stats{padding:18px 16px}}
</style>"""


def _tema(chart: alt.Chart) -> alt.Chart:
    return (chart.configure(background="transparent", font="sans-serif")
            .configure_view(stroke=None)
            .configure_axis(labelColor=TEXTO_2, titleColor=TEXTO_2, gridColor=GRADE, domainColor=GRADE,
                            tickColor=GRADE, labelFontSize=12, titleFontSize=12, titleFontWeight="normal")
            .configure_legend(disable=True))


def _leitura(frases: list[str]) -> None:
    if frases:
        st.markdown('<div class="ps-leitura"><ul>' + "".join(f"<li>{escape(f)}</li>" for f in frases)
                    + "</ul></div>", unsafe_allow_html=True)


def _bloco(titulo: str, pergunta: str) -> None:
    st.markdown(f'<div class="ps-bloco">{escape(titulo)}</div><p class="ps-pergunta">{escape(pergunta)}</p>',
                unsafe_allow_html=True)


def _tile(rotulo: str, valor: str, detalhe: str = "") -> str:
    return (f'<div class="ps-tile"><div class="ps-tile-rot">{escape(rotulo)}</div>'
            f'<div class="ps-tile-val">{escape(valor)}</div>'
            + (f'<div class="ps-tile-det">{escape(detalhe)}</div>' if detalhe else "") + "</div>")


def _legenda(itens: list[tuple[str, str]]) -> None:
    st.markdown('<div class="ps-legenda">' + "".join(
        f'<span><i style="background:{cor}"></i>{escape(t)}</span>' for t, cor in itens) + "</div>",
        unsafe_allow_html=True)


# --- blocos ------------------------------------------------------------------------------------

def _indicadores(p: dict) -> None:
    c, a, s = p.get("clima"), p.get("agua"), p.get("solo")
    tiles = []
    if c:
        tiles.append(_tile("Chuva média por ano", f"{es._mm(c['chuva_anual'])} mm", f"médias de {c['anos']}"))
        tiles.append(_tile("Meses secos", str(c["meses_secos"]), "com menos de 50 mm de chuva"))
        tiles.append(_tile("Temperatura média", f"{c['temp_media']:.1f} °C".replace(".", ","), "média do ano"))
    if a:
        tiles.append(_tile("Água no solo agora", a["situacao"].capitalize(),
                           f"{a['atual_pct']}% de umidade; típico: {a['normal_pct']}%"))
    elif s and s.get("classe"):
        tiles.append(_tile("Tipo de solo", s["classe"]["sibcs"], s["classe"]["wrb"]))
    if tiles:
        st.markdown('<div class="ps-tiles">' + "".join(tiles) + "</div>", unsafe_allow_html=True)


def _clima(c: dict) -> None:
    _bloco("Clima ao longo do ano", "Quando chove e quanto faz de calor no município, em média, desde 2001.")
    df = pd.DataFrame(c["mensal"])
    ciclo = c.get("ciclo")
    df["grupo"] = df["no_ciclo"].map({True: "No ciclo", False: "Fora do ciclo"})
    ordem = df["mes"].tolist()
    col1, col2 = st.columns(2, gap="large")
    with col1:
        st.markdown('<p class="ps-graf-tit">Chuva média por mês (mm)</p>', unsafe_allow_html=True)
        barras = alt.Chart(df).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4, size=22).encode(
            x=alt.X("mes:N", sort=ordem, title=None, axis=alt.Axis(labelAngle=0)),
            y=alt.Y("chuva_mm:Q", title="mm", axis=alt.Axis(tickCount=5)),
            color=alt.Color("grupo:N", scale=alt.Scale(domain=["No ciclo", "Fora do ciclo"],
                                                       range=[CHUVA, CHUVA_FORA] if ciclo else [CHUVA, CHUVA])),
            tooltip=[alt.Tooltip("mes:N", title="Mês"), alt.Tooltip("chuva_mm:Q", title="Chuva (mm)", format=".0f")],
        )
        seco = alt.Chart(pd.DataFrame({"y": [es.MES_SECO_MM]})).mark_rule(color=TEXTO_2, strokeDash=[4, 4]).encode(
            y="y:Q")
        st.altair_chart(_tema((barras + seco).properties(height=250)), use_container_width=True)
        itens = [("Linha tracejada: 50 mm (abaixo disso, mês seco)", "transparent")]
        if ciclo:
            itens = [(f"Meses do ciclo de {ciclo['cultura']}", CHUVA), ("Demais meses", CHUVA_FORA)] + itens
        _legenda(itens)
    with col2:
        st.markdown('<p class="ps-graf-tit">Temperatura por mês (°C): média, com a faixa entre mínima e máxima</p>',
                    unsafe_allow_html=True)
        base = alt.Chart(df).encode(x=alt.X("mes:N", sort=ordem, title=None, axis=alt.Axis(labelAngle=0)))
        faixa = base.mark_area(color=TEMP, opacity=0.16).encode(
            y=alt.Y("tmin_c:Q", title="°C", scale=alt.Scale(zero=False)), y2="tmax_c:Q")
        linha = base.mark_line(color=TEMP, strokeWidth=2).encode(y="temp_c:Q")
        pontos = base.mark_point(color=TEMP, filled=True, size=70).encode(
            y="temp_c:Q",
            tooltip=[alt.Tooltip("mes:N", title="Mês"), alt.Tooltip("temp_c:Q", title="Média (°C)", format=".1f"),
                     alt.Tooltip("tmin_c:Q", title="Mínima média (°C)", format=".1f"),
                     alt.Tooltip("tmax_c:Q", title="Máxima média (°C)", format=".1f")])
        st.altair_chart(_tema((faixa + linha + pontos).properties(height=250)), use_container_width=True)
        _legenda([("Linha: temperatura média", TEMP), ("Faixa: da mínima à máxima média", "#fbd9cb")])
    _leitura(c["leitura"])


def _agua(a: dict) -> None:
    _bloco("Água no solo agora", "O solo tem água para a semente germinar? Comparação com a mesma época dos outros anos.")
    _leitura(a["leitura"])


def _solo(s: dict) -> None:
    _bloco("Solo do local", "Que tipo de solo há na área e o que ele pede de manejo (estimativa por satélite e mapas).")
    t, q, c = s.get("textura"), s.get("quimica"), s.get("classe")
    tiles = []
    if c:
        tiles.append(_tile("Tipo de solo", c["sibcs"], f"{c['wrb']}" + (f", {c['prob']}% de probabilidade"
                                                                         if c.get("prob") else "")))
    if q:
        tiles.append(_tile("pH (acidez)", f"{q['ph']:.1f}".replace(".", ","), "ideal da maioria: 5,5 a 6,5"))
        tiles.append(_tile("CTC", f"{q['ctc']:.1f}".replace(".", ","), "cmol/kg: capacidade de reter nutrientes"))
    if t and t.get("ad_mm_cm"):
        tiles.append(_tile("Água disponível", f"{10 * t['ad_mm_cm']:.0f} mm",
                           "a cada 10 cm de solo"))
    if tiles:
        st.markdown('<div class="ps-tiles">' + "".join(tiles) + "</div>", unsafe_allow_html=True)
    if t:
        st.markdown('<p class="ps-graf-tit">Textura (0 a 60 cm): quanto de cada partícula o solo tem</p>',
                    unsafe_allow_html=True)
        df = pd.DataFrame({"parte": ["Areia", "Silte", "Argila"], "pct": [t["areia"], t["silte"], t["argila"]]})
        barras = alt.Chart(df).mark_bar(cornerRadiusTopRight=4, cornerRadiusBottomRight=4, size=22,
                                        color="#8a5a33").encode(
            y=alt.Y("parte:N", sort=None, title=None),
            x=alt.X("pct:Q", title="% do solo", scale=alt.Scale(domain=[0, 100])),
            tooltip=[alt.Tooltip("parte:N", title="Partícula"), alt.Tooltip("pct:Q", title="%", format=".0f")])
        rotulos = barras.mark_text(align="left", dx=6, color=TEXTO, fontSize=13).encode(
            text=alt.Text("pct:Q", format=".0f"))
        st.altair_chart(_tema((barras + rotulos).properties(height=alt.Step(36))), use_container_width=True)
    _leitura(s.get("leitura") or [])


def _zarc(z: dict) -> None:
    _bloco("Janelas do zoneamento oficial (ZARC)",
           "Em que épocas o Ministério da Agricultura indica plantar cada cultura recomendada, e com que risco.")
    df = pd.DataFrame(z["linhas"])
    df["Risco"] = df["risco"].map({20: "Até 20%", 30: "Até 30%", 40: "Até 40%", 50: "Até 50%"}).fillna("Não indicado")
    df["mes"] = ((df["dec"] - 1) // 3).map(lambda i: es.MESES[i])
    df["periodo"] = df["dec"].map(lambda d: ["1 a 10", "11 a 20", "21 ao fim"][(d - 1) % 3]) + " de " + df["mes"]
    eixo = alt.Axis(values=list(range(2, 37, 3)), labelExpr=f"{es.MESES}[floor((datum.value - 1) / 3)]",
                    labelAngle=0, title=None, grid=False)
    calor = alt.Chart(df).mark_rect(cornerRadius=2, stroke="#fffdf7", strokeWidth=2).encode(
        x=alt.X("dec:O", axis=eixo, scale=alt.Scale(paddingInner=0)),
        y=alt.Y("cultura:N", title=None, sort=z["culturas"]),
        color=alt.Color("Risco:N", scale=alt.Scale(domain=list(RISCO), range=list(RISCO.values()))),
        tooltip=[alt.Tooltip("cultura:N", title="Cultura"), alt.Tooltip("periodo:N", title="Plantio"),
                 alt.Tooltip("Risco:N", title="Risco de perda")])
    sua = pd.DataFrame({"dec": [z["decendio_plantio"]], "rotulo": ["sua data"]})
    marca = alt.Chart(sua).mark_rule(color=MARCA, strokeWidth=3).encode(x="dec:O")
    texto = alt.Chart(sua).mark_text(color=TEXTO, fontWeight="bold", fontSize=12, dy=-6, baseline="bottom").encode(
        x="dec:O", y=alt.value(0), text="rotulo:N")
    st.altair_chart(_tema((calor + marca + texto).properties(height=36 * len(z["culturas"]) + 40)),
                    use_container_width=True)
    _legenda([(t, c) for t, c in RISCO.items()] + [("Barra amarela: a data que você informou", MARCA)])
    _leitura(z["leitura"])


def _notas(notas: list[dict]) -> None:
    _bloco("Como cada cultura foi avaliada",
           "Notas de 0 a 100 por critério. A nota final combina clima, água, solo, zoneamento e rotação e depois "
           "é ajustada pelos seus objetivos e pela sua cultura desejada.")
    setor = {"melhores": "Recomendada", "intermediarias": "Alternativa", "piores": "Não recomendada",
             "desejada": "Sua escolha"}
    linhas = []
    for n in notas:
        linha = {"Cultura": n["cultura"] + (" (sua escolha)" if n["desejada"] else ""),
                 "Grupo": setor.get(n["setor"], n["setor"])}
        for k in ("nota", "t1", "t2", "t3", "t4", "t5", "aderencia"):
            v = n.get(k)
            linha[NOMES_CRITERIOS[k]] = None if v is None else round(100 * v)
        linhas.append(linha)
    df = pd.DataFrame(linhas)
    barra = {NOMES_CRITERIOS[k]: st.column_config.ProgressColumn(NOMES_CRITERIOS[k], min_value=0, max_value=100,
                                                                  format="%d", width="small") for k in
             ("nota", "t1", "t2", "t3", "t4", "t5", "aderencia")}
    barra["Cultura"] = st.column_config.TextColumn("Cultura", width="medium")
    barra["Grupo"] = st.column_config.TextColumn("Grupo", width="small")
    st.dataframe(df, hide_index=True, use_container_width=True, column_config=barra)
    _leitura([
        "Clima: temperatura, chuva e risco de geada no ciclo, nos anos desde 2001 (os anos recentes pesam mais).",
        "Água: simulação diária da água no solo durante o ciclo (método FAO-56), com a umidade de hoje.",
        "Solo: pH, textura, drenagem e fertilidade frente à exigência da cultura (problemas corrigíveis pesam menos).",
        "ZARC: risco do zoneamento oficial na data; culturas sem zoneamento ficam neutras (célula vazia).",
        "Rotação: efeito do seu histórico (ex.: gramínea depois de leguminosa ganha; repetir a cultura perde).",
        "Seus objetivos: quanto a cultura entrega o que você marcou (vazio quando nada foi marcado).",
    ])


def mostrar(p: dict) -> None:
    """Desenha o painel inteiro a partir de ``estatisticas.painel``."""
    st.markdown(CSS, unsafe_allow_html=True)
    with st.container(key="painel_stats"):
        if p.get("erro"):
            st.markdown(f'<p class="ps-aviso">{escape(p["erro"])}</p>', unsafe_allow_html=True)
            return
        st.markdown(f'<div class="ps-titulo">O que os dados dizem sobre {escape(p["municipio"])}</div>'
                    '<p class="ps-sub">Os números abaixo são os mesmos que o modelo usou para ordenar as culturas. '
                    'Passe o mouse nos gráficos para ver os valores.</p>', unsafe_allow_html=True)
        _indicadores(p)
        if p.get("clima"):
            _clima(p["clima"])
        if p.get("agua"):
            _agua(p["agua"])
        if p.get("solo"):
            _solo(p["solo"])
        if p.get("zarc"):
            _zarc(p["zarc"])
        if p.get("notas"):
            _notas(p["notas"])
        else:
            st.markdown('<p class="ps-aviso">Gere as recomendações para ver como cada cultura foi avaliada.</p>',
                        unsafe_allow_html=True)
        st.markdown('<div class="ps-fontes"><strong>Fontes:</strong><br>' + "<br>".join(escape(f) for f in p["fontes"])
                    + "</div>", unsafe_allow_html=True)
