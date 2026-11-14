"""Camada de dados e decisão do AgroData.

Este é o ÚNICO arquivo que muda quando o modelo real chegar. A interface (app.py) só lê o `Resultado`.

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
import os
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Callable, Optional

# ------------------------------------------------------------------ listas do formulário
CULTURAS_HISTORICO = ["Soja", "Milho", "Trigo", "Algodão", "Feijão", "Sorgo", "Girassol", "Milheto", "Pastagem"]
CULTURAS_DESEJADAS = ["Sem preferência", "Soja", "Milho", "Trigo", "Algodão", "Feijão", "Sorgo",
                      "Girassol", "Milheto", "Outra / Indiferente"]

# UF -> (nome, cidades). Amostra de teste; para todas as cidades, use a API de localidades do IBGE.
ESTADOS = {
    "MG": ("Minas Gerais", ["Uberlândia", "Uberaba", "Araguari", "Patos de Minas"]),
    "GO": ("Goiás", ["Goiânia", "Rio Verde", "Jataí"]),
    "SP": ("São Paulo", ["Ribeirão Preto", "Campinas", "São Paulo"]),
    "MT": ("Mato Grosso", ["Cuiabá", "Rondonópolis", "Sorriso"]),
    "MS": ("Mato Grosso do Sul", ["Campo Grande", "Dourados", "Três Lagoas"]),
}

# valor (enviado ao modelo)  ->  rótulo (mostrado ao produtor)
PROBLEMAS = {v: v for v in [
    "Compactação do solo", "Baixa retenção de água", "Deficiência de nitrogênio", "Presença de pragas",
    "Incidência de doenças", "Baixo teor de matéria orgânica", "Erosão do solo", "Plantas daninhas"]}
OBJETIVOS = {
    "Reduzir compactação": "Reduzir compactação", "Reter água": "Melhorar retenção de água",
    "Aumentar nitrogênio": "Aumentar nitrogênio", "Controlar pragas": "Controlar pragas",
    "Controlar doenças": "Reduzir doenças", "Aumentar matéria orgânica": "Aumentar matéria orgânica",
    "Melhorar estrutura do solo": "Melhorar estrutura do solo", "Reduzir erosão": "Reduzir erosão",
    "Aumentar produtividade": "Aumentar produtividade",
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


def obter_estatisticas(e: Entrada) -> dict:
    """Dados da tela de estatísticas (hoje fictícios)."""
    clima = obter_clima(e)
    meses = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
    return {"meses": [f"{i + 1:02d} {m}" for i, m in enumerate(meses)],   # prefixo numérico mantém a ordem no gráfico
            "chuva_mm": clima["chuva_mm_mensal"], "temp_c": clima["temp_media_c"],
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


def motor_modelo(e: Entrada, dados: dict):
    """PONTO DE PLUG-IN DO MODELO.

    Recebe `e` (Entrada; use e.para_dict() para serializar) e `dados` (clima, solo, mercado).
    Devolva um `Resultado` ou um dict/JSON no formato descrito no topo deste arquivo.
    """
    raise NotImplementedError("Modelo ainda não conectado: implemente motor_modelo em motor.py")


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
    nome = motor or os.getenv("MOTOR_RECOMENDACAO", "mock")
    if nome not in MOTORES:
        raise ValueError(f"Motor desconhecido: {nome}. Disponíveis: {', '.join(MOTORES)}")
    saida = MOTORES[nome](e, coletar_dados_externos(e))
    return resultado_de_dict(saida, fonte=nome) if isinstance(saida, (dict, str)) else saida