# Hackthon-NASA-2026

## Pipeline de experimentação: Gradient Boosting

Três modelos (LightGBM, XGBoost e CatBoost) implementados via API do scikit-learn, cada um
com pipelines separados de **treino**, **benchmark** e **inferência**.

```
models/
├── common/            # código compartilhado
│   ├── spec.py           # contrato ModelSpec que cada modelo implementa
│   ├── preprocessing.py  # CategoricalCaster + sklearn Pipeline
│   ├── data.py           # leitura (.csv/.parquet), dataset demo, split
│   ├── metrics.py        # métricas de holdout e scorers de CV
│   ├── config.py         # schema da config + carregamento YAML via OmegaConf
│   ├── artifacts.py      # salvar/carregar modelos
│   └── runners.py        # lógica de treino / benchmark / inferência
├── lightgbm/  ┐
├── xgboost/   ├── model.py      # estimador + hiperparâmetros padrão
└── catboost/  ┘   train.py, benchmark.py, inference.py
```

### Instalação

```bash
pip install -r requirements.txt
```

### Uso

Cada modelo tem um YAML em [configs/](configs/) com as seções `data`, `params`, `train`,
`benchmark` e `inference`. Edite o YAML e rode a partir da raiz do repo (troque `lightgbm`
por `xgboost` ou `catboost`):

```bash
python -m models.lightgbm.train       # usa configs/lightgbm.yaml
python -m models.lightgbm.benchmark
python -m models.lightgbm.inference

# Outro arquivo de config (ex.: uma variação do experimento)
python -m models.lightgbm.train --config configs/lightgbm_lr003.yaml
```

A config é resolvida com `OmegaConf.merge`, nesta ordem (a última vence):

1. Schema `ExperimentConfig` em [models/common/config.py](models/common/config.py): defaults
   e validação. Chaves desconhecidas ou tipos errados geram erro.
2. O arquivo YAML.
3. Overrides opcionais `chave=valor` no terminal, para testes rápidos:
   `python -m models.lightgbm.train params.learning_rate=0.03 data.demo=true`

Os `params` do YAML ainda são mesclados por cima dos padrões de `models/<lib>/model.py`.
Os nomes seguem cada lib (no CatBoost, o número de árvores é `iterations`). Cada run salva a
`config.yaml` final já resolvida, para reprodutibilidade.

### Artefatos

```
artifacts/<modelo>/
├── LATEST                      # id do último treino
├── runs/<run_id>/model.joblib  # pipeline + label encoder + metadata
├── runs/<run_id>/metadata.json # params, features, métricas de holdout, versões
├── runs/<run_id>/config.yaml   # config resolvida usada no treino
└── benchmarks/<run_id>/        # summary.json (média ± desvio), folds.csv e config.yaml
```

### Features categóricas

Colunas não numéricas são tratadas como categóricas. O `CategoricalCaster` fixa as
categorias vistas no treino, então os códigos são os mesmos na inferência. Nulos e
categorias novas viram `__missing__`. Cada booster usa o suporte nativo a categóricas da
própria lib.

### Adicionando um novo modelo

Crie `models/<nome>/model.py` exportando um `SPEC = ModelSpec(...)` e copie os três scripts
de entrada de uma das pastas existentes.

## Dados: ZARC (Tábua de Risco)

Os dados do [painel ZARC](https://mapa-indicadores.agricultura.gov.br/publico/extensions/Zarc/Zarc.html)
vêm do [Portal de Dados Abertos do MAPA](https://dados.agricultura.gov.br/dataset/tabua-de-risco-zoneamento-agricola-de-risco-climatico)
(licença CC-BY). Para baixar ou atualizar:

```bash
python scripts/download_zarc.py                  # safras 2022/23 a 2026/27
python scripts/download_zarc.py --safras 2025 --force
```

A saída vai para `data/raw/zarc/` (ignorado pelo git): um CSV por safra, o `tabua_risco_zarc.parquet`
consolidado e um `manifest.json` com a origem e a contagem de linhas. As colunas são as 19 padrão
da tábua (`Nome_cultura` … `Portaria`) mais `dec1`..`dec36`, o risco de plantio em cada
decêndio do ano (0 = não indicado; 20/30/40 = % de risco).
