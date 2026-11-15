"""Aderência ao produtor: quanto cada cultura entrega o que ele quer ganhar ou resolver.

As torres T1–T6 medem se a cultura *vai bem* no local e na data. Aqui se mede se ela *serve ao produtor*:
os objetivos marcados (ex.: aumentar nitrogênio) e os problemas da área que ele quer resolver (ex.: compactação).

    aderencia = Σ peso(benefício) × atende(cultura, benefício) / Σ peso        ∈ [0, 1]
    nota final = nota agronômica × (1 − PESO_ADERENCIA × (1 − aderencia))

Com PESO_ADERENCIA = 0,4, a cultura que não atende a nenhum pedido perde 40% da nota, e a que atende a todos
não perde nada. Sem nenhum objetivo ou problema marcado, o fator é 1 (não muda nada).

A cultura desejada recebe um bônus: nota + BONUS_DESEJADA × (1 − nota), sem passar de 1 e só se ela não foi
eliminada (clima inapto ou fora do crédito, quando ele é exigido).

Os valores de ``atende`` (0 a 1) seguem as recomendações gerais da Embrapa para plantas de cobertura e adubação
verde (ex.: Embrapa Cerrados, "Plantas de cobertura do solo"; Embrapa Agrobiologia, "Adubação verde"):
leguminosas fixam nitrogênio; gramíneas e adubos verdes de alta biomassa formam palhada (matéria orgânica,
infiltração e retenção de água, proteção contra erosão e supressão de plantas daninhas); raízes pivotantes ou
abundantes rompem camadas compactadas; crotalárias e mucunas reduzem nematoides; e trocar de família botânica
quebra o ciclo de pragas e doenças. **Primeira parametrização, a revisar com um agrônomo.**
"""
from __future__ import annotations

import polars as pl

from towers.t5_rotacao.torre import familia

PESO_ADERENCIA = 0.4
BONUS_DESEJADA = 0.3
LIMIAR_ATENDE, LIMIAR_PARCIAL = 0.7, 0.3

BENEFICIOS = {
    "fixar_nitrogenio": "fixa nitrogênio no solo",
    "descompactar": "raízes que rompem a compactação",
    "materia_organica": "aumenta a matéria orgânica (muita palhada)",
    "estrutura_solo": "melhora a estrutura do solo",
    "reter_agua": "palhada que ajuda a reter água",
    "controlar_erosao": "protege o solo contra erosão",
    "controlar_pragas": "ajuda a reduzir pragas e nematoides",
    "controlar_doencas": "quebra o ciclo de doenças",
    "controlar_daninhas": "abafa plantas daninhas",
}

ADUBOS_VERDES = {"crotalaria", "crotalaria-spectabilis", "mucuna-preta", "feijao-de-porco", "feijao-guandu",
                 "feijao-espada", "tremoco", "tremoco-amarelo", "tremoco-azul", "ervilhaca", "ervilhaca-de-narbona",
                 "estilosantes"}
COBERTURAS_GRAMINEAS = {"milheto", "aveia-preta", "centeio", "braquiaria-ruziziensis", "braquiaria-brizanta",
                        "braquiaria-decumbens", "braquiaria", "sorgo-forrageiro", "capim-do-sudao"}
RAIZES_AGRESSIVAS = {"nabo-forrageiro", "feijao-guandu", "crotalaria", "crotalaria-spectabilis", "milheto",
                     "braquiaria-ruziziensis", "braquiaria-brizanta", "braquiaria-decumbens"}
ALTA_BIOMASSA = COBERTURAS_GRAMINEAS | {"crotalaria", "crotalaria-spectabilis", "mucuna-preta", "feijao-de-porco",
                                        "feijao-guandu", "milho", "sorgo-granifero", "capim-elefante",
                                        "capim-coloniao-mombaca", "nabo-forrageiro"}
SUPRESSORAS_NEMATOIDES = {"crotalaria": 1.0, "crotalaria-spectabilis": 1.0, "mucuna-preta": 1.0,
                          "milheto": 0.5, "aveia-preta": 0.5, "nabo-forrageiro": 0.5}
SUPRESSORAS_DANINHAS = COBERTURAS_GRAMINEAS | {"crotalaria", "crotalaria-spectabilis", "mucuna-preta",
                                               "feijao-de-porco"}


def _atende(c: dict, fam_hist: list[str | None]) -> dict[str, float]:
    """Quanto a cultura ``c`` (linha do catálogo) entrega cada benefício (0 a 1)."""
    id_c, fam = c["id_cultura"], familia(c.get("familia"))
    poacea, fabacea = fam == "Poaceae", fam == "Fabaceae"
    perene_forrageira = c.get("tipo_cultura") == "forrageiras" and c.get("modo") == "implantacao"
    if id_c in ALTA_BIOMASSA or (perene_forrageira and poacea):
        mo = 1.0
    elif poacea:
        mo = 0.5
    elif fabacea:
        mo = 0.3          # palhada de leguminosa de grão: pouca e decompõe rápido
    else:
        mo = 0.0
    descomp = 1.0 if id_c in RAIZES_AGRESSIVAS else 0.5 if (poacea or id_c in ADUBOS_VERDES) else 0.0
    erosao = max(mo, 1.0 if perene_forrageira else 0.0, 0.7 if c.get("uso") == "silvicultura" else 0.0,
                 0.5 if c.get("tipo_cultura") == "industriais_perenes" else 0.0)

    ultima, penultima = (fam_hist + [None, None])[:2]
    if ultima is None:
        quebra = 0.5      # sem histórico: não dá para saber se quebra o ciclo
    elif fam == ultima:
        quebra = 0.0
    else:
        quebra = 1.0 if fam != penultima else 0.6

    return {
        "fixar_nitrogenio": 1.0 if id_c in ADUBOS_VERDES else 0.7 if fabacea else 0.0,
        "descompactar": descomp,
        "materia_organica": mo,
        "estrutura_solo": (descomp + mo) / 2,
        "reter_agua": mo,
        "controlar_erosao": erosao,
        "controlar_pragas": max(SUPRESSORAS_NEMATOIDES.get(id_c, 0.0), 0.5 * quebra),
        "controlar_doencas": quebra,
        "controlar_daninhas": 1.0 if id_c in SUPRESSORAS_DANINHAS else 0.5 if poacea else 0.0,
    }


def aderencia(culturas: pl.DataFrame, pedidos: dict[str, float], historico: list[dict | None] = ()) -> pl.DataFrame:
    """(id_cultura, aderencia, beneficios_atendidos, beneficios_parciais, beneficios_nao_atendidos).

    ``pedidos``: {benefício: peso}. Listas com os códigos de ``BENEFICIOS`` (atende ≥ 0,7; 0,3 a 0,7; < 0,3),
    para o front explicar a nota com as palavras do produtor.

    ``historico``: [última, penúltima] safra (linhas do catálogo ou None), para pragas e doenças.
    """
    if invalidos := set(pedidos) - set(BENEFICIOS):
        raise ValueError(f"benefícios desconhecidos: {sorted(invalidos)} (válidos: {sorted(BENEFICIOS)})")
    fam_hist = [familia(h.get("familia")) if h and h.get("id_cultura") != "pousio" else None
                for h in list(historico)[:2]]
    total = sum(pedidos.values())
    linhas = []
    for c in culturas.iter_rows(named=True):
        a = _atende(c, fam_hist)
        nota = sum(p * a[b] for b, p in pedidos.items()) / total if total else None
        linhas.append({"id_cultura": c["id_cultura"], "aderencia": nota,
                       "beneficios_atendidos": [b for b in pedidos if a[b] >= LIMIAR_ATENDE],
                       "beneficios_parciais": [b for b in pedidos if LIMIAR_PARCIAL <= a[b] < LIMIAR_ATENDE],
                       "beneficios_nao_atendidos": [b for b in pedidos if a[b] < LIMIAR_PARCIAL]})
    lista = pl.List(pl.String)
    return pl.DataFrame(linhas, schema={"id_cultura": pl.String, "aderencia": pl.Float64,
                                        "beneficios_atendidos": lista, "beneficios_parciais": lista,
                                        "beneficios_nao_atendidos": lista})
