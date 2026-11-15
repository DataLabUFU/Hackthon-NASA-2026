"""Componente 2 da T3: aptidão do solo para cada cultura (requisitos de solo do ECOCROP).

Componentes (1 = ótimo), score = o mais limitante (lei do mínimo, como no modelo Ecocrop):

| componente | regra | corrigível? |
|---|---|---|
| pH | trapézio PHMIN/PHOPMN/PHOPMX/PHMAX | ácido → calagem: piso 0,8 + alerta. Alcalino: sem piso |
| textura | ótima (TEXT) 1,0; tolerada (TEXTR) 0,6; fora 0,5 (penaliza, não elimina). Latossolos/Nitossolos argilosos avaliados como média quando favorece | não |
| drenagem | ótima (DRA) 1,0; tolerada (DRAR) 0,6; fora 0,2 | parcialmente (drenos): alerta |
| profundidade | solo ≥ exigência ótima 1,0; ≥ tolerada 0,6; abaixo 0,2 | não |
| fertilidade | solo ≥ exigência ótima 1,0; abaixo → adubação: piso 0,8 + alerta | sim |
| salinidade | solo ≤ tolerância ótima 1,0; ≤ tolerada 0,6; acima 0,2 | não |
| compactação (produtor) | 0,8 + alerta de descompactação | sim |

Requisito sem dado no ECOCROP ou atributo do solo desconhecido → componente neutro (1,0), sinalizado.
"""
from __future__ import annotations

import polars as pl

PISO_CORRIGIVEL = 0.8
TOLERADO = 0.6
FORA = 0.2
FORA_TEXTURA = 0.5   # textura raramente impede o cultivo (benchmark: café em Argissolo argiloso no PR)

# Requisitos de solo corrigidos para o Brasil (sobrescrevem o ECOCROP), com justificativa.
REQUISITOS_CURADOS = {
    "arroz": {"DRA": "poorly (saturated >50% of year), well (dry spells)",
              "_porque": "o ECOCROP descreve o arroz irrigado por inundação; no Brasil há muito arroz de sequeiro"},
    "acai": {"DRA": "poorly (saturated >50% of year), well (dry spells)",
             "_porque": "o ECOCROP descreve o açaí de várzea; no Pará há muito cultivo em terra firme"},
}
FATOR_COMPACTADO = 0.8

ORDEM_PROFUNDIDADE = {"shallow": 1, "medium": 2, "deep": 3}
ORDEM_FERTILIDADE = {"low": 1, "moderate": 2, "high": 3}
ORDEM_SALINIDADE = {"low": 1, "medium": 2, "high": 3}
CODIGO = {  # rótulos do ECOCROP → código usado no perfil
    "shallow (20-50 cm)": "shallow", "medium (50-150 cm)": "medium", "deep (>>150 cm)": "deep",
    "low (<4 dS/m)": "low", "medium (4-10 dS/m)": "medium", "high (>10 dS/m))": "high",
    "well (dry spells)": "well", "poorly (saturated >50% of year)": "poorly", "excessive (dry/moderately dry)": "excessive",
}


def _codigos(texto: str | None) -> set[str]:
    if not texto:
        return set()
    return {CODIGO.get(t.strip(), t.strip()) for t in texto.split(",")}


def _trapezio(x, amin, omin, omax, amax) -> float:
    if x <= amin or x >= amax:
        return 0.0
    if x < omin:
        return (x - amin) / (omin - amin)
    if x > omax:
        return (amax - x) / (amax - omax)
    return 1.0


def _classe_aceita(valor: str | None, otimo: str | None, tolerado: str | None) -> float | None:
    """1,0 / 0,6 / 0,2 por pertencimento; None se faltar dado."""
    if valor is None or not (otimo or tolerado):
        return None
    ot, tol = _codigos(otimo), _codigos(tolerado)
    if "wide" in ot or valor in ot:
        return 1.0
    if "wide" in tol or valor in tol:
        return TOLERADO
    return FORA


def _ordinal(valor: str | None, otimo: str | None, tolerado: str | None, ordem: dict, maior_melhor: bool) -> float | None:
    """Exigência ordinal: o solo precisa ser ≥ (profundidade, fertilidade) ou ≤ (salinidade) o requisito."""
    if valor is None or not (otimo or tolerado):
        return None
    v = ordem[valor]
    def ok(req: str | None) -> bool | None:
        nivs = [ordem[c] for c in _codigos(req) if c in ordem]
        if not nivs:
            return None
        return v >= min(nivs) if maior_melhor else v <= max(nivs)
    o, t = ok(otimo), ok(tolerado)
    if o:
        return 1.0
    if t:
        return TOLERADO
    return FORA if (o is not None or t is not None) else None


def aptidao_solo(culturas: pl.DataFrame, perfil: dict, piso_corrigivel: float = PISO_CORRIGIVEL,
                 latossolo_como_media: bool = True) -> pl.DataFrame:
    """Uma linha por cultura com os componentes, o score_t3, o fator limitante e os alertas.

    ``piso_corrigivel`` = 0 e ``latossolo_como_media`` = False desligam as regras de manejo brasileiras
    (usado no benchmark para medir o efeito delas).
    """
    linhas = []
    for r in culturas.iter_rows(named=True):
        r = r | {k: v for k, v in REQUISITOS_CURADOS.get(r["id_cultura"], {}).items() if not k.startswith("_")}
        comp, alertas = {}, []

        # pH
        ph = perfil.get("ph")
        if ph is not None and None not in (r["PHMIN"], r["PHOPMN"], r["PHOPMX"], r["PHMAX"]):
            s = _trapezio(ph, r["PHMIN"], r["PHOPMN"], r["PHOPMX"], r["PHMAX"])
            if ph < r["PHOPMN"]:
                alertas.append(f"calagem: pH {ph:.1f} abaixo do ideal ({r['PHOPMN']:.1f}–{r['PHOPMX']:.1f})")
                s = max(s, piso_corrigivel)
            elif ph > r["PHOPMX"] and s < 1:
                alertas.append(f"solo alcalino: pH {ph:.1f} acima do ideal ({r['PHOPMN']:.1f}–{r['PHOPMX']:.1f})")
            comp["ph"] = s
        else:
            comp["ph"] = None

        # textura (Latossolo/Nitossolo argiloso: vale a melhor entre "pesada" e "média")
        tex = perfil.get("textura")
        s = _classe_aceita(tex, r["TEXT"], r["TEXTR"])
        if s is not None and tex == "heavy" and perfil.get("estruturado") and latossolo_como_media:
            s = max(s, _classe_aceita("medium", r["TEXT"], r["TEXTR"]) or s)
        comp["textura"] = max(s, FORA_TEXTURA) if s is not None else None

        # drenagem
        s = _classe_aceita(perfil.get("drenagem"), r["DRA"], r["DRAR"])
        if s is not None and s < 1:
            alertas.append("drenagem inadequada para a cultura" + (" (avaliar drenos)" if perfil.get("drenagem") == "poorly" else ""))
        comp["drenagem"] = s

        # profundidade, salinidade
        comp["profundidade"] = _ordinal(perfil.get("profundidade"), r["DEP"], r["DEPR"], ORDEM_PROFUNDIDADE, True)
        comp["salinidade"] = _ordinal(perfil.get("salinidade"), r["SAL"], r["SALR"], ORDEM_SALINIDADE, False)

        # fertilidade (corrigível)
        s = _ordinal(perfil.get("fertilidade"), r["FER"], r["FERR"], ORDEM_FERTILIDADE, True)
        if s is not None and s < 1:
            alertas.append("adubação: fertilidade natural abaixo da exigência da cultura")
            s = max(s, piso_corrigivel)
        comp["fertilidade"] = s

        # compactação (informada pelo produtor)
        if perfil.get("compactado"):
            comp["compactacao"] = FATOR_COMPACTADO
            alertas.append("solo compactado: descompactação/subsolagem e plantas de cobertura")

        validos = {k: v for k, v in comp.items() if v is not None}
        score = min(validos.values()) if validos else 1.0
        limitante = min(validos, key=validos.get) if validos and score < 1 else None
        linhas.append({
            "id_cultura": r["id_cultura"],
            "score_t3": score,
            "fator_limitante_solo": limitante,
            # o fator limitante se resolve com manejo (calagem, adubação, descompactação)?
            "corrigivel": limitante in (None, "fertilidade", "compactacao") or (
                limitante == "ph" and ph is not None and ph < r["PHOPMN"]),
            "alertas_solo": alertas,
            **{f"s_{k}": comp.get(k) for k in ("ph", "textura", "drenagem", "profundidade", "fertilidade", "salinidade")},
            "requisitos_sem_dado": [k for k, v in comp.items() if v is None],
        })
    return pl.DataFrame(linhas, schema_overrides={f"s_{k}": pl.Float64 for k in
                                                  ("ph", "textura", "drenagem", "profundidade", "fertilidade", "salinidade")})
