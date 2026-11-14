"""Regras de elegibilidade a crédito rural e seguro (T6), com vigência e fonte.

AVISO: resumo para orientar o produto, não é aconselhamento jurídico/financeiro. Prevalece o texto
vigente do Manual de Crédito Rural (MCR/BCB), que muda a cada Plano Safra. Reconferir antes de cada
entrega: https://www3.bcb.gov.br/mcr
"""
from __future__ import annotations

VIGENCIA = "Plano Safra 2025/2026 (conferido em nov/2026)"

FONTES = {
    "zarc_custeio": "MCR: concessão de crédito de custeio agrícola subordinada ao ZARC; a partir da safra 2025/26 "
                    "também para valores maiores e contratos sem Proagro (MAPA, Plano Safra 2025/26; Res. CMN 5.229/2025)",
    "sem_zarc": "MCR: em localidades não abrangidas pelo ZARC admite-se outro zoneamento (ex.: ZEE)",
    "proagro": "Proagro exige observância do ZARC (MCR cap. 12); Res. CMN 5.224/2025: enquadramento obrigatório "
               "no Proagro do custeio até R$ 200 mil em lavouras zoneadas",
    "psr": "Subvenção ao Prêmio do Seguro Rural (PSR) usa o ZARC como requisito",
    "car": "MCR 2-9: não se concede crédito a imóvel sem CAR ou com CAR cancelado/suspenso",
    "terra_indigena": "MCR 2-9: vedado crédito a imóvel em terra indígena (com ressalvas do texto)",
    "embargo": "Res. CMN 5.193/2024: crédito a imóvel embargado admitido até meados de 2027 se o CAR estiver "
               "ativo e em análise (fontes divergem entre 30/06/2027 e jul/2027)",
    "uc": "MCR 2-9 / Res. CMN 5.267/2025: instituições devem verificar sobreposição com unidades de conservação",
    "investimento": "Implantação de culturas perenes/florestas é crédito de investimento, com regras próprias",
    "rnc": "Portarias do ZARC indicam cultivares registradas no RNC; usar cultivar registrada e indicada é "
           "condição frequente para Proagro e seguro",
}

AVISO_GERAL = ("Indicação orientativa: confirme as condições com sua instituição financeira. "
               "Regras conforme " + VIGENCIA + ".")
AVISO_RNC = "Use cultivar registrada no RNC e indicada na portaria do ZARC para o seu município."
AVISO_SOCIOAMBIENTAL = ("Situação do CAR, embargos (IBAMA), terra indígena e unidades de conservação não "
                        "verificadas: informe-as ou consulte o SICAR/IBAMA.")

SITUACOES_CAR = {"ativo", "pendente", "cancelado", "suspenso", "inexistente"}
