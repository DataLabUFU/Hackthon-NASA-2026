"""Camada de dados e decisão do AgroData.

Este é o ÚNICO arquivo que liga a interface ao modelo. A interface (app_teste.py) só lê o `Resultado`.
O modelo real (`motor_modelo`) usa o recomendador de seis torres em `towers/` (towers.combinador.recomendar);
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
PESO_PROBLEMA = 0.5   # um problema relatado pesa metade de um objetivo explícito


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


def _pct(x) -> str:
    return "—" if x is None else f"{100 * x:.0f}%"


def _recomendacao_de_linha(r: dict, cat: dict) -> Recomendacao:
    """Uma linha do ranking do recomendador -> card do front."""
    c = cat.get(r["id_cultura"], {})
    ciclo = r.get("ciclo_dias")
    tipo = TIPOS_CULTURA.get(r.get("tipo_cultura") or "", "")
    eleg = {"elegivel": "Elegível a crédito de custeio, Proagro e seguro.",
            "condicional": "Crédito condicionado à regularização do imóvel.",
            "inelegivel": "Fora das regras de crédito/seguro nesta data.",
            "a_verificar": "Elegibilidade a crédito: a verificar."}.get(r.get("status_elegibilidade") or "", "")
    descricao = (f"Plantio sugerido em {r['plantio']:%d/%m/%Y}" + (f" (ciclo de ~{ciclo} dias)" if ciclo else "")
                 + f". Nota {100 * r['score_final']:.0f}/100" + (f" · {tipo}" if tipo else "") + f". {eleg}")

    m = []
    if r.get("eliminada"):
        m.append(f"Não indicada: {r.get('motivo_eliminacao')}.")
    s1, s2, s3 = r.get("s_t1"), r.get("s_t2"), r.get("s_t3")
    if s1 is not None:
        m.append(f"Clima favorável na época (aptidão {_pct(s1)})." if s1 >= 0.8
                 else f"Clima limitante: {r.get('fator_limitante')} (aptidão {_pct(s1)}).")
    if s2 is not None:
        falta = r.get("irrigacao_mm") or 0
        m.append("Baixo risco de falta d'água no ciclo." if s2 >= 0.85
                 else f"Risco hídrico: faltam em média {falta:.0f} mm no ciclo (nota de água {_pct(s2)}).")
    if s3 is not None and s3 < 0.6 and r.get("fator_limitante_solo"):
        m.append(f"Solo pouco adequado: {r['fator_limitante_solo']}.")
    for alerta in (r.get("alertas_solo") or [])[:2]:
        m.append(alerta[:1].upper() + alerta[1:] + ".")
    z = r.get("zarc_status")
    if z == "indicado":
        m.append(f"Indicada pelo zoneamento oficial (ZARC), risco de {r.get('risco_zarc_pct')}%.")
    elif z == "nao_indicado":
        m.append("Fora da janela do zoneamento oficial (ZARC) nesta data.")
    for exp in (r.get("explicacao_rotacao") or []):
        m.append("Rotação: " + exp.split(":")[0] + ".")
    if r.get("status_elegibilidade") == "elegivel" and r.get("portaria_zarc"):
        m.append(f"Crédito e seguro: dentro do ZARC ({r['portaria_zarc'].replace('_', ' ')}).")
    if r.get("alerta_foto_mensagem"):
        m.append(r["alerta_foto_mensagem"])
    if r.get("alerta_ciclo_extremo"):
        m.append("Exige cultivar de ciclo muito precoce ou tardio para esta data.")

    outras = [d.strftime("%d/%m") for d in (r.get("outras_datas_boas") or []) if d != r["plantio"]]
    clima = Clima(
        temperatura=f"{c['TOPMN']:.0f}°C a {c['TOPMX']:.0f}°C (faixa ótima)" if c.get("TOPMN") is not None else "—",
        chuva=f"{c['ROPMN']:.0f} a {c['ROPMX']:.0f} mm (faixa ótima)" if c.get("ROPMN") is not None else "—",
        epoca=f"{r['plantio']:%d/%m}" + (f"; também bom: {', '.join(outras[:3])}" if outras else ""),
        adaptacao=(f"Apta em {_pct(r['prob_apta'])} dos anos (NASA POWER)" if r.get("prob_apta") is not None else "—"),
    )
    return Recomendacao(r["nome_pt"], descricao, m, clima)


def motor_modelo(e: Entrada, dados: dict) -> Resultado:
    """Recomendador real: as seis torres (towers/) combinadas e ordenadas em três setores."""
    import polars as pl
    from towers.combinador import recomendar
    from towers.data.culturas import carregar_culturas
    from towers.data.taxonomia import CACHE_PADRAO as CACHE_GBIF

    mun = localizar_municipio(e.uf, e.cidade)
    if mun is None:
        raise ValueError("Município não encontrado nos dados do IBGE (rode scripts/preparar_dados.py).")
    pesos, so_financiaveis = pesos_da_entrada(e)
    desejada = e.cultura_desejada if e.cultura_desejada not in (None, "Sem preferência", "Outra / Indiferente") else None
    problemas_solo = sorted({PROBLEMA_PARA_SOLO[p] for p in e.problemas if p in PROBLEMA_PARA_SOLO})

    rec = recomendar(
        mun["lat"], mun["lon"], e.data_plantio, cultura_desejada=desejada,
        ultimo=e.ultimo, penultimo=e.penultimo, problemas_solo=problemas_solo,
        pesos=pesos, somente_financiaveis=so_financiaveis, tipos_cultura=e.tipos_cultura or None,
        geocodigo=mun["geocodigo"], universo_piores=pl.col("obrigatoria"),
    )
    cat = {r["id_cultura"]: r for r in carregar_culturas(usar_gbif=CACHE_GBIF.exists())
           .select("id_cultura", "TOPMN", "TOPMX", "ROPMN", "ROPMX").iter_rows(named=True)}

    def conv(df):
        return [_recomendacao_de_linha(r, cat) for r in df.iter_rows(named=True)]

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
    obs.append(f"{rec.ranking.height} culturas avaliadas por clima, água, solo, zoneamento, rotação e regras de crédito.")
    # torres fora da nota (timeout/erro) são log de execução, não aviso ao produtor
    for torre, motivo in (getattr(rec, "torres_ausentes", None) or {}).items():
        log.warning("Recomendação %s-%s: torre %s fora da nota (%s)", e.cidade, e.uf, torre, motivo)
    return Resultado(recomendadas=conv(rec.setores["melhores"]), razoaveis=conv(rec.setores["intermediarias"]),
                     nao_recomendadas=conv(rec.setores["piores"]), fonte="modelo", observacoes=obs)


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