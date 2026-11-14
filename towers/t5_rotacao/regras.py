"""Regras de rotação de culturas da T5 (v0).

Cada regra é um ajuste somado a uma base neutra; o score fica limitado a [0, 1].
Os valores são uma primeira parametrização, coerente com as recomendações gerais de rotação dos
sistemas de produção da Embrapa (diversificar famílias, alternar gramíneas e leguminosas, usar plantas
de cobertura, evitar sucessão de hospedeiros comuns). **Devem ser revisados com um agrônomo/Embrapa**
antes de uso em produção.
"""
from __future__ import annotations

BASE = 0.75   # cultura com histórico informado, sem nenhuma interação positiva ou negativa

# (código, ajuste, descrição exibida ao produtor, base agronômica)
REGRAS = {
    "monocultura":        (-0.25, "Mesma cultura da safra anterior",
                           "acúmulo de pragas, doenças e plantas daninhas específicas"),
    "monocultura_2":      (-0.20, "Mesma cultura nas duas últimas safras",
                           "monocultura contínua agrava o acúmulo de inóculo"),
    "mesma_familia":      (-0.10, "Mesma família botânica da safra anterior",
                           "famílias próximas compartilham pragas e doenças"),
    "mesma_familia_2":    (-0.05, "Mesma família botânica da penúltima safra", "idem, efeito menor"),
    "leguminosa_graminea": (+0.15, "Gramínea após leguminosa",
                            "nitrogênio residual da fixação biológica favorece a gramínea"),
    "leguminosa_outra":   (+0.05, "Após leguminosa", "nitrogênio residual"),
    "apos_graminea":      (+0.10, "Após gramínea (palhada)",
                           "palhada para plantio direto e quebra do ciclo de doenças de folhas largas"),
    "cobertura":          (+0.10, "Após planta de cobertura",
                           "melhora estrutura, matéria orgânica e ciclagem de nutrientes"),
    "mofo_branco":        (-0.10, "Sucessão de hospedeiros do mofo-branco",
                           "Sclerotinia sclerotiorum sobrevive no solo e ataca as duas culturas"),
    "pousio":             (+0.05, "Após pousio", "quebra parcial do ciclo de pragas e doenças"),
}

# Nomes botânicos antigos (ECOCROP) → atuais (APG)
FAMILIA_ATUAL = {
    "Leguminosae": "Fabaceae", "Papilionaceae": "Fabaceae", "Mimosaceae": "Fabaceae", "Caesalpiniaceae": "Fabaceae",
    "Gramineae": "Poaceae", "Cruciferae": "Brassicaceae", "Compositae": "Asteraceae", "Umbelliferae": "Apiaceae",
    "Labiatae": "Lamiaceae", "Palmae": "Arecaceae", "Guttiferae": "Clusiaceae", "Chenopodiaceae": "Amaranthaceae",
}

# Plantas de cobertura (pelo id_cultura do catálogo)
COBERTURAS = {
    "aveia-preta", "crotalaria", "crotalaria-spectabilis", "mucuna-preta", "feijao-de-porco", "nabo-forrageiro",
    "milheto", "braquiaria-brizanta", "braquiaria-decumbens", "braquiaria-ruziziensis", "ervilhaca", "tremoco",
    "estilosantes", "feijao-guandu",
}

# Hospedeiros importantes do mofo-branco (Sclerotinia sclerotiorum)
HOSPEDEIROS_MOFO_BRANCO = {"soja", "feijao", "girassol", "canola", "ervilha", "tomate", "batata", "alface", "vagem"}

POUSIO = {"pousio", "nenhum", "sem cultivo"}
