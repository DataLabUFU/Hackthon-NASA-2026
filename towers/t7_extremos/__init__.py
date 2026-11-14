"""Torre 7: probabilidade de extremos climáticos.

A pergunta que esta torre responde é simples: **em quantos anos, de cada 100, aconteceu
um evento climático forte numa determinada época do ano?**

Os eventos considerados são:

- **chuva extrema**: muita chuva acumulada em poucos dias (pode encharcar o solo, causar
  erosão e atrapalhar o plantio ou a colheita);
- **queda brusca de temperatura**: a temperatura média cai vários graus em poucos dias;
- **indicador de estiagem** (só informativo): dias com diferença grande entre a máxima e a
  mínima, típicos de tempo seco e céu limpo.

Como a probabilidade é calculada
--------------------------------
1. Cada evento é definido por um **limiar fixo** (por exemplo, "mais de X mm em 3 dias").
2. Para cada ano do histórico, verificamos se o evento aconteceu pelo menos uma vez no período
   de interesse (um decêndio, um mês ou a safra inteira). Cada ano vira um "sim" ou "não".
3. A probabilidade é a fração de anos com "sim". Se o evento ocorreu em 5 de 22 anos,
   a probabilidade é 5/22 ≈ 0,23.

Esse método se chama **análise de frequência empírica**: ele só conta o que aconteceu, sem
ajustar uma curva de probabilidade aos dados. Ajustar curvas (as distribuições da teoria dos
valores extremos) só compensa quando se quer estimar eventos mais raros do que os já vistos,
como "a chuva que acontece uma vez a cada 100 anos". Aqui os limiares são escolhidos para
que o evento aconteça com alguma frequência, e com apenas 22 anos de dados essas curvas
ficam instáveis.

Com poucos anos a estimativa é incerta, por isso toda probabilidade vem acompanhada de um
**intervalo de confiança** (ver ``probabilidade``) e do número de anos usados.

Módulos
-------
- ``dados``: leitura do arquivo de clima e separação do período de referência.
- ``eventos``: cálculo diário de cada evento.
- ``probabilidade``: passagem de dias para anos, probabilidade, intervalo e suavização.
- ``config``: limiares e parâmetros lidos de ``configs/extremos.yaml``.
"""
