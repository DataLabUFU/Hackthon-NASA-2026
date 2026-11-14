# 🌱 NASA Space Apps Challenge — Inteligência para Rotação de Culturas

### Desenvolvido pela Liga Acadêmica DataLab

Uma plataforma inteligente de apoio à decisão agrícola que integra observações da Terra da NASA, dados climáticos, informações de solo e histórico de cultivo para recomendar estratégias de plantio mais produtivas, sustentáveis e resilientes às mudanças climáticas.

### 👥 Equipe

Projeto desenvolvido pelos integrantes da Liga Acadêmica DataLab:

- Lincon
- Izan
- Rodrigo
- Daniel
- Matheus Neves
## 🌎 1. O problema

A agricultura mundial enfrenta desafios cada vez maiores relacionados às mudanças climáticas, à irregularidade das chuvas, ao aumento das temperaturas, à escassez de água e à degradação da saúde do solo.

No Brasil, onde a produção agrícola possui grande importância econômica, essas condições tornam o planejamento das safras uma tarefa complexa.

**A escolha inadequada de culturas pode provocar:**

- Esgotamento de nutrientes do solo;
- Aumento da compactação e da erosão;
- Maior vulnerabilidade a pragas e doenças;
- Excesso de consumo de água;
- Redução da produtividade;
- Perda de oportunidades de cultivo e comercialização;
- Dificuldades de acesso ao crédito rural e ao seguro agrícola.

Diante desse cenário, o desafio proposto pela NASA no Space Apps Challenge é desenvolver uma ferramenta capaz de utilizar dados de observação da Terra para auxiliar agricultores na escolha de rotações de culturas mais adequadas às condições ambientais de suas propriedades.

## 💡 2. Nossa solução

Estamos desenvolvendo uma plataforma inteligente de recomendação agrícola que auxilia produtores rurais a decidir o que plantar e quando plantar, considerando as características específicas de sua propriedade, o histórico de cultivo, as condições ambientais e seus objetivos de produção.

O sistema combina dados de satélites, informações agrícolas brasileiras, indicadores climáticos e modelos computacionais para avaliar diferentes possibilidades de plantio.

Em vez de apresentar uma recomendação genérica, a plataforma simula diferentes cenários agrícolas e classifica as culturas de acordo com sua adequação às condições informadas pelo produtor.

O objetivo é transformar grandes volumes de dados ambientais em informações práticas, acessíveis e interpretáveis para a tomada de decisão no campo.

## 🎯 3. Objetivo do projeto

Recomendar as culturas mais adequadas para cada propriedade rural do Brasil, considerando:

- **Clima:** condições climáticas atuais e históricas, utilizando observações da NASA.
- **Solo:** características e condições do solo no período previsto para o plantio.
- **Histórico agrícola:** culturas plantadas nas duas safras anteriores.
- **Localização:** estado e município da propriedade.
- **Problemas identificados:** pragas, compactação, deficiência de nutrientes e outras limitações.
- **Preferências do produtor:** culturas que deseja plantar.
- **Objetivos de produção:** maximização da renda, conservação de água, aumento de nitrogênio, descompactação do solo, redução de riscos e outros critérios.

A plataforma também busca informar o nível de confiança de cada recomendação e sua elegibilidade para financiamento e seguro agrícola, conforme as regras e fontes oficiais disponíveis.

## 🧑‍🌾 4. Como funciona a plataforma?
### 4.1. Entrada de dados pelo produtor

O produtor informa os dados básicos de sua propriedade e suas intenções para a próxima safra.

| Campo	 | Descrição |
|--------|----------|
| Penúltima plantação |Cultura cultivada na safra anterior à última |
Antepenúltima plantação	|Cultura cultivada duas safras atrás
Localização	|Estado e município da propriedade
Problemas na área	|Pragas, solo compactado, erosão, deficiência nutricional etc.
Data da próxima plantação	|Data prevista para iniciar o plantio
Culturas de interesse	|O que o produtor deseja plantar
Objetivos	|Maior renda, conservação de água, aumento de nitrogênio, recuperação do solo etc.

Essas informações permitem personalizar as recomendações de acordo com a realidade de cada produtor.

### 4.2. Motor de análise: as seis torres

O núcleo da plataforma é composto por seis torres de análise independentes. Cada torre avalia uma dimensão específica da produção agrícola e gera um score para cada cenário de plantio.

#### 1. Torre Climática

Avalia as condições climáticas atuais e históricas da região.

Considera:

- Temperatura;
- Precipitação;
- Histórico de chuvas;
- Estresse térmico;
- Evapotranspiração;
- Eventos climáticos extremos.

#### 2. Torre do Solo

Analisa as condições e características do solo.

Considera:

- Características físicas e químicas;
- Fertilidade;
- Compactação;
- Disponibilidade de nutrientes;
- Matéria orgânica;
- Potencial de recuperação da saúde do solo.

#### 3. Torre Hídrica

Avalia a disponibilidade de água e a demanda hídrica das culturas.

Considera:

- Umidade do solo;
- Disponibilidade hídrica;
- Histórico de déficit de água;
- Evapotranspiração;
- Demanda hídrica de cada cultura;
- Tendências de escassez hídrica.

#### 4. Torre ZARC

Verifica a adequação da cultura ao Zoneamento Agrícola de Risco Climático (ZARC).

Considera:

- Município;
- Cultura;
- Tipo de solo;
- Ciclo da cultura;
- Época de semeadura;
- Nível de risco climático;
- Elegibilidade conforme as regras oficiais aplicáveis.

#### 5. Torre de Rotação

Analisa a sequência de culturas e suas consequências agronômicas.

Considera:

- Histórico das duas últimas plantações;
- Alternância entre famílias botânicas;
- Ciclagem de nutrientes;
- Fixação biológica de nitrogênio;
- Interrupção de ciclos de pragas e doenças;
- Potencial de cobertura e recuperação do solo;
- Demanda hídrica e complementaridade entre culturas.

#### 6. Torre de Elegibilidade e Extremos

Avalia restrições regulatórias, operacionais e riscos extremos que podem comprometer a recomendação.

Considera:

- Elegibilidade para crédito rural;
- Condições para contratação de seguro agrícola;
- Restrições de zoneamento;
- Risco de geadas;
- Chuvas extremas;
- Ondas de calor;
- Outros eventos climáticos relevantes.

Cada torre realiza sua análise de maneira independente, permitindo que o sistema identifique os fatores que favorecem ou prejudicam cada alternativa de plantio.

### 4.3. Modelo de integração e classificação

Após as análises individuais, um modelo central recebe os scores das seis torres e realiza a integração das informações.

O sistema avalia os resultados considerando os objetivos definidos pelo produtor e classifica os cenários de plantio em três grupos:

|Classificação	|Interpretação|
|------------|----------------|
🟢 Top 3	|Culturas com as maiores pontuações e melhor adequação ao cenário
🟡 Intermediárias |Alternativas viáveis, mas com algumas limitações
🔴 Bottom 3	|Alternativas com menor adequação às condições analisadas

Para cada cultura, a plataforma apresenta:

- Score geral;
- Scores individuais das seis torres;
- Justificativa da recomendação;
- Benefícios esperados;
- Riscos identificados;
- Nível de confiança;
- Adequação ao objetivo do produtor;
- Situação de elegibilidade para financiamento e seguro, quando verificável.

**A classificação não representa uma garantia de produtividade. Ela funciona como instrumento comparativo de apoio à decisão.**

## 🧠 5. Por que utilizar busca e simulação em vez de um único modelo preditivo treinado?

Uma das principais decisões técnicas do projeto é utilizar um mecanismo de busca e simulação de cenários, em vez de depender exclusivamente de um modelo preditivo treinado.

Isso acontece porque o problema envolve duas características importantes:

### 1. O risco climático não muda necessariamente de uma safra para outra.

O ZARC é construído a partir de séries históricas de dados climáticos e critérios agronômicos. Em uma análise realizada sobre os dados de soja da tabela tabua_risco_zarc.parquetsafras, referentes às safras de 2023 a 2026, observou-se que aproximadamente 96% a 99% dos decêndios mantêm o mesmo valor entre safras consecutivas.

Assim, um modelo treinado apenas para prever o ZARC pode reproduzir padrões históricos sem responder adequadamente às condições atuais da propriedade.

### 2. Os objetivos variam de produtor para produtor.

Um agricultor pode priorizar a conservação de água, enquanto outro deseja maximizar a produtividade, aumentar a renda, recuperar o solo ou garantir a possibilidade de uma segunda safra.

Um modelo treinado para prever um único resultado teria dificuldade em atender a todos esses objetivos de maneira flexível.

#### Nossa abordagem:

Em vez de prever uma única resposta, o sistema:

- Identifica as condições atuais da propriedade.
- Gera cenários candidatos de cultura, ciclo e época de - plantio.
- Simula as consequências agronômicas e climáticas de cada cenário.
- Executa as seis torres de análise.
- Integra os scores considerando os objetivos do produtor.
- Ordena os cenários e apresenta as melhores alternativas.

Os modelos de aprendizado de máquina podem ser utilizados em pontos específicos da arquitetura, complementando as análises quando houver dados adequados para treinamento e validação.

## 🛰️ 6. Integração com dados da NASA

Um dos pilares do projeto é a utilização de dados de observação da Terra disponibilizados pela NASA.

Esses dados permitem analisar as condições ambientais de diferentes regiões brasileiras e identificar tendências que podem influenciar o planejamento agrícola.

Entre os conjuntos de dados de interesse estão:

|Fonte	|Aplicação no projeto|
|----------|-----------------|
|NASA POWER	|Temperatura, precipitação e variáveis meteorológicas
|SMAP	|Umidade do solo
ECOSTRESS	|Temperatura da superfície e estresse térmico
GPM	|Precipitação e eventos de chuva
Landsat	|Monitoramento da cobertura e mudanças na vegetação
MODIS	|Índices de vegetação e monitoramento ambiental
GRACE / GRACE-FO	|Tendências de armazenamento de água
SRTM	|Características topográficas e elevação

A integração dessas fontes possibilita construir uma visão ambiental mais completa da propriedade.

Sempre que necessário, os dados serão harmonizados considerando suas diferentes resoluções espaciais e temporais.

É importante destacar que observações por satélite representam estimativas e medições indiretas de determinadas condições ambientais. Por isso, a combinação com dados locais e informações fornecidas pelo produtor é fundamental.

## 🌱 7. Estratégias de rotação de culturas

A plataforma busca avaliar diferentes culturas e combinações de rotação, considerando as condições locais e as prioridades do produtor.

Entre as estratégias que podem ser exploradas estão:

- Leguminosas: culturas com potencial de fixação biológica de nitrogênio.
- Culturas de cobertura: proteção do solo contra erosão e melhoria da infiltração de água.
- Culturas de raízes profundas: exploração de diferentes camadas do solo e potencial contribuição para sua estrutura.
- Culturas tolerantes à seca: alternativas para regiões com maior risco de déficit hídrico.
- Alternância de famílias botânicas: estratégia para reduzir a pressão de pragas e doenças.

O sistema não considera apenas a cultura isoladamente, mas também sua relação com o histórico de plantio e com as culturas que poderão ser cultivadas posteriormente.

## 📊 8. Resultados esperados

Ao final da análise, o produtor terá acesso a uma comparação entre diferentes possibilidades de plantio.

A interface deverá apresentar:

Ranking das melhores culturas;
Comparação entre as seis torres;
Justificativas técnicas;
Indicadores climáticos e ambientais;
Benefícios potenciais para a saúde do solo;
Riscos e limitações;
Informações de elegibilidade para crédito e seguro.

A proposta é permitir que o produtor compreenda não apenas qual cultura foi recomendada, mas também por que ela foi recomendada.

## 🌾 9. Impacto esperado

O projeto busca contribuir para uma agricultura brasileira mais inteligente, sustentável e resiliente.

Entre os impactos esperados estão:

- Melhor planejamento das safras;
- Redução da vulnerabilidade às mudanças climáticas;
- Uso mais eficiente dos recursos hídricos;
- Incentivo à rotação de culturas;
- Recuperação e conservação da saúde do solo;
- Redução de riscos agrícolas;
- Democratização do acesso a informações ambientais e agrícolas;
- Apoio à tomada de decisão de pequenos, médios e grandes produtores.
## ⚠️ 10. Limitações e responsabilidade

A plataforma tem como finalidade apoiar a tomada de decisão, não substituir o conhecimento do produtor rural, de engenheiros agrônomos ou de especialistas locais.

As recomendações dependem da disponibilidade, qualidade, resolução e atualização dos dados utilizados.

Além disso, a elegibilidade para crédito e seguro depende de critérios oficiais e das regras específicas das instituições financeiras e seguradoras.

Por esse motivo, cada recomendação deverá apresentar suas evidências, limitações e incertezas, incentivando a validação local antes da implementação.

## 🚀 11. Visão do projeto

Acreditamos que a combinação entre ciência, tecnologia e conhecimento agrícola pode transformar a maneira como as decisões de plantio são tomadas.

Nosso propósito é aproximar os dados de observação da Terra da NASA da realidade do produtor rural brasileiro, transformando informações ambientais complexas em recomendações compreensíveis e úteis.

Mais do que recomendar o que plantar, queremos ajudar o produtor a entender o impacto de cada escolha sobre o futuro da sua propriedade.

### NASA Space Apps Challenge | Liga Acadêmica DataLab
### UFU | Universidade Federal de Uberlândia
Tecnologia, ciência de dados e inteligência geoespacial a serviço de uma agricultura mais resiliente.