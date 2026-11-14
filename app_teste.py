"""Versão de teste: formulário do produtor + 3 cartões (verde, amarelo, vermelho).

SEM DADOS REAIS. As regras de pontuação abaixo são de exemplo, só para a interface reagir.
Depois, troque a função `avaliar` pelo motor de pontuação de verdade (scoring.py).

Rodar:  pip install streamlit   e   streamlit run app.py
"""
from datetime import date, timedelta
from html import escape

import streamlit as st

st.set_page_config(page_title="O que plantar a seguir?", layout="wide")

# ---------------------------------------------------------------- listas de escolha
# Lista de exemplo. Para todas as cidades do Brasil, use a API de localidades do IBGE.
CIDADES = {
    "Acre": ["Rio Branco"], "Alagoas": ["Maceió"], "Amapá": ["Macapá"], "Amazonas": ["Manaus"],
    "Bahia": ["Salvador", "Luís Eduardo Magalhães", "Barreiras"], "Ceará": ["Fortaleza"],
    "Distrito Federal": ["Brasília"], "Espírito Santo": ["Vitória"],
    "Goiás": ["Goiânia", "Rio Verde", "Jataí"], "Maranhão": ["São Luís", "Balsas"],
    "Mato Grosso": ["Cuiabá", "Sorriso", "Rondonópolis"], "Mato Grosso do Sul": ["Campo Grande", "Dourados"],
    "Minas Gerais": ["Uberlândia", "Uberaba", "Araguari", "Patos de Minas", "Belo Horizonte"],
    "Pará": ["Belém"], "Paraíba": ["João Pessoa"], "Paraná": ["Curitiba", "Londrina", "Cascavel"],
    "Pernambuco": ["Recife"], "Piauí": ["Teresina", "Uruçuí"], "Rio de Janeiro": ["Rio de Janeiro"],
    "Rio Grande do Norte": ["Natal"], "Rio Grande do Sul": ["Porto Alegre", "Passo Fundo"],
    "Rondônia": ["Porto Velho"], "Roraima": ["Boa Vista"], "Santa Catarina": ["Florianópolis", "Chapecó"],
    "São Paulo": ["São Paulo", "Ribeirão Preto", "Campinas"], "Sergipe": ["Aracaju"], "Tocantins": ["Palmas"],
}

PROBLEMAS = {
    "compactado": "Solo duro ou compactado", "seca": "Falta de água ou veranico",
    "erosao": "Erosão (a terra escorre)", "pragas": "Pragas", "doencas": "Doenças",
    "nematoide": "Nematoides", "daninhas": "Plantas daninhas difíceis",
    "fraco": "Solo fraco ou cansado", "geada": "Risco de geada",
}
OBJETIVOS = {
    "compactacao": "Menos compactação", "agua": "Reter mais água no solo",
    "nitrogenio": "Aumentar o nitrogênio", "pragas": "Lidar com pragas e doenças",
    "erosao": "Proteger o solo da erosão", "materia_organica": "Mais palhada e matéria orgânica",
    "seca": "Aguentar seca e calor", "renda": "Ganhar dinheiro com a safra",
}

# Dados FICTÍCIOS de exemplo (ajuda = objetivos que atende; resolve/piora = problemas).
CULTURAS = {
    "Soja": dict(fam="Fabaceae", meses=[10, 11, 12], ajuda={"nitrogenio", "renda"}, resolve=set(), piora={"compactado", "nematoide", "geada"}),
    "Milho": dict(fam="Poaceae", meses=[1, 2, 10, 11], ajuda={"materia_organica", "renda", "erosao"}, resolve=set(), piora={"seca"}),
    "Sorgo": dict(fam="Poaceae", meses=[1, 2, 3, 10, 11], ajuda={"seca", "materia_organica", "compactacao", "renda"}, resolve={"compactado", "seca"}, piora={"geada"}),
    "Milheto": dict(fam="Poaceae", meses=[2, 3, 10, 11], ajuda={"compactacao", "materia_organica", "seca", "erosao", "agua", "pragas"}, resolve={"compactado", "erosao", "seca", "nematoide"}, piora={"geada"}),
    "Braquiária": dict(fam="Poaceae", meses=[2, 3, 4, 10, 11], ajuda={"compactacao", "agua", "materia_organica", "erosao"}, resolve={"compactado", "erosao", "daninhas", "fraco"}, piora=set()),
    "Crotalária": dict(fam="Fabaceae", meses=[10, 11, 12, 1, 2], ajuda={"nitrogenio", "pragas", "materia_organica"}, resolve={"nematoide", "fraco", "daninhas"}, piora={"geada"}),
    "Feijão": dict(fam="Fabaceae", meses=[2, 3, 4, 5], ajuda={"nitrogenio", "renda"}, resolve=set(), piora={"compactado", "seca", "geada"}),
    "Girassol": dict(fam="Asteraceae", meses=[2, 3, 10], ajuda={"compactacao", "seca", "renda"}, resolve={"compactado", "seca"}, piora=set()),
    "Nabo forrageiro": dict(fam="Brassicaceae", meses=[3, 4, 5], ajuda={"compactacao", "erosao", "pragas", "agua"}, resolve={"compactado", "nematoide", "daninhas", "geada"}, piora=set()),
    "Aveia preta": dict(fam="Poaceae", meses=[4, 5], ajuda={"materia_organica", "erosao", "agua"}, resolve={"erosao", "geada", "doencas"}, piora=set()),
    "Trigo": dict(fam="Poaceae", meses=[4, 5], ajuda={"renda"}, resolve={"geada"}, piora={"seca"}),
    "Guandu": dict(fam="Fabaceae", meses=[10, 11, 12], ajuda={"compactacao", "nitrogenio", "seca", "materia_organica"}, resolve={"compactado", "fraco", "seca"}, piora={"geada"}),
}
NENHUM = "(nenhum / área em descanso)"
MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]


# ---------------------------------------------------------------- regras de exemplo
def avaliar(nome, c, ctx):
    """Troque esta função pelo motor de pontuação real. Devolve nota 0-100 e os motivos."""
    nota, pos, neg = 50, [], []
    for o in ctx["objetivos"]:
        if o in c["ajuda"]:
            nota += 12
            pos.append(f"Ajuda no seu objetivo: {OBJETIVOS[o].lower()}")
    for p in ctx["problemas"]:
        if p in c["resolve"]:
            nota += 10
            pos.append(f"Ajuda a combater: {PROBLEMAS[p].lower()}")
        if p in c["piora"]:
            nota -= 12
            neg.append(f"Pode piorar: {PROBLEMAS[p].lower()}")
    mes = ctx["data"].month
    if mes in c["meses"]:
        nota += 10
        pos.append(f"{MESES[mes - 1].capitalize()} está dentro da época de plantio")
    else:
        nota -= 20
        neg.append(f"{MESES[mes - 1].capitalize()} está fora da época de plantio recomendada")
    ult = ctx["ultimo"]
    if nome == ult:
        nota -= 25
        neg.append("É a mesma cultura do último plantio: aumenta o risco de pragas e doenças")
    elif ult in CULTURAS and CULTURAS[ult]["fam"] == c["fam"]:
        nota -= 10
        neg.append("É da mesma família da cultura anterior: ajuda menos a quebrar o ciclo de pragas")
    elif ult in CULTURAS:
        nota += 5
        pos.append("Muda de família em relação ao último plantio: ajuda a quebrar o ciclo de pragas")
    return dict(nome=nome, nota=max(0, min(100, nota)), pos=pos, neg=neg)


CORES = {"verde": ("#d7f0dc", "#2e7d32"), "amarelo": ("#fff4cc", "#b8860b"), "vermelho": ("#f9d9d9", "#c62828")}


def cartao(titulo, cor, r):
    fundo, borda = CORES[cor]
    lista = lambda xs, vazio: "".join(f"<li>{escape(x)}</li>" for x in xs) or f"<li>{vazio}</li>"
    return (
        f'<div style="background:{fundo};border-left:8px solid {borda};border-radius:12px;padding:16px 18px;color:#1b1b1b;">'
        f'<div style="font-size:0.8rem;font-weight:700;letter-spacing:.05em;text-transform:uppercase;color:{borda};">{titulo}</div>'
        f'<div style="font-size:1.6rem;font-weight:700;margin:4px 0 2px;">{escape(r["nome"])}</div>'
        f'<div style="margin-bottom:10px;">Nota de exemplo: {r["nota"]}/100</div>'
        f'<div style="font-weight:700;">A favor</div><ul style="margin-top:2px;">{lista(r["pos"], "Nenhum ponto forte para o que você marcou")}</ul>'
        f'<div style="font-weight:700;">Atenção</div><ul style="margin-top:2px;">{lista(r["neg"], "Nenhum problema óbvio com o que você informou")}</ul>'
        f"</div>"
    )


# ---------------------------------------------------------------- tela
st.title("O que plantar a seguir?")
st.warning("Versão de teste: as recomendações usam regras de exemplo, sem dados de satélite, solo ou mercado.")

st.subheader("1. Onde fica a área")
c1, c2 = st.columns(2)
estado = c1.selectbox("Estado", sorted(CIDADES), index=sorted(CIDADES).index("Minas Gerais"))
cidade = c2.selectbox("Cidade", CIDADES[estado], key=f"cidade_{estado}")   # a lista muda com o estado

st.subheader("2. O que foi plantado antes")
opcoes = [NENHUM] + sorted(CULTURAS)
c1, c2 = st.columns(2)
ultimo = c1.selectbox("Último plantio", opcoes, index=opcoes.index("Soja"))
penultimo = c2.selectbox("Penúltimo plantio", opcoes, index=opcoes.index("Milho"))

st.subheader("3. Problemas na área")
problemas = st.multiselect("Marque todos que se aplicam", list(PROBLEMAS), format_func=PROBLEMAS.get,
                           placeholder="Escolha um ou mais problemas")

st.subheader("4. Próximo plantio")
c1, c2 = st.columns(2)
data = c1.date_input("Data esperada do plantio", value=date.today() + timedelta(days=30), min_value=date.today(), format="DD/MM/YYYY")
quer = c2.selectbox("O que você quer plantar", sorted(CULTURAS), index=sorted(CULTURAS).index("Soja"))

st.subheader("5. O que você quer melhorar")
objetivos = st.multiselect("Marque todos que fazem sentido", list(OBJETIVOS), format_func=OBJETIVOS.get,
                           placeholder="Escolha um ou mais objetivos")

if st.button("Ver recomendação", type="primary"):
    st.session_state["ver"] = True

if st.session_state.get("ver"):
    st.divider()
    st.subheader(f"Recomendação para {cidade} - {estado}")
    if not objetivos:
        st.info("Nenhum objetivo marcado: as notas usam só a época de plantio, a rotação e os problemas informados.")
    ctx = dict(objetivos=objetivos, problemas=problemas, data=data,
               ultimo=ultimo, penultimo=penultimo)
    res = sorted((avaliar(n, c, ctx) for n, c in CULTURAS.items()), key=lambda r: -r["nota"])
    n = len(res)
    melhor, medio, pior = res[0], res[n // 2], res[-1]

    pos_quer = next(i for i, r in enumerate(res, 1) if r["nome"] == quer)
    msg = f"Você quer plantar **{quer}**: ficou em {pos_quer}º lugar entre {n} opções (nota {res[pos_quer - 1]['nota']})."
    (st.success if pos_quer <= n // 3 else st.error if pos_quer > n - n // 3 else st.warning)(msg)

    k1, k2, k3 = st.columns(3)
    k1.markdown(cartao("Mais recomendada", "verde", melhor), unsafe_allow_html=True)
    k2.markdown(cartao("Razoável", "amarelo", medio), unsafe_allow_html=True)
    k3.markdown(cartao("Não recomendada", "vermelho", pior), unsafe_allow_html=True)

    st.caption("Ferramenta de apoio: não substitui a avaliação do agrônomo e o conhecimento local da área.")
