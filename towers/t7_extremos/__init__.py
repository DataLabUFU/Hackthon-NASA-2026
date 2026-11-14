"""Torre 7: probabilidade de extremos climáticos.

Estima a chance de, numa safra (ou fase) qualquer, acontecer pelo menos um evento forte.

Eventos: chuva extrema (muita chuva em poucos dias), queda brusca de temperatura e, só como
informação, um indicador de estiagem (amplitude térmica alta).

Método (frequência empírica): cada evento tem um limiar fixo; cada ano vira "teve" ou "não
teve" evento no período; a probabilidade é a fração de anos com evento (ex.: 5 de 22 ≈ 0,23).
Em termos de valores extremos, é a estimativa empírica de ``p = Pr(M > z)``: ``M`` é o
máximo da medida no bloco (ano/fase) e o limiar é o nível ``z``. O período de retorno
``T = 1/p`` é um tempo médio de espera e supõe anos independentes e ``p`` constante.

Não ajustamos GEV/GPD: elas servem para extrapolar além do observado, o que não é o caso
aqui, e com blocos curtos e só 22 anos a aproximação fica ruim e instável.

Toda probabilidade vem com intervalo de confiança e número de anos.

Módulos: ``dados`` (leitura), ``eventos`` (cálculo diário), ``probabilidade`` (anos,
probabilidade, intervalo) e ``config`` (limiares).
"""
