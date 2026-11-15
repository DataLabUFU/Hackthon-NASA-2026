import pandas as pd
import streamlit as st

import dados
import scoring as sc

st.set_page_config(page_title="Próxima cultura na rotação", layout="wide")
cult, mer = sc.carregar()
MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
nomes = list(cult.index)


@st.cache_data(show_spinner="Buscando clima na NASA POWER...")
def buscar_clima(lat, lon):
    return dados.clima_power(lat, lon)


st.title("Qual cultura entra a seguir na rotação?")
st.caption("Ferramenta de apoio à decisão. Não substitui o julgamento do agrônomo nem a avaliação local.")

with st.sidebar:
    st.header("1. Local e clima")
    lat = st.number_input("Latitude", value=-18.92, format="%.4f")
    lon = st.number_input("Longitude", value=-48.28, format="%.4f")
    offline = st.checkbox("Usar clima de exemplo (sem internet)")
    ajuste_chuva = st.slider("Cenário: chuva (%)", -40, 40, 0, help="Use para testar um ano mais seco ou mais chuvoso.")
    ajuste_temp = st.slider("Cenário: temperatura (°C)", -2.0, 4.0, 0.0, 0.5)

    st.header("2. Solo")
    auto = st.checkbox("Tentar buscar textura e matéria orgânica (SoilGrids/SSURGO)")
    solo_api = {}
    if auto:
        try:
            solo_api = dados.solo_auto(lat, lon)
        except Exception as e:
            st.warning(f"Não consegui buscar o solo ({e}). Preencha à mão.")
    compactacao = st.slider("Compactação (0 solto a 5 muito compactado)", 0.0, 5.0, 2.0, 0.5,
                            help="Avaliação de campo: penetrômetro ou perfil cultural.")
    argila = st.number_input("Argila (%)", 0.0, 100.0, float(solo_api.get("argila_pct", 30.0)))
    mo = st.number_input("Matéria orgânica (%)", 0.0, 15.0, float(solo_api.get("mo_pct", 2.5)))
    decliv = st.number_input("Declividade (%)", 0.0, 60.0, 3.0, help="Pode vir do SRTM (veja dados.ee_indicadores).")

    st.header("3. Rotação")
    mes_plantio = st.selectbox("Mês de plantio desta cultura", range(1, 13), index=2, format_func=lambda m: MESES[m - 1])
    ant1 = st.selectbox("Cultura anterior (mais recente)", nomes, index=nomes.index("soja"))
    ant2 = st.selectbox("Antes dela", nomes, index=nomes.index("milho"))
    seg = st.selectbox("Cultura seguinte planejada", ["(nenhuma)"] + nomes, index=1 + nomes.index("soja"))
    mes_seg = st.selectbox("Mês de plantio da seguinte", range(1, 13), index=9, format_func=lambda m: MESES[m - 1]) \
        if seg != "(nenhuma)" else None
    base = st.selectbox("Cultura que você plantaria normalmente (comparação)", nomes, index=nomes.index("milho"))
    candidatas = st.multiselect("Culturas candidatas", nomes, default=nomes)

origem = {k: "api" for k in ("argila_pct", "mo_pct") if k in solo_api}
p = sc.Perfil(mes_plantio=mes_plantio, culturas_anteriores=[ant1, ant2],
              cultura_seguinte=None if seg == "(nenhuma)" else seg, mes_cultura_seguinte=mes_seg,
              compactacao=compactacao, argila_pct=argila, mo_pct=mo, declividade_pct=decliv, origem=origem)

st.subheader("O que importa para você")
st.caption("Os pesos iniciais já respondem ao solo informado. Ajuste como quiser (0 = ignorar, 10 = essencial).")
sug = sc.sugerir_pesos(p)
cols = st.columns(len(sc.CRITERIOS))
for col, (k, nome) in zip(cols, sc.CRITERIOS.items()):
    p.pesos[k] = col.slider(nome, 0, 10, sug[k], key=f"w_{k}_{sug[k]}")

try:
    clima = sc.clima_sintetico() if offline else buscar_clima(lat, lon)
except Exception as e:
    st.error(f"Falha ao buscar o clima ({e}). Marque 'Usar clima de exemplo' para testar.")
    st.stop()
if offline:
    st.info("Usando clima de exemplo (sintético). Os resultados são ilustrativos.")

anom = dados.anomalia_umidade(clima)
c1, c2 = st.columns(2)
c1.metric("Umidade da zona radicular (30 dias vs. normal)", "sem dados" if anom is None else f"{anom:+.1f} desvios",
          help="Valores muito negativos indicam solo mais seco que o normal da época (NASA POWER).")
c2.metric("Anos de clima usados", int(clima.index.year.nunique()))

res = sc.pontuar(cult, mer, clima, p, ajuste_chuva, ajuste_temp, candidatas or nomes)

st.subheader("Ranking")
tabela = res[["cultura", "nota"]].copy()
if base in set(res.cultura):
    nb = float(res.loc[res.cultura == base, "nota"].iloc[0])
    tabela["vs_" + base] = (tabela["nota"] - nb).round(1)
st.dataframe(tabela, hide_index=True)
st.bar_chart(res.set_index("cultura")[[f"c_{k}" for k in sc.CRITERIOS]].rename(columns=lambda c: sc.CRITERIOS[c[2:]]))
st.caption("Cada barra mostra quanto cada critério contribuiu para a nota. Culturas fora da janela de plantio perdem 15%.")

st.subheader("As 3 melhores e a sua cultura de referência")
mostrar = list(res.cultura[:3]) + ([base] if base in set(res.cultura) and base not in list(res.cultura[:3]) else [])
for col, n in zip(st.columns(len(mostrar)), mostrar):
    r = res[res.cultura == n].iloc[0]
    with col:
        st.markdown(f"**{n}** ({r.nota})" + (" · referência" if n == base else ""))
        st.markdown("**A favor**")
        for t in r.positivos or ["nada de especial a favor com esses pesos"]:
            st.write(f"- {t}")
        st.markdown("**Riscos**")
        for t in r.riscos or ["nenhum risco óbvio nos dados"]:
            st.write(f"- {t}")

st.subheader("O que a ferramenta não sabe")
for t in sc.lacunas(p):
    st.write(f"- {t}")

with st.expander("Previsão de 16 dias (informativa, não entra na nota)"):
    if st.button("Buscar previsão"):
        try:
            prev = dados.previsao_16d(lat, lon)
            st.line_chart(prev[["tmax", "tmin"]])
            st.bar_chart(prev["chuva_mm"])
        except Exception as e:
            st.warning(f"Não consegui buscar a previsão: {e}")

with st.expander("Como a nota é calculada"):
    st.markdown("""
Nota = média ponderada de 7 critérios (0 a 1), vezes 100, onde os pesos são os seus.
- **Descompactar / cobertura / nitrogênio:** traços de cada cultura em `culturas.csv`.
- **Água:** chuva esperada no ciclo (mediana e ano seco, histórico NASA POWER) contra a necessidade da cultura.
  Solo arenoso e declive aproveitam menos chuva; culturas tolerantes à seca precisam de menos.
- **Temperatura:** média esperada contra a faixa ideal, com penalidade se a mínima ficar abaixo do limite da cultura.
- **Mercado:** margem (receita menos custo) de `mercado.csv`, normalizada entre as candidatas.
- **Sequência:** muda de família botânica? Prepara a cultura seguinte? Cabe no calendário?
""")
