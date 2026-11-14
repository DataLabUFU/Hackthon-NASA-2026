# Torre 7: probabilidade de extremos climáticos

Estima a chance de, numa safra (ou fase) qualquer, acontecer pelo menos um evento climático
forte. Os eventos são:

- **chuva extrema**: chuva somada em 3 dias acima de 80 mm;
- **queda brusca**: a temperatura média cai 5 °C ou mais em 2 dias;
- **algum**: pelo menos um dos dois no mesmo ano.

Também traz um **indicador de estiagem** (amplitude térmica acima do normal), só informativo.

## Como é calculado

Para cada ano de 2000 a 2021, vemos se o evento aconteceu no período (fase do ciclo, decêndio
ou safra). A probabilidade é a fração de anos com evento. O intervalo de confiança vem de
sortear os anos com reposição 1.000 vezes (bootstrap de anos).

Na linguagem de valores extremos: cada ano é um bloco, a medida (chuva em 3 dias, queda em
2 dias) tem um máximo no bloco `M`, e o limiar faz o papel do nível `z`. A probabilidade é
`p = Pr(M > z)`, estimada pela fração de blocos em que o máximo passou do nível. (Não é o
limiar `u` do POT/GPD.)

O período de retorno é `T = 1/p`. Ex.: p = 0,24 → T ≈ 4 safras. É o tempo **médio** de espera,
não um intervalo fixo: o evento pode acontecer dois anos seguidos ou ficar dez anos sem ocorrer.
E isso só vale se os anos forem independentes e `p` for constante no tempo (ver Limitações).

Não ajustamos GEV/GPD. Elas servem para extrapolar além do que já foi observado, e aqui os
limiares foram escolhidos para o evento acontecer com frequência. Com blocos curtos (um
decêndio tem 10 dias) e só 22 anos, a aproximação da GEV fica ruim e instável. Aqui só
contamos o que aconteceu.

## Dados

`dados_unificados.csv` (NASA POWER, MERRA-2): 20 pontos (P01–P20), diário, 2000–2022.
Fica em `data/raw/power/` (fora do git). Só os anos até 2021 entram na referência: 2022 em
diante fica para o ML testar.

## Como usar

```bash
python -m scripts.t7_tabela_referencia   # tabelas dos 20 pontos
python -m scripts.t7_sensibilidade       # sensibilidade dos limiares
python -m scripts.t7_validacao           # tendência e janelas de referência
python -m pytest tests/test_t7_extremos.py
```

As tabelas saem em `artifacts/t7/` (fora do git), com um `metadata.json` (limiares, hash do
CSV e versões).

Consulta para um ponto, uma data de plantio e as fases do ciclo:

```python
from datetime import date
from towers.t7_extremos.consulta import preparar_base, consultar

base = preparar_base()
fases = [
    {"nome": "plantio",  "inicio": 0,   "fim": 20,  "eventos": ["chuva_extrema", "queda_brusca"]},
    {"nome": "colheita", "inicio": 110, "fim": 130, "eventos": ["chuva_extrema"]},
]
r = consultar(base, "P06", date(2026, 10, 20), fases)
```

`inicio` e `fim` são dias depois do plantio. A saída traz `p_chuva_extrema`, `p_oscilacao` e
`p_algum` (cada um com IC e número de anos), `enso`, `indicador_estiagem` e os limiares usados.

## Limiares

Ficam em `configs/extremos.yaml`. Os de hoje são **PROVISÓRIOS**: foram escolhidos para a
probabilidade não ficar perto de 0 nem de 1 nos 20 pontos (safra out–mar). É um critério
estatístico; o valor que causa dano à lavoura ainda precisa vir do agro.

## Para o time de ML

- `p_clim` é a baseline que o modelo precisa superar (Brier skill score).
- Os limiares e as probabilidades são fixados com anos até 2021 e não são recalculados com 2022+.
- O split hoje é aleatório. Sugestão: dividir treino e teste por ano (cronológico) e agrupado
  por ponto, com um intervalo entre treino e teste do tamanho do horizonte do rótulo.
- O score `1 − p_algum` não é aplicado aqui; definir quem converte, para não converter duas vezes.

## Limitações

- 22 anos de reanálise: os intervalos são largos (com p ≈ 0,5, o IC tem cerca de 0,4 de largura).
- A grade da POWER (~50 km) suaviza os extremos. Não há estação do INMET para validar.
- Há tendência forte em 2000–2021 (chuva caindo em 14 dos 20 pontos, temperatura subindo em
  19). Parte pode ser viés da `PRECTOTCORR`, que a T1 diz piorar nos anos recentes.
- Por decêndio, a chuva > 80 mm quase não acontece (p = 0 em 74% dos casos). Prefira as
  janelas das fases.
- Probabilidade aqui é frequência de um evento definido, não chance de perda de produção.
- A conta supõe `p` constante, mas ela está mudando: entre 2000–2010 e 2011–2021, a chuva
  extrema caiu de 0,60 para 0,30 e a queda brusca subiu de 0,30 para 0,60 (mediana dos
  pontos). O `p` de 2000–2021 é uma média de um período em mudança, e o período de retorno
  derivado dele também.
- Anos vizinhos não são totalmente independentes (ENSO); o IC pode ser otimista.

## Pendências

- Coordenadas de P01–P20.
- Limiares definitivos (agro) e janelas das fases de cada cultura.
- Limiar de "amplitude alta" do indicador de estiagem.
- ENSO: tabela `ano → fase` e o índice (RONI ou ONI). Sem ela, `enso` sai `nao_calculado`.
