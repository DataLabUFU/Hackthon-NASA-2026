# -*- coding: utf-8 -*-
"""RotaSafra: interface Streamlit. A lógica fica em motor.py.

Rodar:  pip install -r requirements.txt,  python scripts/preparar_dados.py  e  streamlit run app_teste.py
O modelo real (sete torres em towers/) é o padrão quando os dados existem; force com MOTOR_RECOMENDACAO=mock|modelo.

Este arquivo é autossuficiente no visual: não depende de .streamlit/config.toml.
"""
import base64
import json
import logging
from datetime import date
from html import escape

import streamlit as st

import motor as mt

# Logs de execução (torres fora da nota, falhas do SoilGrids, tempos) vão para o terminal, não para a tela.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
for ruidoso in ("urllib3", "requests"):
    logging.getLogger(ruidoso).setLevel(logging.WARNING)

try:                                    # usado só para marcar a página como pt-BR
    import streamlit.components.v1 as components
except Exception:                       # pragma: no cover
    components = None

NOME, NOME_DESTAQUE = "Rota", "Safra"
SLOGAN = "Rotação inteligente para a próxima safra"

st.set_page_config(page_title=f"{NOME}{NOME_DESTAQUE} | Rotação de Culturas", page_icon="🌱",
                   layout="wide", initial_sidebar_state="collapsed")

CSS = """<style>
:root{--verde-escuro:#23452f;--verde:#477b43;--verde-claro:#e4efdf;--amarelo:#e9bd45;--marrom:#8a5a33;--marrom-escuro:#6f4627;
--bege:#efe6d3;--bege-claro:#f7f1e3;--bege-borda:#d8c9a8;--fundo:#f6f1e5;--texto:#283b2b}
html, body, .stApp,
[data-testid="stAppViewContainer"],
[data-testid="stMain"] {
    background: var(--fundo) !important;
    color: var(--texto);
    color-scheme: light !important;
    min-height: 100vh;
}

*, *::before, *::after {
    color-scheme: light;
}[data-testid="stHeader"],[data-testid="stToolbar"],[data-testid="stDecoration"],#MainMenu,footer{display:none!important}
.block-container{max-width:100%!important;padding:0!important}
.st-key-conteudo{max-width:1250px;width:100%;margin:0 auto;padding:0 24px 8px}
[data-testid="stElementContainer"]:has(iframe[height="0"]){height:0;margin:0;overflow:hidden}
.topo{background:linear-gradient(100deg,#1b3624 0%,var(--verde-escuro) 55%,#355b3b 100%);color:#fff;border-bottom:4px solid var(--amarelo);padding:22px 0}
.topo-in{max-width:1250px;margin:0 auto;padding:0 24px;display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap}
.marca{display:flex;align-items:center;gap:14px}
.logo{font-size:30px;font-weight:800;letter-spacing:.2px;line-height:1.1}.logo span{color:var(--amarelo)}
.slogan{font-size:14px;color:#d7e2d3;margin-top:3px}
.header-tag{background:rgba(255,255,255,.12);border:1px solid rgba(255,255,255,.22);padding:10px 18px;border-radius:22px;font-size:14px;font-weight:600;white-space:nowrap}
.hero{padding:36px 0 6px}
.hero-eyebrow{font-size:13px;font-weight:800;letter-spacing:.14em;color:var(--marrom);margin-bottom:10px}
.pagina-titulo{font-size:clamp(32px,5vw,50px);font-weight:800;line-height:1.1;color:var(--verde-escuro);padding-left:18px;border-left:8px solid var(--amarelo);margin-bottom:14px}
.pagina-sub{font-size:18px;line-height:1.55;color:#4d5f4f;max-width:820px}
.st-key-formulario{background:#fffdf7;border:1px solid #e6dcc3;border-radius:16px;padding:10px 30px 30px;box-shadow:0 4px 18px rgba(80,60,20,.07)}
.secao-titulo{display:flex;align-items:center;gap:12px;font-size:25px;font-weight:800;color:var(--verde-escuro);margin:26px 0 14px;padding-bottom:12px;border-bottom:2px solid #e8dfc6}
.secao-num{background:var(--verde);color:#fff;font-size:15px;font-weight:800;min-width:34px;height:34px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center}
[data-testid="stWidgetLabel"] p{font-size:16px!important;font-weight:700!important;color:#405342!important}

/* Campos de seleção e entrada */
div[data-baseweb="select"] > div,
div[data-baseweb="base-input"],
div[data-baseweb="input"] {
    background-color: var(--bege) !important;
    border: 1px solid var(--bege-borda) !important;
    border-radius: 9px !important;
    color: var(--texto) !important;
    min-height: 48px;
}

/* Texto dentro dos campos */
div[data-baseweb="select"] *,
div[data-baseweb="base-input"] input,
div[data-baseweb="input"] input {
    color: var(--texto) !important;
    -webkit-text-fill-color: var(--texto) !important;
}

/* Fundo dos menus suspensos */
[data-baseweb="popover"],
[data-baseweb="popover"] > div,
[data-baseweb="menu"],
[data-baseweb="menu"] ul,
[role="listbox"] {
    background-color: var(--bege-claro) !important;
    color: var(--texto) !important;
}

/* Opções dos menus */
[role="option"],
[data-baseweb="menu"] li,
[data-baseweb="popover"] li {
    background-color: var(--bege-claro) !important;
    color: var(--texto) !important;
}

/* Opção selecionada ou sob o cursor */
[role="option"]:hover,
[role="option"][aria-selected="true"],
[data-baseweb="menu"] li:hover,
[data-baseweb="menu"] li[aria-selected="true"] {
    background-color: var(--verde-claro) !important;
    color: var(--verde-escuro) !important;
}

/* Calendário */
[data-baseweb="calendar"],
[data-baseweb="calendar"] *,
[data-baseweb="datepicker"],
[data-baseweb="datepicker"] * {
    color-scheme: light !important;
}

[data-baseweb="calendar"],
[data-baseweb="datepicker"] {
    background-color: var(--bege-claro) !important;
    color: var(--texto) !important;
}

/* Dias do calendário */
[data-baseweb="calendar"] button {
    color: var(--texto) !important;
    background-color: transparent !important;
}

[data-baseweb="calendar"] button:hover {
    background-color: var(--verde-claro) !important;
}

/* Dia selecionado */
[data-baseweb="calendar"] button[aria-selected="true"] {
    background-color: var(--verde) !important;
    color: #ffffff !important;
}

/* Cabeçalho do calendário */
[data-baseweb="calendar"] svg {
    fill: var(--verde-escuro) !important;
    color: var(--verde-escuro) !important;
}
div[data-baseweb="select"]>div:hover,div[data-baseweb="select"]>div:focus-within,div[data-baseweb="base-input"]:focus-within{border-color:var(--verde)!important}
div[data-baseweb="select"] *,div[data-baseweb="base-input"] input{color:var(--texto)!important;-webkit-text-fill-color:var(--texto)}
div[data-baseweb="base-input"] input{background:transparent!important;font-size:16px}
div[data-baseweb="select"] div[value]{font-size:16px}
input::placeholder{color:#8c8167!important;-webkit-text-fill-color:#8c8167!important;opacity:1}
[data-baseweb="popover"] [data-baseweb="menu"],[data-baseweb="popover"] ul{background:var(--bege-claro)!important}
[data-baseweb="popover"] li{background:var(--bege-claro)!important;color:var(--texto)!important}
[data-baseweb="popover"] li:hover,[data-baseweb="popover"] li[aria-selected="true"]{background:var(--verde-claro)!important}
[data-baseweb="calendar"]{background:var(--bege-claro)!important;color:var(--texto)!important}
[data-baseweb="calendar"] [aria-selected="true"]{background:var(--verde)!important;color:#fff!important}
[data-testid="stCheckbox"]{background:var(--bege);border:1px solid var(--bege-borda);border-radius:10px;padding:13px 15px;transition:background .2s,border-color .2s}
[data-testid="stCheckbox"]:hover,[data-testid="stCheckbox"]:has(input:checked){background:var(--verde-claro);border-color:var(--verde)}
[data-testid="stCheckbox"] label{width:100%;cursor:pointer;align-items:center}
[data-testid="stCheckbox"] p{font-size:15px!important;font-weight:600!important;color:var(--texto)!important}
label[data-baseweb="checkbox"]>span:first-child{background:var(--bege-claro)!important;border-color:#a89a78!important}
label[data-baseweb="checkbox"]:has(input:checked)>span:first-child{background:var(--verde)!important;border-color:var(--verde)!important}
button[kind="primary"],[data-testid="stBaseButton-primary"]{background:var(--marrom)!important;border:1px solid var(--marrom)!important;color:#fff!important;border-radius:11px!important;padding:.85rem 1rem!important;width:100%;box-shadow:0 3px 10px rgba(111,70,39,.28)}
button[kind="primary"] p,[data-testid="stBaseButton-primary"] p{color:#fff!important;font-size:18px!important;font-weight:800!important}
button[kind="primary"]:hover,[data-testid="stBaseButton-primary"]:hover{background:var(--marrom-escuro)!important;border-color:var(--marrom-escuro)!important}
.resultado-titulo{font-size:clamp(28px,4vw,38px);font-weight:800;color:var(--verde-escuro);margin:38px 0 8px}
.resultado-resumo{font-size:15px;color:#5f6f5f;line-height:1.7;margin-bottom:26px}
.grupo-titulo{padding:17px;border-radius:11px;font-size:19px;font-weight:800;text-align:center;margin-bottom:16px}
.grupo-verde{background:#e2f1e3;color:#2f6a37;border:1px solid #c7e3c9}
.grupo-amarelo{background:#fff3d2;color:#8f6a14;border:1px solid #f0dfad}
.grupo-vermelho{background:#f9e5e3;color:#a2403a;border:1px solid #edc9c5}
.card{background:#fffdf7;border-radius:12px;border-top:5px solid;box-shadow:0 3px 14px rgba(80,60,20,.07);margin-bottom:15px;overflow:hidden}
.card-verde{border-color:#4c9957}.card-amarelo{border-color:#e6b83f}.card-vermelho{border-color:#cf6660}
.card-resumo{list-style:none;cursor:pointer;padding:20px;display:flex;justify-content:space-between;align-items:center;gap:12px}
.card-resumo::-webkit-details-marker{display:none}
.card-resumo:hover{background:#f6f1e3}
.card-titulo{color:var(--verde-escuro);font-size:22px;font-weight:800}
.card-identificacao{display:flex;flex-direction:column;gap:6px}
.card-posicao{font-size:12px;color:#7d6f52;font-weight:800;letter-spacing:.04em}
.card-seta{font-size:22px;color:#7d6f52;transition:transform .25s}
.card[open] .card-seta{transform:rotate(180deg)}
.card-conteudo{padding:0 20px 22px}
.descricao{color:#6c6a58;font-size:14px;margin:0 0 14px;line-height:1.55}
.card-sub{font-size:15px;font-weight:800;margin:16px 0 10px;color:#405342}
.card ul{padding-left:20px;margin:0}
.card li{font-size:14px;color:#4f5d4f;margin-bottom:8px;line-height:1.55}
.clima{background:var(--bege);border-radius:9px;padding:13px 14px;margin-top:6px}
.clima p{font-size:14px;margin:0 0 7px;color:#4a5a4a;line-height:1.45}.clima p:last-child{margin:0}
.clima strong{color:var(--verde-escuro)}
.st-key-faixa_stats {
    background: var(--verde-escuro);
    border-radius: 16px;
    padding: 32px 34px;
    margin-top: 34px;
}

/* Alinhamento vertical do texto e botão */
.st-key-faixa_stats [data-testid="stHorizontalBlock"] {
    align-items: center;
}

.estatisticas-titulo {
    font-size: 27px;
    font-weight: 800;
    color: #fff;
    margin-bottom: 10px;
    line-height: 1.25;
}

.estatisticas-texto {
    font-size: 16px;
    color: #d1dfcf;
    line-height: 1.65;
    margin: 0;
    max-width: 780px;
}

/* Botão de estatísticas */
.st-key-btn_stats button {
    background: var(--amarelo) !important;
    border: none !important;
    border-radius: 10px !important;
    padding: .7rem 1.1rem !important;
    width: 100% !important;
    min-height: 48px;
}

.st-key-btn_stats button p {
    color: #283b2b !important;
    font-size: 15px !important;
    font-weight: 800 !important;
}

.st-key-btn_stats button:hover {
    background: #f4cf68 !important;
}

.st-key-btn_stats button{background:var(--amarelo)!important;border:none!important;border-radius:10px!important;padding:.7rem 1.4rem!important}
.st-key-btn_stats button p{color:#283b2b!important;font-size:16px!important;font-weight:800!important}
.st-key-btn_stats button:hover{background:#f4cf68!important}
.rodape{background:#1b3624;color:#c5d2c3;text-align:center;padding:26px 20px;font-size:14px;line-height:1.6;margin-top:44px}
@media (max-width:640px){.header-tag{display:none}.st-key-formulario{padding:6px 16px 22px}.st-key-faixa_stats{padding:24px 20px}

header-tag {
        display: none;
    }

    .st-key-formulario {
        padding: 6px 16px 22px;
    }

    .st-key-faixa_stats {
        padding: 24px 20px;
    }

    .estatisticas-titulo {
        font-size: 22px;
    }

    .estatisticas-texto {
        font-size: 14px;
    }

    .st-key-btn_stats button {
        padding: .6rem .7rem !important;
    }

    .st-key-btn_stats button p {
        font-size: 13px !important;
    }
}
/* Botão "Gerar recomendações" centralizado */
.st-key-btn_gerar{display:flex!important;justify-content:center!important;width:100%!important}
.st-key-btn_gerar .stButton{display:flex;justify-content:center;width:auto!important}
</style>"""

MARCA_SVG = ('<svg width="46" height="46" viewBox="0 0 46 46" aria-hidden="true"><circle cx="23" cy="23" r="22" fill="#355b3b" '
             'stroke="#e9bd45" stroke-width="2"/><path d="M13 30c0-9 7-15 19-15 0 11-6 17-15 17-2 0-3-.8-4-2z" fill="#e9bd45"/>'
             '<path d="M13 33c5-6 10-10 15-13" stroke="#23452f" stroke-width="2" fill="none" stroke-linecap="round"/></svg>')

SCRIPT_PT_BR = """<script>
const d = window.parent.document;
d.documentElement.lang = "pt-BR";
d.documentElement.setAttribute("translate", "no");
const meta = (k, v, c) => { if (!d.querySelector('meta[' + k + '="' + v + '"]')) { const m = d.createElement("meta"); m.setAttribute(k, v); m.content = c; d.head.appendChild(m); } };
meta("name", "google", "notranslate");
meta("http-equiv", "content-language", "pt-BR");
</script>"""

# título do grupo, cor, rótulo da lista de motivos
GRUPOS = {
    "recomendadas": ("Culturas recomendadas", "verde", "Por que recomendamos?"),
    "razoaveis": ("Alternativas razoáveis", "amarelo", "Por que considerar?"),
    "nao_recomendadas": ("Culturas não recomendadas", "vermelho", "Por que evitar?"),
}


def secao(numero: str, titulo: str):
    badge = f'<span class="secao-num">{numero}</span>' if numero else ""
    st.markdown(f'<div class="secao-titulo">{badge}{titulo}</div>', unsafe_allow_html=True)


# ------------------------------------------------------------------ captura dos dados (formulário -> Entrada)
def grade_checkbox(prefixo: str, opcoes: dict) -> list:
    """Grade de 3 colunas com caixas de marcar. Devolve os VALORES marcados."""
    colunas = st.columns(3)
    return [valor for i, (valor, rotulo) in enumerate(opcoes.items())
            if colunas[i % 3].checkbox(rotulo, key=f"{prefixo}_{valor}")]


def ordenar_por_tamanho(opcoes):
    """Ordena opções pelo tamanho do texto e depois alfabeticamente."""
    return sorted(opcoes, key=lambda item: (len(str(item)), str(item).casefold()))



def coletar_entrada():
    """Desenha o formulário e devolve (Entrada, clicou_no_botao)."""

    with st.container(key="formulario"):

        secao("01", "Localização da propriedade")

        c1, c2 = st.columns(2)

        estados_ordenados = sorted(
            mt.ESTADOS,
            key=lambda uf: (
                len(mt.ESTADOS[uf][0]),
                mt.ESTADOS[uf][0].casefold()
            )
        )

        uf = c1.selectbox(
            "Estado",
            estados_ordenados,
            index=None,
            key="f_uf",
            placeholder="Selecione o estado",
            format_func=lambda u: mt.ESTADOS[u][0]
        )

        cidades = ordenar_por_tamanho(mt.ESTADOS[uf][1]) if uf else []

        cidade = c2.selectbox(
            "Cidade",
            cidades,
            index=None,
            disabled=not uf,
            placeholder="Selecione a cidade" if uf else "Selecione primeiro o estado",
            key=f"cidade_{uf}"
        )

        secao("02", "Histórico de plantio")

        c3, c4 = st.columns(2)

        culturas_historico = ordenar_por_tamanho(mt.CULTURAS_HISTORICO)

        penultimo = c3.selectbox(
            "Penúltimo plantio",
            culturas_historico,
            index=None,
            key="f_penultimo",
            placeholder="Selecione a cultura"
        )

        ultimo = c4.selectbox(
            "Último plantio",
            culturas_historico,
            index=None,
            key="f_ultimo",
            placeholder="Selecione a cultura"
        )

        secao("03", "Próximo plantio")

        c5, c6 = st.columns(2)

        data = c5.date_input(
            "Data prevista para a próxima plantação",
            value=None,
            min_value=date.today(),
            format="DD/MM/YYYY",
            key="f_data",
        )

        culturas_desejadas = [
            "Sem preferência"
        ] + ordenar_por_tamanho(
            [c for c in mt.CULTURAS_DESEJADAS if c != "Sem preferência"]
        )

        desejada = c6.selectbox(
            "Qual cultura deseja plantar?",
            culturas_desejadas,
            index=0,
            key="f_desejada",
        )

        secao("04", "Problemas identificados na área")

        problemas = grade_checkbox("prob", mt.PROBLEMAS)

        secao("05", "Objetivos para a próxima safra")

        objetivos = grade_checkbox("obj", mt.OBJETIVOS)

        tipos = st.multiselect(
            "Tipos de cultura que você considera plantar (vazio = todos)",
            list(mt.TIPOS_CULTURA),
            format_func=lambda t: mt.TIPOS_CULTURA[t],
            placeholder="Todos os tipos",
            key="f_tipos",
        )

        st.write("")

        # Botão centralizado na largura do formulário (CSS em .st-key-btn_gerar)
        clicou = st.button(
            "Gerar recomendações",
            type="primary",
            key="btn_gerar"
        )

    entrada = mt.Entrada(
        penultimo=penultimo,
        ultimo=ultimo,
        uf=uf,
        cidade=cidade,
        data_plantio=data,
        cultura_desejada=None if desejada == "Sem preferência" else desejada,
        problemas=problemas,
        objetivos=objetivos,
        tipos_cultura=tipos
    )

    return entrada, clicou


# ------------------------------------------------------------------ exibição (Resultado -> HTML)
def html_motivo(m: str) -> str:
    """Destaca a informação do produtor a que a frase responde ("Seu objetivo “…”: resposta")."""
    ancora, sep, resto = m.partition(": ")
    if sep and len(ancora) <= 160:
        return f"<strong>{escape(ancora)}:</strong> {escape(resto)}"
    return escape(m)


def html_card(rec, posicao: int, cor: str, titulo_motivos: str) -> str:
    rotulo = f"{posicao}º LUGAR" + (" - MAIS RECOMENDADA" if cor == "verde" and posicao == 1 else "")
    motivos = "".join(f"<li>{html_motivo(m)}</li>" for m in rec.motivos)
    c = rec.clima
    clima = "".join(f"<p>{r}: <strong>{escape(v)}</strong></p>" for r, v in (
        ("Temperatura ideal", c.temperatura), ("Chuva", c.chuva), ("Época", c.epoca), ("Adaptação", c.adaptacao)))
    return (f'<details class="card card-{cor}"><summary class="card-resumo"><div class="card-identificacao">'
            f'<span class="card-posicao">{rotulo}</span><div class="card-titulo">{escape(rec.cultura)}</div></div>'
            f'<span class="card-seta">⌄</span></summary><div class="card-conteudo">'
            f'<p class="descricao">{escape(rec.descricao)}</p><div class="card-sub">{titulo_motivos}</div><ul>{motivos}</ul>'
            f'<div class="card-sub">Características meteorológicas</div><div class="clima">{clima}</div></div></details>')


def html_resumo(e: mt.Entrada, resultado: mt.Resultado) -> str:
    texto = (f"Área analisada: <strong>{escape(e.cidade)} - {escape(e.uf)}</strong>"
             f" | Histórico: <strong>{escape(e.penultimo)} → {escape(e.ultimo)}</strong>"
             f" | Próximo plantio: <strong>{e.data_plantio.strftime('%d/%m/%Y')}</strong>"
             f" | Cultura desejada: <strong>{escape(e.cultura_desejada or 'Sem preferência')}</strong>"
             f"<br>Problemas identificados: {escape(', '.join(e.problemas) or 'Nenhum informado')}"
             f"<br>Objetivos: {escape(', '.join(e.objetivos) or 'Nenhum informado')}")
    if resultado.observacoes:                  # notas do modelo: cultura desejada, água no solo, torres fora da nota
        texto += "<br><br>" + "<br>".join(escape(o) for o in resultado.observacoes)
    if resultado.fonte == "mock":
        texto += ("<br><br><em>As recomendações exibidas são demonstrativas e ainda não são calculadas "
                  "automaticamente com base nos dados informados.</em>")
    return texto


def mostrar_resultado(e: mt.Entrada, resultado: mt.Resultado):
    st.markdown('<div class="resultado-titulo">Recomendações para sua próxima safra</div>'
                f'<div class="resultado-resumo">{html_resumo(e, resultado)}</div>', unsafe_allow_html=True)
    for coluna, (chave, (titulo, cor, tit_motivos)) in zip(st.columns(3), GRUPOS.items()):
        cards = "".join(html_card(r, i, cor, tit_motivos) for i, r in enumerate(getattr(resultado, chave), 1))
        coluna.markdown(f'<div class="grupo-titulo grupo-{cor}">{titulo}</div>{cards}', unsafe_allow_html=True)


def mostrar_estatisticas(e: mt.Entrada, resultado: mt.Resultado | None):
    """Painel em largura total; os dados ficam guardados enquanto a entrada e o resultado não mudam."""
    import estatisticas
    import painel_estatisticas
    chave = (e.uf, e.cidade, e.data_plantio, id(resultado))
    guardado = st.session_state.get("painel")
    if not guardado or guardado[0] != chave:
        with st.spinner("Carregando os dados da região..."):
            guardado = (chave, estatisticas.painel(e, resultado))
        st.session_state["painel"] = guardado
    painel_estatisticas.mostrar(guardado[1])


def alternar_estatisticas():
    st.session_state["stats"] = not st.session_state.get("stats", False)
    if st.session_state["stats"]:
        st.query_params["stats"] = "1"
    else:
        st.query_params.pop("stats", None)



# ------------------------------------------------------------------ memória entre recarregamentos
# O Streamlit abre uma sessão nova a cada F5. As marcações ficam na URL (st.query_params), e a resposta fica no
# cache do servidor (st.cache_data), chaveada pela entrada: ao recarregar, o formulário e as recomendações voltam
# sem recalcular. O link também serve para compartilhar a consulta.
SEP = "|"


def codificar_entrada(e: mt.Entrada) -> str:
    texto = json.dumps(e.para_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return base64.urlsafe_b64encode(texto.encode("utf-8")).decode("ascii").rstrip("=")


def decodificar_entrada(codigo: str) -> mt.Entrada | None:
    try:
        d = json.loads(base64.urlsafe_b64decode(codigo + "=" * (-len(codigo) % 4)).decode("utf-8"))
        d["data_plantio"] = date.fromisoformat(d["data_plantio"]) if d.get("data_plantio") else None
        campos = set(mt.Entrada.__dataclass_fields__)
        return mt.Entrada(**{k: v for k, v in d.items() if k in campos})
    except Exception:
        return None


@st.cache_data(ttl="12h", max_entries=256, show_spinner=False)
def gerar_com_cache(codigo: str) -> mt.Resultado:
    """Resultado por entrada (compartilhado entre sessões; o clima da NASA muda no máximo uma vez por dia)."""
    return mt.gerar_recomendacoes(decodificar_entrada(codigo))


def restaurar_da_url() -> None:
    """Na primeira execução da sessão, devolve ao formulário (e ao resultado) o que estava na URL."""
    if st.session_state.get("_restaurado"):
        return
    st.session_state["_restaurado"] = True
    q = st.query_params
    uf = q.get("uf")
    if uf in mt.ESTADOS:
        st.session_state["f_uf"] = uf
        if q.get("cidade") in mt.ESTADOS[uf][1]:
            st.session_state[f"cidade_{uf}"] = q["cidade"]
    for param, chave in (("pen", "f_penultimo"), ("ult", "f_ultimo")):
        if q.get(param) in mt.CULTURAS_HISTORICO:
            st.session_state[chave] = q[param]
    try:
        d = date.fromisoformat(q.get("data", ""))
        if d >= date.today():               # data que já passou não volta (o campo não aceita)
            st.session_state["f_data"] = d
    except ValueError:
        pass
    if q.get("des") in mt.CULTURAS_DESEJADAS:
        st.session_state["f_desejada"] = q["des"]
    for param, prefixo, opcoes in (("prob", "prob", mt.PROBLEMAS), ("obj", "obj", mt.OBJETIVOS)):
        for valor in q.get(param, "").split(SEP):
            if valor in opcoes:
                st.session_state[f"{prefixo}_{valor}"] = True
    tipos = [t for t in q.get("tipos", "").split(SEP) if t in mt.TIPOS_CULTURA]
    if tipos:
        st.session_state["f_tipos"] = tipos
    if q.get("stats") == "1":
        st.session_state["stats"] = True
    codigo = q.get("r")
    e = decodificar_entrada(codigo) if codigo else None
    if e is not None:
        try:
            with st.spinner("Recuperando suas recomendações..."):
                st.session_state.update(entrada_res=e, resultado=gerar_com_cache(codigo))
        except Exception:                   # dados mudaram ou entrada inválida: o produtor gera de novo
            st.query_params.pop("r", None)


def salvar_na_url(e: mt.Entrada) -> None:
    """Escreve as marcações atuais na URL (só o que mudou; não dispara nova execução)."""
    novo = {"uf": e.uf, "cidade": e.cidade, "pen": e.penultimo, "ult": e.ultimo,
            "data": e.data_plantio.isoformat() if e.data_plantio else None,
            "des": e.cultura_desejada, "prob": SEP.join(e.problemas), "obj": SEP.join(e.objetivos),
            "tipos": SEP.join(e.tipos_cultura)}
    for k, v in novo.items():
        if v:
            if st.query_params.get(k) != v:
                st.query_params[k] = v
        elif k in st.query_params:
            del st.query_params[k]


# ------------------------------------------------------------------ página
st.markdown(CSS, unsafe_allow_html=True)
st.markdown(f'<div class="topo"><div class="topo-in"><div class="marca">{MARCA_SVG}<div>'
            f'<div class="logo">{NOME}<span>{NOME_DESTAQUE}</span></div><div class="slogan">{SLOGAN}</div></div></div>'
            '<div class="header-tag">Apoio à decisão do produtor</div></div></div>', unsafe_allow_html=True)

with st.container(key="conteudo"):
    st.markdown('<div class="hero"><div class="hero-eyebrow">PLANEJAMENTO DA SAFRA</div>'
                '<div class="pagina-titulo">Planejamento da próxima plantação</div>'
                '<div class="pagina-sub">Informe as condições da sua área e receba recomendações de culturas '
                'considerando o histórico, os objetivos e o clima.</div></div>', unsafe_allow_html=True)

    restaurar_da_url()
    entrada, clicou = coletar_entrada()
    salvar_na_url(entrada)

    if clicou:
        faltam = mt.validar_entrada(entrada)
        if faltam:
            st.error("Preencha " + (", ".join(faltam[:-1]) + " e " if len(faltam) > 1 else "") + faltam[-1] + ".")
        else:
            try:
                with st.spinner("Gerando recomendações..."):
                    resultado = gerar_com_cache(codificar_entrada(entrada))
                # guarda uma "foto" da entrada: o resultado só muda quando o produtor gerar de novo
                st.session_state.update(entrada_res=entrada, resultado=resultado)
                st.query_params["r"] = codificar_entrada(entrada)
            except Exception as erro:
                st.error(f"Não foi possível gerar as recomendações: {erro}")

    if "resultado" in st.session_state:
        mostrar_resultado(st.session_state["entrada_res"], st.session_state["resultado"])
        
with st.container(key="faixa_stats"):

    texto_stats, botao_stats = st.columns([4, 1])

    with texto_stats:
        st.markdown(
            '<div class="estatisticas-titulo">'
            'Quer entender os dados por trás das recomendações?'
            '</div>'
            '<p class="estatisticas-texto">'
            'Consulte gráficos, indicadores de produtividade, '
            'características do solo, dados climáticos e estudos '
            'utilizados para fundamentar as recomendações.'
            '</p>',
            unsafe_allow_html=True
        )

    with botao_stats:
        st.button(
            "Ocultar estatísticas" if st.session_state.get("stats")
            else "Acessar estatísticas →",
            key="btn_stats",
            on_click=alternar_estatisticas
        )


# painel em largura total, abaixo da faixa (dentro da coluna do botão ficava espremido)
if st.session_state.get("stats"):
    mostrar_estatisticas(st.session_state.get("entrada_res", entrada), st.session_state.get("resultado"))

fontes_dados = ("<br>Dados: NASA POWER (clima, extremos e umidade do solo), SoilGrids, ECOCROP/FAO e ZARC/MAPA. "
                "Confirme as condições de crédito com sua instituição financeira." if mt.DADOS_REAIS
                else "<br>Versão de demonstração: recomendações e indicadores fictícios.")
st.markdown(f'<div class="rodape">{NOME}{NOME_DESTAQUE} © 2026 | Plataforma de apoio à decisão do produtor.<br>'
            'Ferramenta de apoio: não substitui a avaliação do agrônomo nem o conhecimento local da área.'
            f'{fontes_dados}</div>', unsafe_allow_html=True)

if components is not None:                # marca a página como pt-BR e sem tradução automática
    try:
        components.html(SCRIPT_PT_BR, height=0)
    except Exception:
        pass
