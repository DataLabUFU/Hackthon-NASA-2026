"""Pesos das torres por objetivo do produtor (a consequência que ele quer otimizar).

T1 clima (aptidão), T2 água (simulação hídrica), T3 solo, T4 zoneamento oficial (ZARC), T5 rotação.
A T4 tem peso menor em todos os objetivos, exceto "financiamento": o ZARC já embute clima e solo, as mesmas
informações de T1, T2 e T3 (evita contar duas vezes). A T6 (elegibilidade) não entra na média: é filtro/selo.

Valores iniciais, a ajustar com o time (e, quando houver rótulo real, com o combinador aprendido do plano §4.3).
"""
from __future__ import annotations

TORRES = ("t1", "t2", "t3", "t4", "t5")

OBJETIVOS: dict[str, dict] = {
    "equilibrado": {
        "descricao": "Equilíbrio entre clima, água, solo, zoneamento e rotação",
        "pesos": {"t1": 0.25, "t2": 0.25, "t3": 0.20, "t4": 0.15, "t5": 0.15},
    },
    "evitar_seca": {
        "descricao": "Minimizar o risco de perda por falta de água",
        "pesos": {"t1": 0.20, "t2": 0.40, "t3": 0.15, "t4": 0.15, "t5": 0.10},
    },
    "estabilidade": {
        "descricao": "Safra garantida: prioriza os piores anos (P20 da T1 e chance de perda da T2)",
        "pesos": {"t1": 0.30, "t2": 0.30, "t3": 0.15, "t4": 0.15, "t5": 0.10},
        "conservador": True,
    },
    "financiamento": {
        "descricao": "Manter acesso a crédito e seguro: só opções financiáveis, zoneamento com mais peso",
        "pesos": {"t1": 0.20, "t2": 0.20, "t3": 0.15, "t4": 0.35, "t5": 0.10},
        "somente_financiaveis": True,
    },
    "saude_do_solo": {
        "descricao": "Rotação e conservação do solo",
        "pesos": {"t1": 0.15, "t2": 0.15, "t3": 0.30, "t4": 0.10, "t5": 0.30},
    },
}

PISO_SCORE = 0.05        # um score 0 não anula o total (0,05 ^ peso ainda penaliza muito)
