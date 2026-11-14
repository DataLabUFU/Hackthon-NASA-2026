import requests
import pandas as pd
import json

'''''

url = 'https://servicodados.ibge.gov.br/api/v1/localidades/microrregioes?orderBy=nome'

resposta = requests.get(url)

if resposta.status_code == 200:

    dados = resposta.json()

    df = pd.json_normalize(dados, sep='_')

    df.to_csv('localizacao_normalizada.csv', index=False, encoding='utf-8-sig')

    print("execução correta api")

else:

    print(f"a conexao nao deu certo{resposta.status_code}")
    print(f"detalhes do erro: {resposta.text}")

'''''


df = pd.read_csv(r'C:\Users\User\Hackton_Nasa\Hackthon-NASA-2026\localizacao_normalizada.csv', sep=',')

print(df.columns, df.head(), df.tail())