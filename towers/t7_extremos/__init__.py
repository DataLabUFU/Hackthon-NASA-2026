"""Torre 7: probabilidade de extremos climáticos.

Responde: em que fração dos anos aconteceu um evento forte numa época do ano?

Eventos: chuva extrema (muita chuva em poucos dias), queda brusca de temperatura e, só como
informação, um indicador de estiagem (amplitude térmica alta).

Método (frequência empírica): cada evento tem um limiar fixo; cada ano vira "teve" ou "não
teve" evento no período; a probabilidade é a fração de anos com evento (ex.: 5 de 22 ≈ 0,23).
Não ajustamos distribuições de valores extremos: elas servem para estimar eventos mais raros
que os observados, o que não é o caso aqui, e ficam instáveis com só 22 anos.

Toda probabilidade vem com intervalo de confiança e número de anos.

Módulos: ``dados`` (leitura), ``eventos`` (cálculo diário), ``probabilidade`` (anos,
probabilidade, intervalo) e ``config`` (limiares).
"""
