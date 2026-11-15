"""Camada de dados e decisão do AgroData.

Este é o ÚNICO arquivo que liga a interface ao modelo. A interface (app_teste.py) só lê o `Resultado`.
O modelo real (`motor_modelo`) usa o recomendador de sete torres em `towers/` (towers.combinador.recomendar);
é o padrão quando os dados estão baixados (scripts/preparar_dados.py). `motor_mock` continua para demonstração.

Fluxo:  Entrada (formulário)
          -> coletar_dados_externos(entrada)   [hoje MOCK: clima, solo, mercado]
          -> MOTORES[nome](entrada, dados)     [hoje MOCK: resultado fixo]
          -> Resultado (3 listas de Recomendacao)

Para ligar o modelo:
  1. Implemente `motor_modelo` (ou troque os mocks de `obter_*` por dados reais).
  2. Rode o app com a variável de ambiente  MOTOR_RECOMENDACAO=modelo
  3. O motor pode devolver um `Resultado` ou um dict/JSON no formato abaixo (use `resultado_de_dict`).

Formato JSON esperado do modelo:
{
  "recomendadas":     [ {"cultura": "Milheto", "descricao": "...", "motivos": ["...", "..."],
                         "clima": {"temperatura": "25°C a 35°C", "chuva": "400 a 600 mm no ciclo",
                                   "epoca": "Verão", "adaptacao": "Boa tolerância à seca"}} ],
  "razoaveis":        [ ... ],
  "nao_recomendadas": [ ... ]
}
A ordem de cada lista é o ranking (o primeiro é o 1º lugar).
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Callable, Optional

log = logging.getLogger(__name__)

# ------------------------------------------------------------------ listas do formulário
# Vêm dos dados do recomendador (towers/): culturas do catálogo e todos os municípios do IBGE.
# Sem os dados baixados (ver scripts/preparar_dados.py), ficam as listas de exemplo abaixo.
_HISTORICO_EXEMPLO = ["Soja", "Milho", "Trigo", "Algodão", "Feijão", "Sorgo", "Girassol", "Milheto", "Pastagem"]
_DESEJADAS_EXEMPLO = ["Sem preferência", "Soja", "Milho", "Trigo", "Algodão", "Feijão", "Sorgo",
                      "Girassol", "Milheto", "Outra / Indiferente"]
_ESTADOS_EXEMPLO = {
    "MG": ("Minas Gerais", ["Uberlândia", "Uberaba", "Araguari", "Patos de Minas"]),
    "GO": ("Goiás", ["Goiânia", "Rio Verde", "Jataí"]),
    "SP": ("São Paulo", ["Ribeirão Preto", "Campinas", "São Paulo"]),
    "MT": ("Mato Grosso", ["Cuiabá", "Rondonópolis", "Sorriso"]),
    "MS": ("Mato Grosso do Sul", ["Campo Grande", "Dourados", "Três Lagoas"]),
}
NOME_UF = {
    "AC": "Acre", "AL": "Alagoas", "AM": "Amazonas", "AP": "Amapá", "BA": "Bahia", "CE": "Ceará",
    "DF": "Distrito Federal", "ES": "Espírito Santo", "GO": "Goiás", "MA": "Maranhão", "MG": "Minas Gerais",
    "MS": "Mato Grosso do Sul", "MT": "Mato Grosso", "PA": "Pará", "PB": "Paraíba", "PE": "Pernambuco", "PI": "Piauí",
    "PR": "Paraná", "RJ": "Rio de Janeiro", "RN": "Rio Grande do Norte", "RO": "Rondônia", "RR": "Roraima",
    "RS": "Rio Grande do Sul", "SC": "Santa Catarina", "SE": "Sergipe", "SP": "São Paulo", "TO": "Tocantins",
}
TIPOS_CULTURA = {
    "graos": "Grãos, oleaginosas e fibras", "hortalicas": "Hortaliças", "frutas": "Frutas",
    "raizes": "Raízes e tubérculos", "forrageiras": "Forrageiras e plantas de cobertura",
    "industriais_perenes": "Perenes industriais (café, cana...)", "aromaticas": "Aromáticas e medicinais",
    "silvicultura": "Silvicultura", "outras": "Outras",
}


def _carregar_listas():
    """(histórico, desejadas, estados, municípios, dados_reais). Nunca falha: cai nas listas de exemplo."""
    try:
        from towers.data import neon
        neon.garantir_arquivos()   # clone novo / Streamlit Cloud: ECOCROP, municípios, PTF e GBIF vêm do banco
        from towers.data.culturas import carregar_culturas
        from towers.data.municipios import carregar_municipios
        from towers.data.taxonomia import CACHE_PADRAO as CACHE_GBIF
        cat = carregar_culturas(usar_gbif=CACHE_GBIF.exists()).filter("exibivel")
        curadas = sorted(cat.filter("obrigatoria")["nome_pt"].unique().to_list(), key=str.casefold)
        todas = sorted(cat["nome_pt"].unique().to_list(), key=str.casefold)
        mun = carregar_municipios(baixar=True)
        estados = {uf: (NOME_UF.get(uf, uf), sorted(g["nome"].to_list(), key=str.casefold))
                   for (uf,), g in mun.group_by("uf")}
        return ["Pousio", *curadas], ["Sem preferência", *todas], dict(sorted(estados.items())), mun, True
    except Exception:  # dados ausentes (ex.: clone novo): a interface continua funcionando com o mock
        return _HISTORICO_EXEMPLO, _DESEJADAS_EXEMPLO, _ESTADOS_EXEMPLO, None, False


CULTURAS_HISTORICO, CULTURAS_DESEJADAS, ESTADOS, _MUNICIPIOS, DADOS_REAIS = _carregar_listas()

# valor (enviado ao modelo)  ->  rótulo (mostrado ao produtor)
PROBLEMAS = {v: v for v in [
    "Compactação do solo", "Baixa retenção de água", "Deficiência de nitrogênio", "Presença de pragas",
    "Incidência de doenças", "Baixo teor de matéria orgânica", "Erosão do solo", "Plantas daninhas"]}
OBJETIVOS = {
    "Reduzir compactação": "Reduzir compactação", "Reter água": "Melhorar retenção de água",
    "Aumentar nitrogênio": "Aumentar nitrogênio", "Controlar pragas": "Controlar pragas",
    "Controlar doenças": "Reduzir doenças", "Aumentar matéria orgânica": "Aumentar matéria orgânica",
    "Melhorar estrutura do solo": "Melhorar estrutura do solo", "Reduzir erosão": "Reduzir erosão",
    "Aumentar produtividade": "Aumentar produtividade", "Acesso a crédito e seguro": "Manter acesso a crédito e seguro",
}

# Como o formulário vira entrada das torres:
# - problemas que são atributo do solo -> Torre 3; os demais reforçam o perfil de rotação/solo nos pesos
PROBLEMA_PARA_SOLO = {"Compactação do solo": "compactado", "Baixa retenção de água": "arenoso",
                      "Baixo teor de matéria orgânica": "pouco_fertil"}
PROBLEMA_PARA_PERFIL = {"Baixa retenção de água": "evitar_seca", "Deficiência de nitrogênio": "saude_do_solo",
                        "Presença de pragas": "saude_do_solo", "Incidência de doenças": "saude_do_solo",
                        "Erosão do solo": "saude_do_solo", "Plantas daninhas": "saude_do_solo",
                        "Compactação do solo": "saude_do_solo", "Baixo teor de matéria orgânica": "saude_do_solo"}
# - cada objetivo marcado aponta para um perfil de pesos do combinador (towers/combinador/pesos.py)
OBJETIVO_PARA_PERFIL = {"Reter água": "evitar_seca", "Aumentar produtividade": "estabilidade",
                        "Acesso a crédito e seguro": "financiamento"}   # os demais: "saude_do_solo"
PESO_PROBLEMA = 0.5   # nos pesos das torres, um problema relatado pesa metade de um objetivo explícito
# - objetivos e problemas viram benefícios que a cultura deve entregar (towers/combinador/preferencias.py):
#   a aderência pesa direto na nota de cada cultura; objetivo e problema têm o mesmo peso
OBJETIVO_PARA_BENEFICIO = {
    "Reduzir compactação": "descompactar", "Reter água": "reter_agua", "Aumentar nitrogênio": "fixar_nitrogenio",
    "Controlar pragas": "controlar_pragas", "Controlar doenças": "controlar_doencas",
    "Aumentar matéria orgânica": "materia_organica", "Melhorar estrutura do solo": "estrutura_solo",
    "Reduzir erosão": "controlar_erosao",
}   # "Aumentar produtividade" e "Acesso a crédito e seguro" agem pelos pesos e pelo filtro de crédito
PROBLEMA_PARA_BENEFICIO = {
    "Compactação do solo": "descompactar", "Baixa retenção de água": "reter_agua",
    "Deficiência de nitrogênio": "fixar_nitrogenio", "Presença de pragas": "controlar_pragas",
    "Incidência de doenças": "controlar_doencas", "Baixo teor de matéria orgânica": "materia_organica",
    "Erosão do solo": "controlar_erosao", "Plantas daninhas": "controlar_daninhas",
}


# ------------------------------------------------------------------ modelos de dados
@dataclass
class Entrada:
    """Tudo que o produtor informou. É isto que o modelo recebe."""
    penultimo: Optional[str] = None
    ultimo: Optional[str] = None
    uf: Optional[str] = None
    cidade: Optional[str] = None
    data_plantio: Optional[date] = None
    cultura_desejada: Optional[str] = None          # None = sem preferência
    problemas: list = field(default_factory=list)
    objetivos: list = field(default_factory=list)
    tipos_cultura: list = field(default_factory=list)  # vazio = todos os tipos

    def para_dict(self) -> dict:
        d = asdict(self)
        d["data_plantio"] = self.data_plantio.isoformat() if self.data_plantio else None
        return d


@dataclass
class Clima:
    temperatura: str = "—"
    chuva: str = "—"
    epoca: str = "—"
    adaptacao: str = "—"


@dataclass
class Recomendacao:
    cultura: str
    descricao: str = ""
    motivos: list = field(default_factory=list)
    clima: Clima = field(default_factory=Clima)


@dataclass
class Resultado:
    recomendadas: list = field(default_factory=list)      # verde
    razoaveis: list = field(default_factory=list)         # amarelo
    nao_recomendadas: list = field(default_factory=list)  # vermelho
    fonte: str = "mock"                                   # "mock" ou "modelo"
    observacoes: list = field(default_factory=list)       # notas do modelo exibidas no resumo
    detalhes: dict = field(default_factory=dict)          # notas por critério e local (painel de estatísticas)

    def para_dict(self) -> dict:
        return asdict(self)


ENTRADA_DEMO = Entrada(penultimo="Milho", ultimo="Soja", uf="MG", cidade="Uberlândia", data_plantio=date.today())


def validar_entrada(e: Entrada) -> list:
    """Devolve o que falta preencher (lista vazia = tudo certo)."""
    faltam = []
    if not e.penultimo or not e.ultimo:
        faltam.append("os dois últimos plantios")
    if not e.uf or not e.cidade:
        faltam.append("a localização")
    if not e.data_plantio:
        faltam.append("a data prevista")
    return faltam


# ------------------------------------------------------------------ fontes de dados (MOCK)
# Troque cada função pela chamada real (NASA POWER, SoilGrids/SSURGO, Cepea/Conab...).
def obter_clima(e: Entrada) -> dict:
    return {"fonte": "mock", "chuva_mm_mensal": [250, 200, 180, 80, 30, 10, 10, 15, 50, 130, 210, 260],
            "temp_media_c": [24, 24, 24, 23, 21, 20, 20, 22, 24, 25, 24, 24]}


def obter_solo(e: Entrada) -> dict:
    return {"fonte": "mock", "argila_pct": 35, "materia_organica_pct": 2.4, "compactacao": "média"}


def obter_mercado(e: Entrada) -> dict:
    return {"fonte": "mock", "margem_ha": {"Soja": 2000, "Milho": 1700, "Milheto": 600}}


def coletar_dados_externos(e: Entrada) -> dict:
    return {"clima": obter_clima(e), "solo": obter_solo(e), "mercado": obter_mercado(e)}


def localizar_municipio(uf: Optional[str], cidade: Optional[str]) -> Optional[dict]:
    """geocodigo, lat, lon do município escolhido no formulário (None sem dados reais)."""
    if _MUNICIPIOS is None or not uf or not cidade:
        return None
    import polars as pl
    m = _MUNICIPIOS.filter((pl.col("uf") == uf) & (pl.col("nome") == cidade))
    return m.row(0, named=True) if m.height else None


def obter_estatisticas(e: Entrada) -> dict:
    """Chuva e temperatura médias mensais do município (NASA POWER); sem dados reais, valores fictícios."""
    meses = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
    rotulos = [f"{i + 1:02d} {m}" for i, m in enumerate(meses)]   # prefixo numérico mantém a ordem no gráfico
    mun = localizar_municipio(e.uf, e.cidade)
    if mun is not None:
        try:
            import polars as pl
            from towers.data.power import CHUVA, clima_diario
            c = clima_diario(mun["lat"], mun["lon"])
            completos = c.filter(pl.col("data").dt.year() < c["data"].max().year)
            chuva = (completos.group_by(pl.col("data").dt.year().alias("a"), pl.col("data").dt.month().alias("m"))
                     .agg(pl.col(CHUVA).sum()).group_by("m").agg(pl.col(CHUVA).mean()).sort("m"))
            temp = c.group_by(pl.col("data").dt.month().alias("m")).agg(pl.col("T2M").mean()).sort("m")
            a0, a1 = c["data"].min().year, c["data"].max().year
            return {"meses": rotulos, "chuva_mm": [round(v, 0) for v in chuva[CHUVA].to_list()],
                    "temp_c": [round(v, 1) for v in temp["T2M"].to_list()],
                    "aviso": f"Médias de {a0} a {a1} em {mun['nome']}-{mun['uf']}: chuva do GPM IMERG e "
                             f"temperatura do MERRA-2, via NASA POWER."}
        except Exception:
            pass
    clima = obter_clima(e)
    return {"meses": rotulos, "chuva_mm": clima["chuva_mm_mensal"], "temp_c": clima["temp_media_c"],
            "aviso": "Dados fictícios, apenas para teste da interface."}


# ------------------------------------------------------------------ motores
def _rec(cultura, descricao, motivos, temp, chuva, epoca, adaptacao):
    return Recomendacao(cultura, descricao, motivos, Clima(temp, chuva, epoca, adaptacao))


def motor_mock(e: Entrada, dados: dict) -> Resultado:
    """Resultado fixo (ignora a entrada). Serve para testar a interface."""
    return Resultado(fonte="mock", recomendadas=[
        _rec("Milheto", "Alternativa para cobertura e recuperação do solo.",
             ["Contribui para a formação de palhada e proteção do solo.",
              "Possui sistema radicular que auxilia na melhoria da estrutura física.",
              "Ajuda a reduzir perdas de água por evaporação.", "Contribui para a ciclagem de nutrientes."],
             "25°C a 35°C", "400 a 600 mm no ciclo", "Verão / transição", "Boa tolerância à seca"),
        _rec("Crotalária", "Leguminosa utilizada na cobertura e melhoria do sistema produtivo.",
             ["Auxilia na fixação biológica de nitrogênio.", "Contribui para a produção de biomassa.",
              "Pode auxiliar no manejo de determinados nematoides, conforme a espécie.",
              "Favorece a diversificação da rotação de culturas."],
             "20°C a 30°C", "400 a 700 mm no ciclo", "Primavera / verão", "Boa adaptação ao calor"),
        _rec("Girassol", "Opção de diversificação e aproveitamento do sistema produtivo.",
             ["Apresenta sistema radicular profundo.", "Contribui para a diversificação de culturas.",
              "Pode aproveitar nutrientes em camadas mais profundas.",
              "Possibilita uma alternativa de produção e renda."],
             "20°C a 30°C", "400 a 600 mm no ciclo", "Conforme calendário regional", "Tolerância moderada à seca"),
    ], razoaveis=[
        _rec("Feijão", "Possibilidade de cultivo com atenção ao manejo.",
             ["Pode diversificar o sistema produtivo.",
              "Possui ciclo relativamente curto e pode deixar o solo mais descompactado.",
              "Permite diversificação de renda na propriedade.",
              "Exige atenção ao histórico de doenças e pragas."],
             "18°C a 30°C", "300 a 450 mm no ciclo", "Conforme calendário regional", "Exige manejo hídrico"),
        _rec("Sorgo", "Alternativa com potencial de adaptação a condições de menor disponibilidade hídrica.",
             ["Apresenta boa tolerância relativa à seca.",
              "Pode ser utilizado para produção de grãos ou forragem, deixando o solo mais descompactado.",
              "Contribui para a diversificação do sistema.",
              "É necessário avaliar o histórico fitossanitário da área."],
             "25°C a 32°C", "400 a 600 mm no ciclo", "Verão / safrinha", "Boa tolerância à seca"),
        _rec("Milho", "Alternativa produtiva que depende do histórico e das condições da área.",
             ["Possui ampla utilização comercial.", "Permite diversificação em relação a outras culturas.",
              "Pode contribuir para a produção de palhada.",
              "Exige atenção à disponibilidade de água e nutrientes."],
             "20°C a 30°C", "500 a 800 mm no ciclo", "Conforme zoneamento", "Exige boa disponibilidade hídrica"),
    ], nao_recomendadas=[
        _rec("Soja", "Menor adequação ao cenário hipotético analisado.",
             ["O cultivo sucessivo pode favorecer a manutenção de doenças específicas.",
              "Há necessidade de avaliar o histórico de pragas da área.",
              "Pode não atender ao objetivo de diversificação da rotação.",
              "Requer análise da fertilidade e do histórico fitossanitário."],
             "20°C a 30°C", "450 a 800 mm no ciclo", "Conforme zoneamento", "Depende da cultivar"),
        _rec("Algodão", "Cultura que pode exigir condições específicas de manejo e investimento.",
             ["Possui manejo fitossanitário complexo.", "Exige monitoramento frequente de pragas.",
              "Pode demandar maior investimento operacional.", "É necessário avaliar as condições locais de cultivo."],
             "20°C a 30°C", "500 a 1.000 mm no ciclo", "Conforme zoneamento", "Sensível ao excesso de umidade"),
        _rec("Trigo", "Alternativa que pode apresentar limitações conforme as condições climáticas regionais.",
             ["Depende de condições climáticas adequadas durante o ciclo.",
              "Pode apresentar maior risco em regiões muito quentes.",
              "Exige avaliação do calendário agrícola regional.", "Necessita de análise da viabilidade econômica local."],
             "15°C a 25°C", "450 a 600 mm no ciclo", "Outono / inverno", "Depende da região e cultivar"),
    ])


def pesos_da_entrada(e: Entrada) -> tuple[dict, bool]:
    """(pesos das torres, somente_financiaveis) a partir dos objetivos e problemas marcados.

    Cada objetivo aponta para um perfil de pesos; problemas relatados entram com metade do peso.
    Sem nada marcado, vale o perfil "equilibrado".
    """
    from towers.combinador.pesos import OBJETIVOS as PERFIS
    escolhas = [(OBJETIVO_PARA_PERFIL.get(o, "saude_do_solo"), 1.0) for o in e.objetivos]
    escolhas += [(PROBLEMA_PARA_PERFIL[p], PESO_PROBLEMA) for p in e.problemas if p in PROBLEMA_PARA_PERFIL]
    if not escolhas:
        escolhas = [("equilibrado", 1.0)]
    total = sum(w for _, w in escolhas)
    torres = PERFIS["equilibrado"]["pesos"].keys()
    pesos = {t: sum(PERFIS[perfil]["pesos"][t] * w for perfil, w in escolhas) / total for t in torres}
    return pesos, "Acesso a crédito e seguro" in e.objetivos


def beneficios_da_entrada(e: Entrada) -> dict[str, float]:
    """{benefício: peso} pedidos pelo produtor (objetivos e problemas marcados, mesmo peso cada)."""
    pedidos: dict[str, float] = {}
    for b in [OBJETIVO_PARA_BENEFICIO.get(o) for o in e.objetivos] + [PROBLEMA_PARA_BENEFICIO.get(p) for p in e.problemas]:
        if b:
            pedidos[b] = pedidos.get(b, 0.0) + 1.0
    return pedidos


# o que atenderia cada pedido, quando a cultura do cartão não atende
EXEMPLOS_BENEFICIO = {
    "fixar_nitrogenio": "leguminosas como crotalária, feijão-guandu, mucuna ou soja",
    "descompactar": "nabo-forrageiro, braquiária, milheto ou crotalária",
    "materia_organica": "culturas de muita palhada, como milheto, braquiária, sorgo ou milho",
    "estrutura_solo": "milheto, braquiária, nabo-forrageiro ou crotalária",
    "reter_agua": "culturas de muita palhada, como milheto, braquiária, sorgo ou milho",
    "controlar_erosao": "plantas de cobertura (milheto, braquiária, crotalária) ou pastagem",
    "controlar_pragas": "crotalária ou mucuna (reduzem nematoides) ou uma cultura de outra família",
    "controlar_doencas": "uma cultura de família botânica diferente da última safra",
    "controlar_daninhas": "braquiária, aveia-preta ou milheto, que abafam as daninhas",
}


def _rotulo(texto: str) -> str:
    return f"“{texto[:1].lower() + texto[1:]}”"


def _juntar(itens: list[str]) -> str:
    return itens[0] if len(itens) == 1 else ", ".join(itens[:-1]) + " e " + itens[-1]


def _ancora_pedidos(itens: list[tuple[str, str]]) -> str:
    """'Seu objetivo “a” e o problema “b”' (sem repetir o mesmo rótulo)."""
    obj = list(dict.fromkeys(_rotulo(x) for t, x in itens if t == "objetivo"))
    prob = list(dict.fromkeys(_rotulo(x) for t, x in itens if t == "problema"))
    partes = []
    if obj:
        partes.append(("Seu objetivo " if len(obj) == 1 else "Seus objetivos ") + _juntar(obj))
    if prob:
        if obj:
            partes.append(("o problema " if len(prob) == 1 else "os problemas ") + _juntar(prob))
        else:
            partes.append(("Problema informado " if len(prob) == 1 else "Problemas informados ") + _juntar(prob))
    return " e ".join(partes)


def _resposta_ao_pedido(r: dict, codigo: str) -> str:
    from towers.combinador.preferencias import BENEFICIOS
    if codigo in (r.get("beneficios_atendidos") or []):
        return f"atende, {BENEFICIOS[codigo]}."
    if codigo in (r.get("beneficios_parciais") or []):
        return (f"atende em parte ({BENEFICIOS[codigo]}, mas com efeito menor); para resolver de vez, "
                f"prefira {EXEMPLOS_BENEFICIO[codigo]}.")
    return f"não ajuda; para isso, prefira {EXEMPLOS_BENEFICIO[codigo]}."


def _por_que_diferente(r: dict, d: dict) -> str:
    """Por que a cultura ``r`` ficou acima ou abaixo da desejada ``d``: aptidão do local x seus pedidos."""
    ar, ad_ = r.get("score_agronomico"), d.get("score_agronomico")
    xr, xd = r.get("aderencia"), d.get("aderencia")
    nome, alvo = r["nome_pt"], d["nome_pt"]
    fracos = ", ".join(d.get("pontos_fracos") or [])
    if r.get("eliminada"):
        return ""
    if ar is None or ad_ is None:
        return f"; {alvo} perde em {fracos}" if r["score_final"] > d["score_final"] and fracos else ""
    if r["score_final"] < d["score_final"]:
        if ar > ad_ + 0.02 and xr is not None and xd is not None and xr < xd:
            return (f"; {nome} vai melhor no local (aptidão {100 * ar:.0f} contra {100 * ad_:.0f}), mas atende "
                    f"menos ao que você pediu, e {alvo} ganhou prioridade por ser a sua escolha")
        return f"; {alvo} ganhou prioridade por ser a sua escolha" + (
            "" if ar >= ad_ else f" e vai melhor no local (aptidão {100 * ad_:.0f} contra {100 * ar:.0f})")
    if ar > ad_ + 0.02:
        return (f"; {alvo} tem aptidão menor no local ({100 * ad_:.0f} contra {100 * ar:.0f})"
                + (f" e perde em {fracos}" if fracos else ""))
    if xr is not None and xd is not None and xr > xd:
        return f"; {nome} atende melhor ao que você pediu"
    return ""


def _justificativas_do_produtor(r: dict, e: Entrada | None, ctx: dict | None = None) -> list[str]:
    """Uma frase para cada coisa que o produtor informou, começando por ela (``Âncora: resposta``)."""
    if e is None:
        return []
    ctx = ctx or {}
    m = []
    nome = r["nome_pt"]
    # cultura desejada
    if r.get("desejada"):
        m.append(f"Sua cultura desejada ({nome}): " + (
            "ganhou prioridade no ranking e é viável no local." if not r.get("eliminada")
            else f"não é indicada aqui nesta época ({r.get('motivo_eliminacao')})."))
    elif (d := ctx.get("desejada")) and d.get("nome_pt") != nome:
        if d.get("eliminada"):
            m.append(f"Sua cultura desejada ({d['nome_pt']}): não é indicada aqui ({d.get('motivo_eliminacao')}); "
                     f"{nome} é uma alternativa viável.")
        else:
            m.append(f"Sua cultura desejada ({d['nome_pt']}): nota {100 * d['score_final']:.0f} contra "
                     f"{100 * r['score_final']:.0f} de {nome}{_por_que_diferente(r, d)}.")
    # objetivos e problemas com as palavras do produtor; pedidos com a mesma resposta viram uma linha só
    linhas: dict[str, list[tuple[str, str]]] = {}      # resposta → [(tipo, rótulo)], na ordem em que aparecem
    for o in e.objetivos:
        rotulo = OBJETIVOS.get(o, o)
        if (cod := OBJETIVO_PARA_BENEFICIO.get(o)):
            linhas.setdefault(_resposta_ao_pedido(r, cod), []).append(("objetivo", rotulo))
        elif o == "Aumentar produtividade" and r.get("s_t1") is not None and not r.get("eliminada"):
            apta = f", apta em {_pct(r['prob_apta'])} dos anos" if r.get("prob_apta") is not None else ""
            ext = (f"; {_frase_extremos(r)}" if r.get("p_extremo") is not None else "")
            resposta = (f"clima {_qualidade(r['s_t1'])} e água {_qualidade(r.get('s_t2'))} na data "
                        f"sugerida{apta}{ext}.")
            linhas.setdefault(resposta, []).append(("objetivo", rotulo))
        elif o == "Acesso a crédito e seguro":
            resposta = {
                "elegivel": "dentro do zoneamento oficial (ZARC); elegível a custeio, Proagro e seguro rural.",
                "condicional": "elegível, desde que o imóvel esteja regularizado.",
                "inelegivel": "fora das regras de crédito e seguro nesta data.",
            }.get(r.get("status_elegibilidade") or "", "cultura sem zoneamento oficial; confirme com o banco.")
            linhas.setdefault(resposta, []).append(("objetivo", rotulo))
    for p in e.problemas:
        if (cod := PROBLEMA_PARA_BENEFICIO.get(p)):
            linhas.setdefault(_resposta_ao_pedido(r, cod), []).append(("problema", p))
    for resposta, itens in linhas.items():
        m.append(f"{_ancora_pedidos(itens)}: {resposta}")
    # histórico (rotação)
    if e.ultimo:
        hist = f"{e.penultimo} → {e.ultimo}" if e.penultimo else e.ultimo
        regras = []
        for exp in (r.get("explicacao_rotacao") or []):
            regra, _, porque = exp.partition(":")
            regra = regra.rsplit(" (", 1)[0]                    # tira o ajuste numérico, ex.: "(+0.15)"
            regras.append(regra[:1].lower() + regra[1:] + (f" ({porque.strip()})" if porque else ""))
        if regras:
            m.append(f"Seu histórico ({hist}): {nome} entra como {'; '.join(regras)}.")
        elif r.get("s_t5") is None:
            m.append(f"Seu histórico ({hist}): {nome} é perene ou silvicultura; a rotação não se aplica.")
        else:
            m.append(f"Seu histórico ({hist}): sem interação forte entre {e.ultimo} e {nome}.")
    return m


def _alerta_solo(alerta: str, informou_compactacao: bool = False) -> str:
    """'calagem: pH 5.3 abaixo do ideal (5.5–6.5)' → 'pH 5.3 abaixo do ideal (5.5–6.5), corrigível com calagem'."""
    acao, sep, detalhe = alerta.partition(": ")
    if not sep:
        return alerta
    if acao == "solo compactado":
        return ("a compactação que você informou pede " if informou_compactacao else "solo compactado pede ") + detalhe
    if acao in ("calagem", "adubação"):
        return f"{detalhe}, corrigível com {acao}"
    return f"{acao}: {detalhe}"


def _frase_extremos(r: dict) -> str:
    """T7: chance de chuva forte/persistente ou de frio nas fases sensíveis do ciclo da cultura."""
    pe, pc, pf = r.get("p_extremo"), r.get("p_extremo_chuva"), r.get("p_extremo_frio")
    enso = r.get("enso_fase")
    com_enso = f", considerando o {enso} atual" if enso in ("El Niño", "La Niña") else ""
    if pe == 0:
        return "nenhum extremo de chuva ou frio nas fases sensíveis do ciclo desde 2001"
    detalhe = []
    if pc:
        detalhe.append(f"chuva forte ou persistente {_pct(pc)}")
    if pf:
        detalhe.append(f"frio na fase sensível {_pct(pf)}")
    return (f"chance de extremo climático de {_pct(pe)}{com_enso}"
            + (f" (no histórico desde 2001: {', '.join(detalhe)} dos anos)" if detalhe else ""))


def _justificativas_do_local(r: dict, e: Entrada | None) -> list[str]:
    """Data informada (clima, água, ZARC) e região (solo), ancoradas no que o produtor escolheu."""
    m = []
    data = e.data_plantio if e is not None else None
    if data and r["plantio"] != data:
        dias = (r["plantio"] - data).days
        ancora = (f"Na data que você informou ({data:%d/%m}): o melhor plantio é em {r['plantio']:%d/%m}, "
                  f"{abs(dias)} dias {'depois' if dias > 0 else 'antes'}")
    elif data:
        ancora = f"Na data que você informou ({data:%d/%m})"
    else:
        ancora = f"No plantio em {r['plantio']:%d/%m}"
    partes = []
    s1, s2 = r.get("s_t1"), r.get("s_t2")
    if s1 is not None:
        partes.append(f"clima {_qualidade(s1)}" + ("" if s1 >= 0.7 else
                                                   f" ({LIMITANTE_CLIMA.get(r.get('fator_limitante'), 'clima')})"))
    if s2 is not None:
        falta = r.get("irrigacao_mm") or 0
        partes.append("baixo risco de faltar água" if s2 >= 0.85 else f"faltam em média {falta:.0f} mm de água no ciclo")
    if (pe := r.get("p_extremo")) is not None:
        partes.append(_frase_extremos(r))
    z = r.get("zarc_status")
    if z == "indicado":
        partes.append(f"indicada pelo zoneamento oficial (risco de até {r.get('risco_zarc_pct')}%)")
    elif z == "nao_indicado":
        partes.append("fora da janela do zoneamento oficial")
    if partes:
        sep = "; " if data and r["plantio"] != data else ": "
        m.append(f"{ancora}{sep}{'; '.join(partes)}.")
    if r.get("alerta_ciclo_extremo"):
        m.append("Para o ciclo nesta data: exige cultivar muito precoce ou tardia.")
    if r.get("alerta_foto_mensagem"):
        m.append(r["alerta_foto_mensagem"])
    lugar = f"Em {e.cidade}-{e.uf}" if e is not None and e.cidade else "No local"
    s3 = r.get("s_t3")
    informou_compactacao = e is not None and "Compactação do solo" in e.problemas
    solo = [_alerta_solo(a, informou_compactacao) for a in (r.get("alertas_solo") or [])[:3]]
    if s3 is not None and s3 < 0.6 and r.get("fator_limitante_solo"):
        solo.insert(0, f"solo pouco adequado ({r['fator_limitante_solo']})")
    if solo:
        m.append(f"{lugar}: {'; '.join(solo)}.")
    elif s3 is not None:
        m.append(f"{lugar}: solo adequado para {r['nome_pt']}.")
    return m


LIMITANTE_CLIMA = {"geada": "risco de geada", "temperatura": "temperatura fora da faixa ideal",
                   "chuva": "chuva insuficiente ou excessiva no ciclo",
                   "pegamento": "pouca chuva logo após o plantio (germinação e pegamento)"}


def _qualidade(s: float | None) -> str:
    if s is None:
        return "sem avaliação"
    return "muito favorável" if s >= 0.85 else "favorável" if s >= 0.7 else "razoável" if s >= 0.5 else "limitante"


def _pct(x) -> str:
    return "—" if x is None else f"{100 * x:.0f}%"


def _recomendacao_de_linha(r: dict, cat: dict, e: Entrada | None = None, ctx: dict | None = None) -> Recomendacao:
    """Uma linha do ranking do recomendador -> card do front.

    Cada justificativa começa pela informação do produtor a que responde ("Seu objetivo “…”: …",
    "Seu histórico (…)", "Na data que você informou (…)", "Em Cidade-UF: …"). ``ctx``: {"desejada": linha
    da cultura desejada no ranking}, para comparar as outras culturas com ela."""
    c = cat.get(r["id_cultura"], {})
    ciclo = r.get("ciclo_dias")
    tipo = TIPOS_CULTURA.get(r.get("tipo_cultura") or "", "")
    eleg = {"elegivel": "Elegível a crédito de custeio, Proagro e seguro.",
            "condicional": "Crédito condicionado à regularização do imóvel.",
            "inelegivel": "Fora das regras de crédito/seguro nesta data.",
            "a_verificar": "Elegibilidade a crédito: a verificar."}.get(r.get("status_elegibilidade") or "", "")
    descricao = (f"Plantio sugerido em {r['plantio']:%d/%m/%Y}" + (f" (ciclo de ~{ciclo} dias)" if ciclo else "")
                 + f". Nota {100 * r['score_final']:.0f}/100"
                 + (f" para o seu caso (aptidão do local {100 * agro:.0f}/100)"
                    if (agro := r.get("score_agronomico")) is not None and not r.get("eliminada")
                    and abs(agro - r["score_final"]) >= 0.02 else "")
                 + (f" · {tipo}" if tipo else "") + f". {eleg}")

    m = _justificativas_do_produtor(r, e, ctx)
    if r.get("eliminada") and not r.get("desejada"):
        m.insert(1 if ctx and ctx.get("desejada") else 0, f"Não indicada: {r.get('motivo_eliminacao')}.")
    m += _justificativas_do_local(r, e)
    credito_no_objetivo = e is not None and "Acesso a crédito e seguro" in e.objetivos
    if not credito_no_objetivo and r.get("status_elegibilidade") == "elegivel" and r.get("portaria_zarc"):
        m.append(f"Crédito e seguro: dentro do ZARC ({r['portaria_zarc'].replace('_', ' ')}).")

    outras = [d.strftime("%d/%m") for d in (r.get("outras_datas_boas") or []) if d != r["plantio"]]
    clima = Clima(
        temperatura=f"{c['TOPMN']:.0f}°C a {c['TOPMX']:.0f}°C (faixa ótima)" if c.get("TOPMN") is not None else "—",
        chuva=f"{c['ROPMN']:.0f} a {c['ROPMX']:.0f} mm (faixa ótima)" if c.get("ROPMN") is not None else "—",
        epoca=f"{r['plantio']:%d/%m}" + (f"; também bom: {', '.join(outras[:3])}" if outras else ""),
        adaptacao=(f"Apta em {_pct(r['prob_apta'])} dos anos (NASA POWER)" if r.get("prob_apta") is not None else "—"),
    )
    return Recomendacao(r["nome_pt"], descricao, m, clima)


def motor_modelo(e: Entrada, dados: dict) -> Resultado:
    """Recomendador real: as sete torres (towers/) combinadas e ordenadas em três setores."""
    import polars as pl
    from towers.combinador import recomendar
    from towers.data.culturas import carregar_culturas
    from towers.data.taxonomia import CACHE_PADRAO as CACHE_GBIF

    mun = localizar_municipio(e.uf, e.cidade)
    if mun is None:
        raise ValueError("Município não encontrado nos dados do IBGE (rode scripts/preparar_dados.py).")
    pesos, so_financiaveis = pesos_da_entrada(e)
    beneficios = beneficios_da_entrada(e)
    desejada = e.cultura_desejada if e.cultura_desejada not in (None, "Sem preferência", "Outra / Indiferente") else None
    problemas_solo = sorted({PROBLEMA_PARA_SOLO[p] for p in e.problemas if p in PROBLEMA_PARA_SOLO})

    rec = recomendar(
        mun["lat"], mun["lon"], e.data_plantio, cultura_desejada=desejada,
        ultimo=e.ultimo, penultimo=e.penultimo, problemas_solo=problemas_solo,
        pesos=pesos, somente_financiaveis=so_financiaveis, tipos_cultura=e.tipos_cultura or None,
        geocodigo=mun["geocodigo"], universo_piores=pl.col("obrigatoria"), beneficios=beneficios or None,
    )
    cat = {r["id_cultura"]: r for r in carregar_culturas(usar_gbif=CACHE_GBIF.exists())
           .select("id_cultura", "TOPMN", "TOPMX", "ROPMN", "ROPMX").iter_rows(named=True)}

    def conv(df):
        return [_recomendacao_de_linha(r, cat, e, {"desejada": rec.desejada}) for r in df.iter_rows(named=True)]

    obs = []
    if rec.desejada:
        d = rec.desejada
        setor = {"melhores": "entre as recomendadas", "intermediarias": "entre as alternativas razoáveis",
                 "piores": "entre as não recomendadas", "eliminada": "eliminada",
                 "fora_dos_setores": "fora dos destaques"}[d["setor"]]
        obs.append(f"Sua cultura desejada, {d['nome_pt']}, ficou em {d['posicao']}º de {d['total_culturas']} "
                   f"({setor}), nota {100 * d['score_final']:.0f}/100, melhor data {d['plantio']:%d/%m}.")
    t2 = rec.torres.get("t2")
    if t2 is not None and t2.height:
        t = t2.row(0, named=True)
        obs.append(f"Água no solo em {t['data_estado_solo']:%d/%m/%Y}: {_pct(t['agua_solo_hoje'])} da capacidade "
                   f"(NASA POWER); solo {t['classe_ad']} pela textura do SoilGrids.")
    obs.append(f"{rec.ranking.height} culturas avaliadas por clima, água, solo, zoneamento, rotação, extremos climáticos e regras de crédito.")
    # torres fora da nota (timeout/erro) são log de execução, não aviso ao produtor
    for torre, motivo in (getattr(rec, "torres_ausentes", None) or {}).items():
        log.warning("Recomendação %s-%s: torre %s fora da nota (%s)", e.cidade, e.uf, torre, motivo)
    notas = []
    for setor, df in [*rec.setores.items(), ("desejada", rec.ranking.filter(pl.col("desejada")) if "desejada"
                                             in rec.ranking.columns else rec.ranking.clear())]:
        for r in df.iter_rows(named=True):
            if setor == "desejada" and any(n["cultura"] == r["nome_pt"] for n in notas):
                continue
            notas.append({"setor": setor, "id_cultura": r["id_cultura"], "cultura": r["nome_pt"],
                          "plantio": r["plantio"], "ciclo_dias": r.get("ciclo_dias"), "eliminada": r["eliminada"],
                          "nota": r["score_final"], "aptidao_local": r.get("score_agronomico"),
                          "aderencia": r.get("aderencia"), "desejada": bool(r.get("desejada")),
                          **{t: r.get(f"s_{t}") for t in ("t1", "t2", "t3", "t4", "t5", "t7")}})
    detalhes = {"geocodigo": mun["geocodigo"], "notas": notas}
    return Resultado(recomendadas=conv(rec.setores["melhores"]), razoaveis=conv(rec.setores["intermediarias"]),
                     nao_recomendadas=conv(rec.setores["piores"]), fonte="modelo", observacoes=obs,
                     detalhes=detalhes)


MOTORES: dict = {"mock": motor_mock, "modelo": motor_modelo}   # registre novos motores aqui


# ------------------------------------------------------------------ conversão da saída do modelo
def _rec_de_dict(d: dict) -> Recomendacao:
    clima = d.get("clima") or {}
    motivos = d.get("motivos") or []
    if isinstance(motivos, str):
        motivos = [motivos]
    return Recomendacao(
        cultura=str(d.get("cultura", "—")), descricao=str(d.get("descricao", "")),
        motivos=[str(m) for m in motivos],
        clima=Clima(**{k: str(clima.get(k, "—")) for k in ("temperatura", "chuva", "epoca", "adaptacao")}))


def resultado_de_dict(d, fonte: str = "modelo") -> Resultado:
    """Converte o dict/JSON do modelo em `Resultado`. Campos ausentes viram '—'."""
    if isinstance(d, str):
        d = json.loads(d)
    return Resultado(
        recomendadas=[_rec_de_dict(x) for x in d.get("recomendadas", [])],
        razoaveis=[_rec_de_dict(x) for x in d.get("razoaveis", [])],
        nao_recomendadas=[_rec_de_dict(x) for x in d.get("nao_recomendadas", [])],
        fonte=fonte)


def gerar_recomendacoes(e: Entrada, motor: Optional[str] = None) -> Resultado:
    """Único ponto de entrada usado pelo app."""
    nome = motor or os.getenv("MOTOR_RECOMENDACAO", "modelo" if DADOS_REAIS else "mock")
    if nome not in MOTORES:
        raise ValueError(f"Motor desconhecido: {nome}. Disponíveis: {', '.join(MOTORES)}")
    saida = MOTORES[nome](e, coletar_dados_externos(e))
    return resultado_de_dict(saida, fonte=nome) if isinstance(saida, (dict, str)) else saida