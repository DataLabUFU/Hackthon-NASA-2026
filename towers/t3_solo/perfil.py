"""Componente 1 da T3: perfil do solo do local, nas mesmas classes que o ECOCROP usa.

Fontes, da mais confiável para a menos:
1. análise de solo informada pelo produtor (pH, argila, CTC);
2. problemas informados pelo produtor (ácido, arenoso, argiloso, encharcado, compactado, raso, salino,
   pouco fértil);
3. SoilGrids 2.0 (pH, textura, CTC e classe WRB, 250 m).

Classes derivadas:
- textura (ECOCROP: light / medium / heavy), pelo grupamento textural do SiBCS (Embrapa):
  arenosa = argila < 15% e areia ≥ 70%; argilosa = argila ≥ 35%; média = o restante;
- fertilidade (low / moderate / high) pela CTC a pH 7, faixas da 5ª Aproximação (CFSEMG, 1999):
  ≤ 4,30 baixa; 4,31–8,60 média; > 8,60 alta (cmol(c)/dm³ ≈ cmol(c)/kg);
- drenagem, profundidade e salinidade pela classe WRB (SoilGrids não mapeia esses atributos):
  só se a classe tiver probabilidade ≥ 30%; Gleysols/Stagnosols/Planosols/Histosols → mal drenado; Arenosols → excessivamente drenado;
  Leptosols → raso; Ferralsols/Arenosols → profundo; Solonchaks → salino; Solonetz → salinidade média.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

from towers.data import soilgrids

log = logging.getLogger(__name__)

PROBLEMAS_VALIDOS = {"acido", "arenoso", "argiloso", "encharcado", "compactado", "raso", "salino", "pouco_fertil"}
PH_SE_ACIDO = 5.0

# Fluvisols NÃO entram: no semiárido os Neossolos Flúvicos são aluviais bem drenados (benchmark contra a PAM)
WRB_MAL_DRENADOS = {"Gleysols", "Stagnosols", "Planosols", "Histosols"}
PROB_MIN_WRB = 30   # % mínima da classe WRB para inferir drenagem, profundidade e salinidade
WRB_EXCESSIVOS = {"Arenosols"}
WRB_RASOS = {"Leptosols"}
WRB_PROFUNDOS = {"Ferralsols", "Arenosols"}
WRB_ESTRUTURADOS = {"Ferralsols", "Nitisols"}   # argilosos bem agregados: drenam como textura média
WRB_SALINIDADE = {"Solonchaks": "high", "Solonetz": "medium"}


def classe_textural(areia: float, argila: float) -> str:
    if argila < 15 and areia >= 70:
        return "light"
    if argila >= 35:
        return "heavy"
    return "medium"


def classe_fertilidade(ctc: float) -> str:
    return "low" if ctc <= 4.30 else ("moderate" if ctc <= 8.60 else "high")


def perfil_solo(lat: float, lon: float, problemas: tuple[str, ...] | list[str] = (), analise: dict | None = None,
                fontes: dict | None = None) -> dict:
    """Perfil do solo com a origem de cada atributo.

    ``analise``: {"ph": float, "argila": %, "areia": %, "ctc": cmol(c)/kg} da análise de solo (opcional).
    ``fontes``: injeta {"textura", "quimica", "classe"} (testes); por padrão consulta o SoilGrids.
    """
    problemas = set(problemas)
    if invalidos := problemas - PROBLEMAS_VALIDOS:
        raise ValueError(f"problemas de solo desconhecidos: {sorted(invalidos)} (válidos: {sorted(PROBLEMAS_VALIDOS)})")
    analise = analise or {}
    fontes = dict(fontes or {})
    faltam = {nome: f for nome, f in (("textura", soilgrids.textura), ("quimica", soilgrids.quimica),
                                      ("classe", soilgrids.classe_wrb)) if nome not in fontes}
    if faltam:
        # as três consultas ao SoilGrids em paralelo: o tempo fica o da mais lenta, não a soma
        with ThreadPoolExecutor(max_workers=len(faltam), thread_name_prefix="soilgrids") as ex:
            futuros = {nome: ex.submit(f, lat, lon) for nome, f in faltam.items()}
        for nome, fut in futuros.items():
            try:
                fontes[nome] = fut.result()
            except Exception as e:  # rede/API: segue com o que houver, sinalizado
                log.warning("T3: SoilGrids (%s) indisponível: %s", nome, e)
                fontes[nome] = None
    tex, qui, cls = fontes.get("textura"), fontes.get("quimica"), fontes.get("classe")
    origem: dict[str, str] = {}
    p: dict = {"wrb": cls["wrb"] if cls else None, "wrb_probabilidades": cls.get("wrb_probabilidades") if cls else None}

    # pH
    if "ph" in analise:
        p["ph"], origem["ph"] = analise["ph"], "analise"
    elif qui:
        p["ph"], origem["ph"] = qui["ph"], "soilgrids"
    else:
        p["ph"], origem["ph"] = None, "sem_dado"
    if "acido" in problemas and "ph" not in analise:
        p["ph"] = min(p["ph"], PH_SE_ACIDO) if p["ph"] is not None else PH_SE_ACIDO
        origem["ph"] = "produtor (ácido)"

    # textura
    areia = analise.get("areia", tex["areia"] if tex else None)
    argila = analise.get("argila", tex["argila"] if tex else None)
    if "arenoso" in problemas:
        p["textura"], origem["textura"] = "light", "produtor (arenoso)"
    elif "argiloso" in problemas:
        p["textura"], origem["textura"] = "heavy", "produtor (argiloso)"
    elif argila is not None and areia is not None:
        p["textura"] = classe_textural(areia, argila)
        origem["textura"] = "analise" if "argila" in analise else "soilgrids"
    else:
        p["textura"], origem["textura"] = None, "sem_dado"
    p["argila"], p["areia"] = argila, areia
    p["estruturado"] = p["wrb"] in WRB_ESTRUTURADOS and "argiloso" not in problemas

    # fertilidade
    ctc = analise.get("ctc", qui["ctc"] if qui else None)
    if "pouco_fertil" in problemas:
        p["fertilidade"], origem["fertilidade"] = "low", "produtor (pouco fértil)"
    elif ctc is not None:
        p["fertilidade"], origem["fertilidade"] = classe_fertilidade(ctc), "analise" if "ctc" in analise else "soilgrids"
    else:
        p["fertilidade"], origem["fertilidade"] = None, "sem_dado"
    p["ctc"] = ctc

    # drenagem, profundidade e salinidade (classe WRB confiável, ou o produtor)
    prob_wrb = (cls.get("wrb_probabilidades") or [[None, 100]])[0][1] if cls else 0
    p["wrb_probabilidade"] = prob_wrb
    wrb = p["wrb"] if prob_wrb >= PROB_MIN_WRB else None
    if "encharcado" in problemas:
        p["drenagem"], origem["drenagem"] = "poorly", "produtor (encharcado)"
    else:
        p["drenagem"] = "poorly" if wrb in WRB_MAL_DRENADOS else ("excessive" if wrb in WRB_EXCESSIVOS else "well")
        origem["drenagem"] = "soilgrids (WRB)" if wrb else "padrao"
    if "raso" in problemas:
        p["profundidade"], origem["profundidade"] = "shallow", "produtor (raso)"
    else:
        p["profundidade"] = "shallow" if wrb in WRB_RASOS else ("deep" if wrb in WRB_PROFUNDOS else "medium")
        origem["profundidade"] = "soilgrids (WRB)" if wrb else "padrao"
    if "salino" in problemas:
        p["salinidade"], origem["salinidade"] = "medium", "produtor (salino)"
    else:
        p["salinidade"] = WRB_SALINIDADE.get(wrb, "low")
        origem["salinidade"] = "soilgrids (WRB)" if wrb else "padrao"

    p["compactado"] = "compactado" in problemas
    p["origem"] = origem
    return p
