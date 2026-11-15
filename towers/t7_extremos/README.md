# Torre 7: probabilidade de extremos climáticos

Estima a chance de, numa safra (ou fase) qualquer, acontecer pelo menos um evento climático
forte. Os eventos são:

- **chuva extrema**: chuva somada em 3 dias acima de 80 mm;
- **queda brusca**: a temperatura média cai 5 °C ou mais em 2 dias;
- **algum**: pelo menos um dos dois no mesmo ano.

Também traz um **indicador de estiagem** (amplitude térmica acima do normal), só informativo.

O README principal lista "chuvas extremas" na torre 6 (Elegibilidade e Extremos). No código, os
extremos ficam aqui na T7, como módulo separado; a T6 trata só de crédito, seguro e zoneamento.
Geada e calor não estão na T7: ficam na T1 (aptidão climática) e na T2 (simulação hídrica).

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

As coordenadas estão em `pontos.csv` (centro da célula da grade da POWER, 0,5° x 0,625°).
Os 20 pontos cobrem o Triângulo Mineiro, de 18,5° S a 20° S e de 50,625° W a 47,5° W.
Fora dessas células a torre não responde.

## Como usar

```bash
python -m scripts.t7_sensibilidade       # sensibilidade dos limiares
python -m scripts.t7_validacao           # tendência e janelas de referência
python -m scripts.t7_gpd                 # GPD da chuva (~11 min)
python -m scripts.t7_tabela_referencia --publicar   # tabelas dos 20 pontos
python -m pytest tests/test_t7_extremos.py
```

As tabelas saem em `artifacts/t7/` (fora do git), com um `metadata.json` (limiares, hash do
CSV e versões). Com `--publicar`, as que o ML usa são copiadas para `towers/t7_extremos/tabelas/`,
que vai para o repositório.

Consulta para um ponto, uma data de plantio e as fases do ciclo:

```python
from datetime import date
from towers.t7_extremos.consulta import preparar_base, consultar, consultar_coordenada

base = preparar_base()
fases = [
    {"nome": "plantio",  "inicio": 0,   "fim": 20,  "eventos": ["chuva_extrema", "queda_brusca"]},
    {"nome": "colheita", "inicio": 110, "fim": 130, "eventos": ["chuva_extrema"]},
]
r = consultar(base, "P06", date(2026, 10, 20), fases)
r = consultar_coordenada(base, -18.92, -48.27, date(2026, 10, 20), fases)  # mesma coisa (cai no P06)
```

`inicio` e `fim` são dias depois do plantio. A saída traz `p_chuva_extrema`, `p_oscilacao` e
`p_algum` (cada um com IC e número de anos), `enso`, `indicador_estiagem` e os limiares usados.
Coordenada fora dos 20 pontos devolve `{"status": "fora_da_area"}`.

A torre entrega **probabilidades**, não score. Se o ML quiser um score, ele converte.

## No recomendador (todo o Brasil)

O app chama `avaliar_t7` (`torre.py`), que roda em paralelo com as outras torres e com o mesmo prazo
(30 s). Diferenças em relação a `consulta.py`:

- **Dados:** em vez do CSV dos 20 pontos, usa a série diária do NASA POWER da célula do local (a mesma de
  T1 e T2, `PRECTOTCORR` e `T2M`), então responde em qualquer ponto do país. Eventos, limiares
  (`configs/extremos.yaml`) e funções (`eventos.py`, `referencia.indicadores_diarios`) são os mesmos.
- **Anos:** todos os anos completos da série (2001 em diante), não só 2000–2021 (o corte é do ML).
- **Fases (genéricas, até chegarem as janelas por cultura):** estabelecimento 0–20 dias (chuva e queda),
  floração 40–65% do ciclo (queda) e colheita nos últimos 20 dias (chuva). Ciclo = meio de
  `ciclo_min`–`ciclo_max` do catálogo (120 dias sem dado). Perenes e silvicultura: só o estabelecimento.
- **Score:** `score_t7 = 1 − p_algum` (a conversão sugerida acima). As probabilidades, o IC e `n_anos`
  seguem na saída e aparecem nos cartões e no painel de estatísticas.
- **Peso no combinador** (`towers/combinador/pesos.py`): 0,10 no equilibrado, 0,20 em "estabilidade",
  0,10 em "saúde do solo" e 0,05 em "evitar seca" e "financiamento".

## Limiares

Ficam em `configs/extremos.yaml`. Os de hoje são **PROVISÓRIOS**: foram escolhidos para a
probabilidade não ficar perto de 0 nem de 1 nos 20 pontos (safra out–mar). É um critério
estatístico; o valor que causa dano à lavoura ainda precisa vir do agro.

## Para o time de ML

As probabilidades estão em `towers/t7_extremos/tabelas/`:

| Arquivo | O que tem |
|---|---|
| `referencia_safra.csv` | **principal**: por ponto (com `LAT, LON`) e evento (`chuva_extrema`, `queda_brusca`, `algum`), P(≥ 1 evento na safra out–mar), IC 95%, `n_anos`, `metodo` (`gpd`/`empirico`) e `motivo_metodo` |
| `referencia_decendio.csv` | o mesmo por decêndio (sempre empírico; a chuva quase não passa de 80 mm num decêndio) |
| `gpd_por_ponto.csv` | parâmetros da GPD, níveis de retorno de 10 e 20 safras e diagnósticos |
| `metadata.json` | limiares, anos, hash do CSV, versões e pontos com GPD |

Para atualizar: `python -m scripts.t7_gpd` e depois `python -m scripts.t7_tabela_referencia --publicar`.

- `p_clim` é a baseline que o modelo precisa superar (Brier skill score).
- Os limiares e as probabilidades são fixados com anos até 2021 e não são recalculados com 2022+.
- O split hoje é aleatório. Sugestão: dividir treino e teste por ano (cronológico) e agrupado
  por ponto, com um intervalo entre treino e teste do tamanho do horizonte do rótulo.
- A torre entrega só probabilidades. Se quiserem um score (ex.: `1 − p_algum`), a conversão é de vocês.
- As tabelas têm `PONTO, LAT, LON`, para casar com a grade de vocês.

## GPD (chuva extrema na safra)

`python -m scripts.t7_gpd` (≈ 11 min) ajusta uma GPD por ponto na safra out–mar de 2000–2021.
Saída em `artifacts/t7/gpd/`. Rode antes da tabela de referência.

**Onde entra na torre:** só na chuva extrema da safra out–mar (`referencia_safra.csv`), e só
nos pontos em que a GPD:

1. passou no teste de estabilidade; e
2. concorda com a contagem: o valor empírico cai dentro do IC da GPD. Se o valor observado fica
   fora, o modelo está mal ajustado justamente no nível entregue, e vale a contagem.

Esses pontos ficam com `metodo = gpd`. Os outros pontos, a queda brusca, `algum`, os decêndios
e as fases do ciclo continuam empíricos (`metodo = empirico`). A coluna `motivo_metodo` diz
por quê, e o valor empírico fica sempre ao lado (`p_empirico`, `ic_inf_empirico`,
`ic_sup_empirico`). No YAML: `gpd.usar_na_chuva` liga/desliga a GPD e
`gpd.exigir_concordancia` liga/desliga a regra 2.

Por que só aí: a GPD foi ajustada para a safra inteira e não dá para recortá-la em fases (a
chuva não é igual de outubro a março); e `algum` misturando GPD com contagem exigiria supor que
chuva e queda são independentes, o que não são.

### Fórmulas

Seja `X` a chuva acumulada em 3 dias e `u` um limiar alto. Os excessos `Y = X − u` (só os picos
de cada temporal, depois do declustering) seguem a GPD (Coles, eq. 4.2):

```math
H(y) = \Pr(Y \le y) = 1 - \left(1 + \frac{\xi\, y}{\sigma}\right)^{-1/\xi},
\qquad y > 0,\ \ 1 + \frac{\xi\, y}{\sigma} > 0
```

- `σ > 0`: escala (tamanho típico do excesso);
- `ξ`: forma da cauda. `ξ > 0` cauda pesada; `ξ = 0` exponencial (`H(y) = 1 − e^(−y/σ)`);
  `ξ < 0` cauda com teto em `u − σ/ξ`.

Estimação por máxima verossimilhança (Coles, eq. 4.10), com `k` excessos:

```math
\ell(\sigma, \xi) = -k \log \sigma - \left(1 + \frac{1}{\xi}\right) \sum_{i=1}^{k} \log\!\left(1 + \frac{\xi\, y_i}{\sigma}\right)
```

Os temporais chegam como um processo de Poisson, com `λ` temporais acima de `u` por safra.
A probabilidade de o máximo da safra passar de um nível `z ≥ u` (a que a torre entrega, com
`z = 80 mm`) é:

```math
\Pr(M > z) = 1 - \exp\!\left\{-\lambda \left[1 + \xi\, \frac{z - u}{\sigma}\right]^{-1/\xi}\right\}
```

E o nível de retorno de `T` safras (`Pr(M > z_T) = 1/T`):

```math
z_T = u + \frac{\sigma}{\xi}\left[\left(\frac{\lambda}{-\log(1 - 1/T)}\right)^{\xi} - 1\right]
```

O IC vem do bootstrap de safras: sorteia as safras com reposição e refaz limiar, declustering
e ajuste em cada uma das 200 réplicas.

### Tratamento dos dados para cumprir as hipóteses da GPD (Coles, cap. 4–6):

| Hipótese | O que foi feito | Resultado |
|---|---|---|
| Mesma distribuição ao longo do ano | só dias da safra out–mar | — |
| Excessos independentes | declustering: grupo termina com `r` dias abaixo de `u` (3 na chuva, 2 na queda); só o pico entra | θ ≈ 0,39 na chuva (cada temporal dá 2–3 dias acima de `u`) e 0,73 na queda |
| Limiar `u` | quantil 0,95 da safra; ξ conferido em 0,90, 0,95 e 0,975 | chuva: ξ estável (≈ −0,09); queda: ξ cai para −0,27 em 0,975 |
| Ajuste | máxima verossimilhança; gráfico de probabilidade e KS | correlação PP ≥ 0,99 e KS sem rejeição nos 20 pontos |
| Sem tendência | σ(t) = exp(β₀ + β₁t) pela razão de verossimilhança; taxa de grupos por Kendall | chuva: tamanho sem tendência, mas o nº de temporais cai em 8 pontos; queda: σ cresce em todos (p < 0,05 em 12) |
| Estabilidade | 200 vezes com 85% das safras: oscilação do nível de 10 safras GPD × empírico | aprovada em 13 pontos (chuva) e 10 (queda) |

### Resultados

Mediana dos 20 pontos:

| | p empírico | p GPD | largura do IC (emp. / GPD) | nível de 10 safras (GPD / emp.) |
|---|---|---|---|---|
| chuva > 80 mm em 3 dias | 0,48 | 0,47 | 0,41 / 0,27 | 106 / 112 mm |
| queda ≥ 5 °C em 2 dias | 0,45 | 0,40 | 0,41 / 0,26 | 6,1 / 6,1 °C |

Leitura:

- A GPD concorda com a contagem e dá intervalos mais estreitos, porque usa todos os temporais
  da safra, não só "teve ou não teve".
- Na **queda brusca**, os eventos estão ficando maiores (σ crescendo). A GPD com σ constante
  não vale; seria preciso a tendência no modelo, e extrapolar a tendência para 2026 é arriscado.
- Na **chuva**, o tamanho dos temporais é estável, mas a quantidade cai em 8 pontos: λ constante
  também é uma aproximação.
- ξ é negativo na maioria dos pontos (cauda com limite superior). Com 21 safras isso pode
  subestimar eventos acima do maior já visto: não usar a GPD para níveis muito além do observado.
- O teste de estabilidade divide pela oscilação do empírico; em alguns pontos ela é muito
  pequena e a razão explode (P10 e P13). Olhar junto com o desvio de ξ (≤ 0,09 em todos).
- A GPD passou no teste de estabilidade em 13 pontos. Em 3 deles (P10, P15 e P16) o valor
  empírico ficou fora do IC da GPD, que dava de 0,14 a 0,16 a menos: provável subestimação
  (ξ negativo, λ caindo). Pela regra de concordância, esses três voltaram para o empírico.
- Chuva pela GPD em 10 pontos: P01, P03, P04, P05, P07, P08, P09, P11, P17 e P19.

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

- Limiares definitivos (agro) e janelas das fases de cada cultura.
- Limiar de "amplitude alta" do indicador de estiagem.
- ENSO: tabela `ano → fase` e o índice (RONI ou ONI). Sem ela, `enso` sai `nao_calculado`.
