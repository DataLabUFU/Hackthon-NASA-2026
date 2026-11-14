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

Todos os comandos rodam a partir da raiz do repo. Troque `lightgbm` por `xgboost` ou `catboost`.

```bash
# Treino (holdout de 20% por padrão; --test-size 0 treina com tudo)
python -m models.lightgbm.train --data data/train.csv --target label --drop id

# Benchmark com validação cruzada (k-fold estratificado para classificação)
python -m models.lightgbm.benchmark --data data/train.csv --target label --drop id --folds 5

# Inferência (usa o último modelo treinado, ou --model <pasta do run>)
python -m models.lightgbm.inference --input data/test.csv --output predictions/lgbm.csv --proba --keep id

# Smoke test com dados sintéticos
python -m models.lightgbm.train --demo
```

Opções úteis:

- `--task classification|regression`: o padrão `auto` infere a tarefa pelo alvo.
- `--params '{"learning_rate": 0.03}'` ou `--params configs/lgbm.json`: sobrescreve hiperparâmetros.
  Os nomes seguem cada lib (no CatBoost, o número de árvores é `iterations`).
- `--seed`, `--output-dir`.

### Artefatos

```
artifacts/<modelo>/
├── LATEST                      # id do último treino
├── runs/<run_id>/model.joblib  # pipeline + label encoder + metadata
├── runs/<run_id>/metadata.json # params, features, métricas de holdout, versões
└── benchmarks/<run_id>/        # summary.json (média ± desvio) e folds.csv
```

### Features categóricas

Colunas não numéricas são tratadas como categóricas. O `CategoricalCaster` fixa as
categorias vistas no treino, então os códigos são os mesmos na inferência. Nulos e
categorias novas viram `__missing__`. Cada booster usa o suporte nativo a categóricas da
própria lib.

### Adicionando um novo modelo

Crie `models/<nome>/model.py` exportando um `SPEC = ModelSpec(...)` e copie os três scripts
de entrada de uma das pastas existentes.
