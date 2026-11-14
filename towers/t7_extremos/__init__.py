"""Torre 7: probabilidade de extremos climáticos (chuva extrema e queda brusca de temperatura).

Análise de frequência empírica de eventos extremos (não é TVE/GEV/GPD): a probabilidade é a
fração dos anos de referência em que o evento ocorreu, com IC por bootstrap de anos.

Módulos:

- ``dados``: leitura do ``dados_unificados.csv`` (NASA POWER, P01–P20, 2000–2022) e recorte
  da referência (anos até 2021; 2022 em diante é período do ML).
- ``eventos``: definições dos eventos (chuva acumulada, queda de temperatura, amplitude térmica).
- ``probabilidade``: indicadores anuais, probabilidade empírica, bootstrap de anos e suavização.
- ``config``: limiares (valor, unidade, fonte, vigência, status PROVISORIO/DEFINIDO).
"""
