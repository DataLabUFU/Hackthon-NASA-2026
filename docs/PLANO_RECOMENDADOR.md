# Recomendador de Plantio: plano de execução (v0)

Projeto para o NASA Space Apps. Este documento define o escopo, a arquitetura, as fontes de dados (com links), as restrições de financiamento rural e as etapas de execução do recomendador de plantio.

> **Status:** plano inicial (v0). Todos os links e regras normativas devem ser reconferidos antes de cada entrega. A regulação do crédito rural muda a cada Plano Safra.

---

## 1. Objetivo

Recomendar ao produtor **o que plantar e quando**, em qualquer local do **Brasil**. A recomendação considera:

- o **clima atual e histórico** do local (dados da NASA);
- as **condições do solo no momento do plantio**;
- o **histórico de plantio** (último e penúltimo);
- a **consequência que o próprio produtor escolhe** otimizar (evitar seca, maximizar produtividade, evitar geada, garantir a safrinha, manter o acesso a crédito ou seguro etc.).

O recomendador considera **todas as culturas com parâmetros conhecidos**, mesmo as pouco comuns no Brasil, e informa o nível de confiança de cada recomendação e se a opção é financiável e segurável.

### Por que busca e simulação, e não um modelo preditivo treinado

- O risco do ZARC é **climatológico**: ele vem de séries históricas longas. Entre safras consecutivas, cerca de 96% a 99% dos decêndios da soja têm o mesmo valor (análise feita em `tabua_risco_zarc.parquet`, safras 2023–2026). Por isso, um modelo treinado para prever o ZARC não reage ao clima atual.
- O objetivo é escolhido pelo usuário no momento da consulta. Um modelo treinado fixa um único target.
- Por isso, o núcleo é **simular os cenários candidatos** (cultura × data × ciclo) a partir do estado atual, **calcular as consequências** e **ordenar** os candidatos pelo objetivo escolhido. Os modelos treinados entram em pontos específicos (ver §4.3).

---

## 2. Entradas do usuário

| Campo | Exemplo | Uso |
|---|---|---|
| Localização (município ou lat/lon) | Londrina-PR / -23,3, -51,2 | **Obrigatória**: clima, solo, ZARC e regras regionais |
| Cultura desejada | soja | Candidato principal; as alternativas são geradas automaticamente |
| Data de plantio pretendida | 20/11/2026 | Centro da janela de busca (±30 dias) |
| Problemas no solo | compactado, ácido, arenoso, encharcado | Ajustam a água disponível, a profundidade de raiz e as penalidades |
| Último plantio | soja | Regras de rotação |
| Penúltimo plantio | milho | Regras de rotação |
| Objetivo (consequência) | evitar seca | Define a função de ordenação |
| *(opcional)* Código do CAR | — | Verificação de elegibilidade socioambiental ao crédito |
| *(opcional)* Irrigado? | não | Troca o balanço hídrico de sequeiro pelo irrigado |

---

## 3. Arquitetura

```
                    ┌────────────────────────────────────────────┐
 entrada usuário ──►│ 1. Gerador de candidatos                   │
                    │    culturas (ECOCROP) × datas × ciclos     │
                    └───────────────┬────────────────────────────┘
                                    ▼
      ┌──────────────┬──────────────┼──────────────┬──────────────┬──────────────┐
      ▼              ▼              ▼              ▼              ▼              ▼
 [T1] Aptidão   [T2] Simulação [T3] Solo     [T4] ZARC      [T5] Rotação   [T6] Elegib.
 climática      hídrica NASA   SoilGrids +   (risco         e manejo       crédito /
 (ECOCROP)      (FAO-56)       Embrapa       oficial)                      seguro
      │              │              │              │              │              │
      └──────────────┴──────┬───────┴──────────────┴──────────────┘              │
                            ▼                                                     ▼
                 2. Combinação de scores (gates + média ponderada)        flags / filtro
                            ▼                                                     │
                 3. Ranking pelo objetivo do usuário ◄────────────────────────────┘
                            ▼
                 4. Saída: top-N + métricas + nível de confiança + selos
```

### 3.1 Torres de score

Cada torre devolve, por candidato, um **score em [0, 1]** (1 = melhor) e as métricas que o explicam.

| Torre | Pergunta | Saída | Fontes |
|---|---|---|---|
| **T1 – Aptidão climática** | O clima do local e da janela comporta a cultura? | Aptidão de Ecocrop (mínimo dos trapézios de temperatura, chuva, pH e fotoperíodo) | ECOCROP + NASA POWER |
| **T2 – Simulação hídrica e térmica** | Partindo do estado atual, como a safra se comporta nos anos históricos? | P(perda > 20%), queda média de rendimento, P(geada), P(calor), déficit na floração | NASA POWER, SMAP, IMERG, FAO-56/FAO-33 |
| **T3 – Solo** | O solo do local atende a cultura? | Aptidão de pH, textura, água disponível (AD) e drenagem | SoilGrids, Embrapa/PronaSolos, input do usuário |
| **T4 – ZARC** | O zoneamento oficial indica esse plantio? | Risco 20/30/40% ou "não indicado" → score | Tábua de Risco ZARC (MAPA) |
| **T5 – Rotação e manejo** | O histórico favorece ou prejudica? | Bônus ou penalidade por família, doenças em comum e monocultura | Regras agronômicas (Embrapa) |
| **T6 – Elegibilidade** | Dá para financiar e segurar? | Flags: ZARC ok, Proagro/PSR ok, cultivar registrada, CAR ok | MCR/BCB, RNC, SICAR, IBAMA |

### 3.2 Combinação dos scores: recomendação

A ideia de cada torre gerar um score e um modelo final combinar tudo é boa, com três cuidados:

1. **Não existe target observado para o "score final"** no início. Um modelo combinador supervisionado precisa de um rótulo de resultado real. Sem esse rótulo, o combinador começa como uma **regra explícita e explicável**:
   - **Gates (eliminatórios):** aptidão T1 = 0, ciclo que não cabe na janela, fotoperíodo incompatível.
   - **Média geométrica ponderada** das torres T1–T5: `score = Π sᵢ^wᵢ`. Uma torre muito ruim derruba o total, o que não acontece com a média aritmética. Os pesos `wᵢ` dependem do **objetivo escolhido pelo usuário** (ex.: "evitar seca" aumenta o peso de T2).
   - **T6 não entra na média.** Ela vira um **filtro opcional** ("só opções financiáveis") ou um **selo** no resultado. Elegibilidade a crédito é uma restrição, não uma qualidade agronômica.
2. **As torres não são independentes.** O ZARC (T4) já embute clima e solo, as mesmas informações de T1, T2 e T3. Somar tudo conta a mesma informação duas vezes. Use T4 principalmente como **validação** e como **flag de elegibilidade**, com peso baixo no score.
3. **Combinador aprendido (fase 2):** quando houver rótulo real, troque os pesos fixos por um modelo aprendido. A fonte de rótulo são os **sinistros do seguro rural (PSR/SISSER)** por município, cultura e ano (§5.6). Use uma regressão logística ou um GBM com restrição monotônica sobre os scores das torres. Esse modelo continua interpretável e nele **o split temporal faz sentido**, porque os sinistros variam de um ano para outro.

### 3.3 Níveis de confiança por cultura

| Nível | Critério | Mensagem ao produtor |
|---|---|---|
| **A** | Parâmetros FAO-56 + ZARC para o município | Simulado e validado pelo zoneamento oficial |
| **B** | Parâmetros FAO-56, sem ZARC | Simulado, sem validação oficial e sem acesso garantido a crédito ou seguro |
| **C** | Só ECOCROP | Aptidão climática estimada, avaliar com cautela |

---

## 4. Detalhamento técnico

### 4.1 Gerador de candidatos

- **Culturas:** ~2.500 espécies do ECOCROP, filtradas por T1 (gate) → dezenas de culturas viáveis.
- **Datas:** data pretendida e deslocamentos de −30 a +30 dias, de 10 em 10 (alinhado aos decêndios do ZARC).
- **Ciclos:** precoce, médio e tardio, quando houver parâmetros (ECOCROP `GMIN`/`GMAX`).
- **Fora do escopo da v0:** culturas perenes (café, citros, cana, frutíferas), porque a decisão é de implantação de longo prazo e não de safra.

### 4.2 T2: simulação (núcleo)

- **Balanço hídrico diário FAO-56** (coeficiente de cultura único): depleção da zona de raízes `Dr`, `TAW = AD × profundidade de raiz`, `RAW = p × TAW`, coeficiente de estresse `Ks`, `ETa = Ks × Kc × ET0`.
- **Estado inicial:** umidade atual do solo (POWER `GWETROOT` na v0; SMAP L4 na v1).
- **Clima futuro:** **ensemble de anos análogos**. A safra é simulada com cada um dos ~30 anos históricos (POWER diário, 1991–hoje), e o conjunto vira uma distribuição de resultados → probabilidades.
- **ET0:** Hargreaves (Tmax, Tmin e latitude) na v0; Penman-Monteith da FAO-56 com radiação, vento e umidade relativa da POWER na v1.
- **Rendimento:** `1 − Ya/Ym = Ky × (1 − ETa/ETc)` (FAO-33/FAO-66).
- **Riscos térmicos:** geada (Tmin < 2 °C na fase crítica) e calor (≥ 3 dias com Tmax > 35 °C na floração).
- **Fotoperíodo:** comprimento do dia (fórmula astronômica) × sensibilidade da cultura (ECOCROP).

### 4.3 Onde entra modelo treinado

| Uso | Modelo | Rótulo |
|---|---|---|
| Combinador de scores (fase 2) | Regressão logística / GBM monotônico | Sinistro PSR (sim/não) por município, cultura e ano |
| Calibração do simulador | Ajuste de Kc, p e Ky | Concordância com a Tábua ZARC (simulação partindo de condições médias) |
| Ponderação dos anos análogos (opcional) | Similaridade com o estado atual (ENSO, umidade) | — |
| Surrogate do simulador (opcional) | GBM | Saídas do próprio simulador |

### 4.4 Solo (T3) a partir do input do usuário

| Problema informado | Efeito no modelo |
|---|---|
| Compactado | Profundidade de raiz efetiva × 0,6 → menor TAW |
| Arenoso | AD → AD1/AD2 |
| Argiloso | AD → AD5 |
| Ácido | Penalidade, ou aptidão de pH com o valor informado/SoilGrids |
| Encharcado | Penalidade para culturas sensíveis a encharcamento (drenagem do ECOCROP) |

O dado do usuário **tem prioridade** sobre o dado de mapa (SoilGrids ou Embrapa), porque o mapa tem resolução de 250 m ou menos detalhada e não captura o manejo do talhão.

### 4.5 Rotação (T5): regras iniciais

- Mesma cultura no último plantio: −0,15; repetida também no penúltimo: −0,30.
- Leguminosa → gramínea: +0,10 (nitrogênio residual).
- Pares com doenças em comum (ex.: soja ↔ feijão, mofo-branco): −0,10.
- As regras devem ser revisadas com referências da Embrapa antes da entrega.

---

## 5. Fontes de dados

### 5.1 NASA

| Dado | Uso | Acesso | Autenticação |
|---|---|---|---|
| **NASA POWER** (diário, por ponto): `PRECTOTCORR`, `T2M_MAX`, `T2M_MIN`, `GWETROOT`, `ALLSKY_SFC_SW_DWN`, `RH2M`, `WS2M` | Clima histórico (1981–), ET0, umidade da zona de raízes | Portal: https://power.larc.nasa.gov/ · API: https://power.larc.nasa.gov/docs/services/api/ · Endpoint: `https://power.larc.nasa.gov/api/temporal/daily/point` | Não |
| **SMAP L4 Soil Moisture** (SPL4SMGP, 9 km, 3-horário) | Umidade atual do solo na zona de raízes (v1) | https://nsidc.org/data/spl4smgp | Earthdata Login: https://urs.earthdata.nasa.gov/ |
| **GPM IMERG** (chuva, 0,1°) | Chuva recente em alta resolução | https://gpm.nasa.gov/data/imerg | Earthdata Login |
| **MODIS NDVI** (MOD13Q1, 250 m) | Estado da vegetação e da área (opcional) | https://lpdaac.usgs.gov/products/mod13q1v061/ · Extração por ponto: https://appeears.earthdatacloud.nasa.gov/ | Earthdata Login |

### 5.2 Culturas e parâmetros agronômicos

| Dado | Uso | Acesso |
|---|---|---|
| **FAO ECOCROP** (~2.500 espécies) | T1: temperatura, chuva, pH, textura, fotoperíodo, ciclo | FAO: https://www.fao.org/land-water/resources/tools/databases/ecocrop/en · Busca via GAEZ: https://gaez.fao.org/pages/ecocrop · CSV (cópia do projeto OpenCLIM, licença OGL v3): https://github.com/OpenCLIM/ecocrop (`EcoCrop_DB.csv`) |
| **FAO-56** (Kc, fases, raiz, p) | T2: simulação | https://www.fao.org/3/x0490e/x0490e00.htm |
| **FAO-66, *Crop yield response to water*** (Ky) | T2: queda de rendimento | https://www.fao.org/3/i2800e/i2800e00.htm |
| **GAEZ v4** (requisitos agroclimáticos) | Calibração e validação | https://gaez.fao.org/ |

> O ECOCROP **não** é uma lista de sementes plantáveis no Brasil. Ele traz requisitos ecológicos por espécie, sem considerar o país. A disponibilidade legal de sementes no Brasil vem do **RNC** (§5.5).

### 5.3 Solo

| Dado | Uso | Acesso |
|---|---|---|
| **SoilGrids 2.0** (ISRIC, 250 m): pH, argila, areia, silte, carbono orgânico, densidade | T3, por coordenada | https://soilgrids.org · REST API: https://rest.isric.org/soilgrids/v2.0/docs |
| **Embrapa GeoInfo**: mapa de solos do Brasil 1:5.000.000, aptidão agrícola, vulnerabilidade à erosão | T3 e contexto | https://geoinfo.dados.embrapa.br/ · Aptidão agrícola: https://geoinfo.dados.embrapa.br/catalogue/#/map/6499 |
| **PronaSolos** (Embrapa/CPRM/IBGE) | Mapas e perfis de solo em escala maior | Documento do programa: https://www.gov.br/agricultura/pt-br/arquivos/mapa-pronasolos.pdf/@@download/file (confirmar a URL atual da plataforma SigWeb) |
| **Classes AD do ZARC** | Conversão textura → água disponível | Portarias ZARC por cultura (§5.4) |

### 5.4 Zoneamento e dados oficiais brasileiros

| Dado | Uso | Acesso |
|---|---|---|
| **Tábua de Risco ZARC** (MAPA, CC-BY) | T4, validação e elegibilidade | Dados abertos: https://dados.agricultura.gov.br/dataset/tabua-de-risco-zoneamento-agricola-de-risco-climatico · Painel: https://mapa-indicadores.agricultura.gov.br/publico/extensions/Zarc/Zarc.html |
| **Portarias e notas técnicas do ZARC** | Cultivares, classes de solo, regras por cultura | https://www.gov.br/agricultura/pt-br/assuntos/riscos-seguro/programa-nacional-de-zoneamento-agricola-de-risco-climatico |
| **IBGE: localidades e malhas** | Geocódigo, centroides, micro e mesorregiões | https://servicodados.ibge.gov.br/api/docs/localidades · https://servicodados.ibge.gov.br/api/docs/malhas |
| **IBGE: PAM** (produção agrícola municipal) | Culturas praticadas por município, validação | https://sidra.ibge.gov.br/pesquisa/pam/tabelas |

### 5.5 Sementes e cultivares

| Dado | Uso | Acesso |
|---|---|---|
| **RNC: Registro Nacional de Cultivares (CultivarWeb)** | Selo "cultivar registrada no Brasil" | https://www.gov.br/agricultura/pt-br/acesso-a-informacao/tecnologia-da-informacao/sistemas/orgaos/mapa/vegetal/snpc-cultivar-web · A "Lista de Cultivares Registradas e Protegidas" está prevista no Plano de Dados Abertos do MAPA 2025–2027; confirmar se já existe exportação em lote |

### 5.6 Seguro, crédito e resultados reais

| Dado | Uso | Acesso |
|---|---|---|
| **SISSER / PSR**: apólices de seguro rural subvencionadas (2006–2025) | Rótulo para o combinador (sinistros) e validação | https://dados.agricultura.gov.br/dataset/sisser3 · Dicionário: https://dados.agricultura.gov.br/dataset/baefdc68-9bad-4204-83e8-f2888b79ab48/resource/2c5c55d0-1473-4749-b08f-cfaf887a9fa3/download/dicionariodedados-sisser.pdf |
| **Manual de Crédito Rural (MCR)** | Regras de elegibilidade (T6) | https://www3.bcb.gov.br/mcr · Normativos: https://normativos.bcb.gov.br/ |
| **Proagro (BCB)** | Regras do programa | https://www.bcb.gov.br/content/estabilidadefinanceira/proagro_docs/resumo_instrucoes_Proagro.pdf |

### 5.7 Socioambiental (elegibilidade ao crédito)

| Dado | Uso | Acesso |
|---|---|---|
| **SICAR: Cadastro Ambiental Rural** | Situação do CAR do imóvel | https://www.car.gov.br/ |
| **IBAMA: áreas embargadas** | Embargos ambientais | https://servicos.ibama.gov.br/ctf/publico/areasembargadas/ConsultaPublicaAreasEmbargadas.php |
| **FUNAI: terras indígenas** e **ICMBio: unidades de conservação** | Sobreposição com áreas protegidas | Geoserviços FUNAI e ICMBio (confirmar URLs na implementação da T6) |

---

## 6. Restrições de financiamento e seguro rural

> **Aviso:** resumo para orientar o produto, **não** é aconselhamento jurídico ou financeiro. O texto vigente do MCR (Banco Central) prevalece e deve ser conferido a cada Plano Safra. O recomendador deve sempre exibir: *"confirme as condições com sua instituição financeira"*.

### 6.1 ZARC como condição de crédito

- O MCR subordina a concessão de crédito rural às recomendações do zoneamento agroecológico e do ZEE e, **nas operações de custeio agrícola, do ZARC**.
- **A partir da safra 2025/26**, o crédito de **custeio agrícola** passou a exigir a observância das recomendações do ZARC também em valores maiores e em contratos **sem** Proagro. Antes, a exigência valia principalmente para operações do Pronaf de até R$ 200 mil com Proagro obrigatório (MAPA; Resolução CMN 5.229/2025, segundo a Agroicone).
- Nas localidades **não abrangidas** pelo ZARC, o MCR admite o uso de outro zoneamento (ex.: ZEE).
- **Impacto no produto:** plantar **fora da janela** ou em **célula "não indicada"** do ZARC pode inviabilizar o custeio. Culturas sem ZARC (níveis B e C) podem ter acesso restrito a crédito e seguro.

### 6.2 Proagro e seguro rural (PSR)

- **Proagro:** é obrigatória a observância do ZARC (cultura, município, solo e período de plantio) para o enquadramento. O MCR (cap. 12) restringe o custeio enquadrado aos empreendimentos conduzidos sob as condições do ZARC.
- **Resolução CMN 5.224/2025:** enquadramento obrigatório no Proagro para custeio de até R$ 200 mil em lavouras zoneadas (limite de R$ 200 mil por beneficiário por ano).
- **Resolução CMN 5.227/2025:** a partir de 2025/26, as indenizações do Proagro devem cobrir pelo menos 60% das perdas reconhecidas.
- **Subvenção ao Prêmio do Seguro Rural (PSR):** usa o ZARC como requisito.
- Proagro Mais (Pronaf) segue as normas gerais do Proagro, inclusive quanto ao ZARC.

### 6.3 Impedimentos socioambientais (MCR seção 2-9)

Alterados pela Resolução CMN 5.193/2024 e depois pelas Resoluções 5.267 e 5.268/2025:

- **CAR:** não se concede crédito a imóvel **sem inscrição no CAR**, ou com inscrição **cancelada ou suspensa** (há ressalvas no MCR).
- **Terras indígenas:** vedado crédito a imóvel total ou parcialmente inserido em terra indígena (com as ressalvas do texto).
- **Unidades de conservação e áreas protegidas:** as instituições devem verificar a sobreposição.
- **Embargos ambientais:** a regra anterior (Res. 5.081) vedava totalmente; a Res. 5.193/2024 permite crédito, **até meados de 2027**, a imóveis embargados com CAR ativo e em análise. As fontes divergem entre 30/06/2027 e julho de 2027; conferir.
- **Desmatamento após julho de 2019:** exigências adicionais.
- **Monitoramento:** as instituições financeiras passaram a fiscalizar por sensoriamento remoto (Res. 5.267/2025).

### 6.4 Outras condições a verificar

- **Cultivar:** as portarias do ZARC indicam cultivares e grupos de maturação. Usar cultivar registrada no RNC e compatível com a portaria é condição frequente para o Proagro e o seguro. Conferir por cultura.
- **Cadastro de empregadores (trabalho análogo à escravidão):** é impedimento usual no crédito rural. Conferir a redação vigente no MCR.
- **Pronaf e Pronamp:** têm limites, taxas e requisitos próprios (DAP/CAF etc.). A v0 só informa e não simula.

### 6.5 Como a T6 entra no produto

| Verificação | v0 | v1 |
|---|---|---|
| Candidato dentro da janela ZARC (não "não indicado") | ✅ automática (Tábua ZARC) | ✅ |
| Cultura zoneada no município | ✅ automática | ✅ |
| Cultivar registrada no RNC | ⚠️ selo, se houver exportação em lote | ✅ |
| CAR ativo, embargo IBAMA, TI e UC | ℹ️ só aviso | ✅ com o código do CAR informado |
| Filtro "só financiável/segurável" | ✅ | ✅ |

---

## 7. Plano de execução

### Fase 0: fundação
- [ ] Estrutura do repositório (§8), ambiente e `requirements.txt` (polars, numpy, requests, pyarrow).
- [ ] Download e cache local de: ECOCROP, Tábua ZARC, IBGE (centroides dos municípios).
- [ ] Cliente da NASA POWER com cache em parquet por coordenada.
- **Entrega:** dados locais e notebook de exploração.

### Fase 1: MVP do simulador (T1 + T2)
- [ ] Limpeza do ECOCROP: tabela normalizada de parâmetros e mapeamento nome científico → nome comum PT-BR.
- [ ] T1: aptidão de Ecocrop (temperatura, chuva, pH e fotoperíodo) por local e janela.
- [ ] Tabela FAO-56/FAO-66 para 20 a 30 culturas anuais (as principais do Brasil + arroz, sorgo, mandioca, batata, hortaliças, girassol, amendoim...).
- [ ] T2: balanço hídrico FAO-56 + ensemble de anos análogos + métricas.
- [ ] Gerador de candidatos e ranking por objetivo (pesos fixos).
- **Entrega:** função `recomendar(...)` funcionando para qualquer coordenada no Brasil.

### Fase 2: solo, ZARC, rotação e elegibilidade (T3–T6)
- [ ] T3: SoilGrids por coordenada + override pelo input do usuário.
- [ ] T4: consulta à Tábua ZARC por geocódigo, cultura, classe AD e decêndio.
- [ ] T5: regras de rotação.
- [ ] T6: flags ZARC, Proagro e PSR; selo RNC; aviso socioambiental.
- [ ] Níveis de confiança A/B/C.
- **Entrega:** ranking completo com selos.

### Fase 3: validação e calibração
- [ ] Rodar o simulador em condições médias e medir a concordância com o ZARC (acurácia por classe, por cultura e por região).
- [ ] Ajustar Kc, p e Ky para maximizar a concordância.
- [ ] Cruzar as recomendações com os sinistros do PSR: os decêndios de alto risco concentram os sinistros?
- **Entrega:** relatório de validação (número forte para o pitch).

### Fase 4: combinador aprendido (se houver tempo)
- [ ] Dataset: scores das torres × sinistro PSR (município, cultura, ano).
- [ ] Regressão logística ou GBM monotônico com **split temporal** por ano e holdout espacial.
- [ ] Comparar com os pesos fixos.

### Fase 5: produto e pitch
- [ ] Interface (Streamlit ou página web): formulário de entrada, mapa e ranking com explicações.
- [ ] Narrativa: "dados da NASA + zoneamento oficial → recomendação explicável, reativa ao clima atual, com aviso de financiabilidade".

---

## 8. Estrutura proposta do repositório

```
recomendador/
  dados/            # clientes e cache: power.py, smap.py, soilgrids.py, zarc.py, ecocrop.py, ibge.py
  torres/           # t1_aptidao.py, t2_simulacao.py, t3_solo.py, t4_zarc.py, t5_rotacao.py, t6_elegibilidade.py
  culturas/         # parametros_fao56.csv, mapeamento_nomes.csv, regras_rotacao.yaml
  combinador.py     # gates + média geométrica ponderada (e, depois, o modelo aprendido)
  recomendador.py   # orquestração: candidatos → torres → combinação → ranking
notebooks/          # exploração e validação
scripts/            # downloads (ECOCROP, ZARC, PSR, IBGE)
docs/               # este plano
data/               # (gitignored) dados brutos e cache
```

---

## 9. Riscos e limitações

| Risco | Mitigação |
|---|---|
| Parâmetros FAO genéricos (não por cultivar) | Calibrar contra o ZARC; exibir o nível de confiança |
| ECOCROP com faixas amplas e imprecisas | Usar só como gate e triagem |
| `GWETROOT` é a fração da saturação, não da água disponível | Aproximação na v0; SMAP L4 na v1 |
| POWER com resolução de ~0,5° (municípios vizinhos iguais) | Aceitável para clima; o solo vem de fonte de 250 m |
| Regulação do crédito muda a cada Plano Safra | Regras parametrizadas em arquivo de config, com data de vigência; aviso ao usuário |
| Acesso ao ECOCROP e ao RNC em lote incerto | Cópia OpenCLIM do ECOCROP; RNC como selo opcional |
| Dupla contagem entre as torres (ZARC já embute clima e solo) | T4 com peso baixo / como validação |

---

## 10. Referências usadas neste plano

- MCR (BCB): https://www3.bcb.gov.br/mcr/completo
- MAPA, Plano Safra 2025/2026: https://www.gov.br/agricultura/pt-br/assuntos/noticias/2025/governo-federal-lanca-plano-safra-2025-2026-com-r-516-2-bilhoes-para-impulsionar-o-agro-brasileiro
- Agroicone, análise do Plano Safra 2025/26: https://agroicone.com.br/wp-content/uploads/2025/07/Agroicone_Breve-analise-do-Plano-Safra-2025-26-1.pdf
- Resolução CMN 5.224/2025: https://legismap.com.br/leis-e-normas/resolucao-cmn-n-5-224-de-06-06-2025
- Ajustes de crédito e Proagro 2025/26: https://souagro.net/noticia/2025/06/cmn-ajusta-regras-de-credito-rural-e-proagro-para-a-safra-2025-26/
- Embrapa, relatório de impactos do ZARC: https://bs.sede.embrapa.br/2023/relatorios/agriculturadigital_zarc.pdf
- Nota técnica MAPA (Proagro × ZARC): https://www.gov.br/agricultura/pt-br/assuntos/riscos-seguro/programa-nacional-de-zoneamento-agricola-de-risco-climatico/notas-tecnicas-air/notas-tecnicas-2024/NotaTcnica5ArrozeAmendoim.pdf
- Impedimentos socioambientais (Res. 5.193/2024): https://www.conjur.com.br/2025-mar-02/alteracao-das-normas-de-impedimentos-socioambientais-para-acesso-ao-credito-rural/
- Res. CMN 5.267/2025: https://www.audsat.com.br/blog/resolucao-cmn-5267-2025/
- Mudanças na fiscalização em 2026: https://cooperativismodecredito.coop.br/2026/03/o-que-muda-na-fiscalizacao-e-nos-impedimentos-do-credito-rural-em-2026/
- CNA, Guia do Crédito Rural: https://www.cnabrasil.org.br/storage/arquivos/guia_do_credito_rural_versaoonline_2022-05-28-120918_qagk.pdf
