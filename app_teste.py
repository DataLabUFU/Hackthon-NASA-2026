"""AgroData: interface Streamlit (convertida do HTML). A lógica fica em motor.py.

Rodar:  pip install -r requirements.txt,  python scripts/preparar_dados.py  e  streamlit run app_teste.py
O modelo real (seis torres em towers/) é o padrão quando os dados existem; force com MOTOR_RECOMENDACAO=mock|modelo.
"""
from datetime import date
from html import escape

import pandas as pd
import streamlit as st

import motor as mt

st.set_page_config(page_title="AgroData | Rotação de Culturas", layout="wide")

CSS = """<style>
:root{--verde-escuro:#23452f;--verde:#477b43;--verde-claro:#e4efdf;--amarelo:#e9bd45}
.stApp{background:#f3f5ed}
.block-container{max-width:1250px;padding-top:1.5rem;padding-bottom:2rem}
#MainMenu,footer{visibility:hidden}
.topo{background:var(--verde-escuro);color:#fff;padding:25px 30px;border-radius:12px;display:flex;justify-content:space-between;align-items:center;gap:16px;margin-bottom:28px}
.logo{font-size:25px;font-weight:bold}.logo span{color:var(--amarelo)}
.topo p{font-size:13px;color:#d7e2d3;margin:5px 0 0}
.header-tag{background:#355b3b;padding:10px 16px;border-radius:20px;font-size:13px;white-space:nowrap}
.pagina-titulo{font-size:28px;font-weight:bold;color:var(--verde-escuro);margin-bottom:8px}
.pagina-sub{color:#718071;font-size:14px;margin-bottom:20px}
.secao-titulo{font-size:19px;font-weight:bold;color:var(--verde-escuro);margin:18px 0 14px;padding-bottom:10px;border-bottom:1px solid #e5e9df}
[data-testid="stWidgetLabel"] p{font-weight:bold;font-size:13px;color:#405342}
div[data-testid="stVerticalBlockBorderWrapper"]{background:#fff;border-radius:12px}
.stButton>button{width:100%;padding:.8rem;font-weight:bold}
.resultado-titulo{font-size:23px;font-weight:bold;color:var(--verde-escuro);margin:35px 0 7px}
.resultado-resumo{font-size:13px;color:#778477;line-height:1.6;margin-bottom:25px}
.grupo-titulo{padding:16px;border-radius:9px;font-size:15px;font-weight:bold;text-align:center;margin-bottom:15px}
.grupo-verde{background:#e2f1e3;color:#35743d;border:1px solid #c7e3c9}
.grupo-amarelo{background:#fff3d2;color:#9c751c;border:1px solid #f0dfad}
.grupo-vermelho{background:#f9e5e3;color:#a8433c;border:1px solid #edc9c5}
.card{background:#fff;border-radius:11px;border-top:4px solid;box-shadow:0 3px 12px rgba(0,0,0,.04);margin-bottom:15px;overflow:hidden}
.card-verde{border-color:#4c9957}.card-amarelo{border-color:#e6b83f}.card-vermelho{border-color:#cf6660}
.card-resumo{list-style:none;cursor:pointer;padding:20px;display:flex;justify-content:space-between;align-items:center;gap:12px}
.card-resumo::-webkit-details-marker{display:none}
.card-resumo:hover{background:#f8faf6}
.card-titulo{color:var(--verde-escuro);font-size:17px;font-weight:bold}
.card-identificacao{display:flex;flex-direction:column;gap:6px}
.card-posicao{font-size:11px;color:#778477;font-weight:bold}
.card-seta{font-size:20px;color:#718071;transition:transform .25s}
.card[open] .card-seta{transform:rotate(180deg)}
.card-conteudo{padding:0 20px 22px}
.descricao{color:#7b897b;font-size:12px;margin:0 0 14px;line-height:1.5}
.card-sub{font-size:13px;font-weight:bold;margin:14px 0 10px;color:#405342}
.card ul{padding-left:18px;margin:0}
.card li{font-size:12px;color:#667466;margin-bottom:8px;line-height:1.5}
.clima{background:#f2f5ee;border-radius:8px;padding:12px;margin-top:6px}
.clima p{font-size:12px;margin:0 0 7px;color:#526451;line-height:1.4}.clima p:last-child{margin:0}
.clima strong{color:var(--verde-escuro)}
.estatisticas{background:var(--verde-escuro);color:#fff;border-radius:12px;padding:30px;margin:35px 0 12px}
.estatisticas-titulo{font-size:21px;font-weight:bold;margin-bottom:9px}
.estatisticas p{font-size:13px;color:#d1dfcf;line-height:1.6;margin:0}
.rodape{background:#1b3624;color:#c5d2c3;text-align:center;padding:20px;font-size:12px;border-radius:12px;margin-top:30px}
</style>"""

# título do grupo, cor, rótulo da lista de motivos
GRUPOS = {
    "recomendadas": ("Culturas recomendadas", "verde", "Por que recomendamos?"),
    "razoaveis": ("Alternativas razoáveis", "amarelo", "Por que considerar?"),
    "nao_recomendadas": ("Culturas não recomendadas", "vermelho", "Por que evitar?"),
}


# ------------------------------------------------------------------ captura dos dados (formulário -> Entrada)
def grade_checkbox(prefixo: str, opcoes: dict) -> list:
    """Grade de 3 colunas com caixas de marcar. Devolve os VALORES marcados."""
    colunas = st.columns(3)
    return [valor for i, (valor, rotulo) in enumerate(opcoes.items())
            if colunas[i % 3].checkbox(rotulo, key=f"{prefixo}_{valor}")]


def coletar_entrada():
    """Desenha o formulário e devolve (Entrada, clicou_no_botao)."""
    with st.container(border=True):
        st.markdown('<div class="secao-titulo">01. Características da propriedade</div>', unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        penultimo = c1.selectbox("Penúltimo plantio", mt.CULTURAS_HISTORICO, index=None, placeholder="Selecione a cultura")
        ultimo = c2.selectbox("Último plantio", mt.CULTURAS_HISTORICO, index=None, placeholder="Selecione a cultura")

        c3, c4 = st.columns(2)
        uf = c3.selectbox("Estado", list(mt.ESTADOS), index=None, placeholder="Selecione o estado",
                          format_func=lambda u: mt.ESTADOS[u][0])
        cidade = c4.selectbox("Cidade", mt.ESTADOS[uf][1] if uf else [], index=None, disabled=not uf,
                              placeholder="Selecione a cidade" if uf else "Selecione primeiro o estado",
                              key=f"cidade_{uf}")      # a chave muda com o estado: a lista reinicia

        c5, c6 = st.columns(2)
        data = c5.date_input("Data prevista para a próxima plantação", value=None, format="DD/MM/YYYY")
        desejada = c6.selectbox("Qual cultura deseja plantar?", mt.CULTURAS_DESEJADAS, index=0)

        st.markdown('<div class="secao-titulo">02. Problemas identificados na área</div>', unsafe_allow_html=True)
        problemas = grade_checkbox("prob", mt.PROBLEMAS)
        st.markdown('<div class="secao-titulo">03. Objetivos para a próxima safra</div>', unsafe_allow_html=True)
        objetivos = grade_checkbox("obj", mt.OBJETIVOS)
        tipos = st.multiselect("Tipos de cultura que você considera plantar (vazio = todos)", list(mt.TIPOS_CULTURA),
                               format_func=lambda t: mt.TIPOS_CULTURA[t], placeholder="Todos os tipos")
        clicou = st.button("Analisar área e gerar recomendações", type="primary")

    entrada = mt.Entrada(penultimo=penultimo, ultimo=ultimo, uf=uf, cidade=cidade, data_plantio=data,
                         cultura_desejada=None if desejada == "Sem preferência" else desejada,
                         problemas=problemas, objetivos=objetivos, tipos_cultura=tipos)
    return entrada, clicou


# ------------------------------------------------------------------ exibição (Resultado -> HTML)
def html_card(rec, posicao: int, cor: str, titulo_motivos: str) -> str:
    rotulo = f"{posicao}º LUGAR" + (" - MAIS RECOMENDADA" if cor == "verde" and posicao == 1 else "")
    motivos = "".join(f"<li>{escape(m)}</li>" for m in rec.motivos)
    c = rec.clima
    clima = "".join(f"<p>{r}: <strong>{escape(v)}</strong></p>" for r, v in (
        ("Temperatura ideal", c.temperatura), ("Chuva", c.chuva), ("Época", c.epoca), ("Adaptação", c.adaptacao)))
    return (f'<details class="card card-{cor}"><summary class="card-resumo"><div class="card-identificacao">'
            f'<span class="card-posicao">{rotulo}</span><div class="card-titulo">{escape(rec.cultura)}</div></div>'
            f'<span class="card-seta">⌄</span></summary><div class="card-conteudo">'
            f'<p class="descricao">{escape(rec.descricao)}</p><div class="card-sub">{titulo_motivos}</div><ul>{motivos}</ul>'
            f'<div class="card-sub">Características meteorológicas</div><div class="clima">{clima}</div></div></details>')


def html_resumo(e: mt.Entrada, resultado: mt.Resultado, demo: bool) -> str:
    if demo:
        return f"Simulação demonstrativa para {escape(e.cidade)} - {escape(e.uf)}. Os resultados abaixo são fictícios."
    texto = (f"Área analisada: <strong>{escape(e.cidade)} - {escape(e.uf)}</strong>"
             f" | Histórico: <strong>{escape(e.penultimo)} → {escape(e.ultimo)}</strong>"
             f" | Próximo plantio: <strong>{e.data_plantio.strftime('%d/%m/%Y')}</strong>"
             f" | Cultura desejada: <strong>{escape(e.cultura_desejada or 'Sem preferência')}</strong>"
             f"<br><br>Problemas identificados: {escape(', '.join(e.problemas) or 'Nenhum informado')}"
             f"<br>Objetivos: {escape(', '.join(e.objetivos) or 'Nenhum informado')}")
    if resultado.observacoes:
        texto += "<br><br>" + "<br>".join(escape(o) for o in resultado.observacoes)
    if resultado.fonte == "mock":
        texto += ("<br><br><em>As recomendações exibidas são demonstrativas e ainda não são calculadas "
                  "automaticamente com base nos dados informados.</em>")
    return texto


def mostrar_resultado(e: mt.Entrada, resultado: mt.Resultado, demo: bool):
    st.markdown('<div class="resultado-titulo">Recomendações para sua próxima safra</div>'
                f'<div class="resultado-resumo">{html_resumo(e, resultado, demo)}</div>', unsafe_allow_html=True)
    for coluna, (chave, (titulo, cor, tit_motivos)) in zip(st.columns(3), GRUPOS.items()):
        cards = "".join(html_card(r, i, cor, tit_motivos) for i, r in enumerate(getattr(resultado, chave), 1))
        coluna.markdown(f'<div class="grupo-titulo grupo-{cor}">{titulo}</div>{cards}', unsafe_allow_html=True)


def mostrar_estatisticas(e: mt.Entrada):
    est = mt.obter_estatisticas(e)
    df = pd.DataFrame({"Chuva (mm)": est["chuva_mm"], "Temperatura média (°C)": est["temp_c"]}, index=est["meses"])
    st.markdown('<div class="secao-titulo">Estatísticas da região</div>', unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    c1.markdown("**Chuva média mensal (mm)**")
    c1.bar_chart(df["Chuva (mm)"])
    c2.markdown("**Temperatura média mensal (°C)**")
    c2.line_chart(df["Temperatura média (°C)"])
    st.caption(est["aviso"])


# ------------------------------------------------------------------ página
st.markdown(CSS, unsafe_allow_html=True)
st.markdown('<div class="topo"><div><div class="logo">Agro<span>Data</span></div>'
            '<p>Inteligência agrícola para decisões mais sustentáveis</p></div>'
            '<div class="header-tag">Apoio à rotação de culturas</div></div>'
            '<div class="pagina-titulo">Planejamento da próxima plantação</div>'
            '<div class="pagina-sub">Informe as condições da sua área para receber recomendações de culturas '
            'considerando o histórico, os objetivos e o clima.</div>', unsafe_allow_html=True)

entrada, clicou = coletar_entrada()

if "resultado" not in st.session_state:               # primeira visita: mostra a demonstração
    st.session_state.update(demo=True, entrada_res=mt.ENTRADA_DEMO,
                            resultado=mt.gerar_recomendacoes(mt.ENTRADA_DEMO, motor="mock"))

if clicou:
    faltam = mt.validar_entrada(entrada)
    if faltam:
        st.error("Preencha " + (", ".join(faltam[:-1]) + " e " if len(faltam) > 1 else "") + faltam[-1] + ".")
    else:
        try:
            with st.spinner("Gerando recomendações..."):
                resultado = mt.gerar_recomendacoes(entrada)
            # guarda uma "foto" da entrada: o resultado só muda quando o produtor clicar de novo
            st.session_state.update(demo=False, entrada_res=entrada, resultado=resultado)
        except Exception as erro:
            st.error(f"Não foi possível gerar as recomendações: {erro}")

mostrar_resultado(st.session_state.entrada_res, st.session_state.resultado, st.session_state.demo)

st.markdown('<div class="estatisticas"><div class="estatisticas-titulo">Quer entender os dados por trás das recomendações?</div>'
            '<p>Consulte gráficos, indicadores de produtividade, características do solo, dados climáticos e estudos '
            'utilizados para fundamentar as recomendações.</p></div>', unsafe_allow_html=True)
if st.button("Acessar estatísticas →", key="btn_stats"):
    st.session_state.stats = not st.session_state.get("stats", False)
if st.session_state.get("stats"):
    mostrar_estatisticas(st.session_state.entrada_res)

aviso_rodape = ("A demonstração inicial é fictícia. As análises usam NASA POWER (clima e umidade do solo), "
                "SoilGrids, ECOCROP/FAO e o ZARC/MAPA; confirme as condições de crédito com sua instituição financeira."
                if mt.DADOS_REAIS else "Dados, recomendações e indicadores apresentados nesta versão são fictícios.")
st.markdown('<div class="rodape">DataLab © 2026 | Plataforma de apoio à decisão do produtor.<br><br>'
            f'{aviso_rodape}</div>', unsafe_allow_html=True)