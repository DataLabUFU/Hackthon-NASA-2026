"""Carga e limpeza da base FAO ECOCROP.

Fonte: cópia da base FAO ECOCROP mantida pelo projeto OpenCLIM (licença OGL v3)
https://github.com/OpenCLIM/ecocrop — arquivo ``EcoCrop_DB.csv``.
O arquivo está em Latin-1 com alguns bytes de outra codificação (ver ``TRADUCAO_BYTES``)
e usa ``NA`` como nulo.

``carregar_ecocrop`` devolve uma linha por espécie (após fundir duplicatas idênticas), já
filtrada e com as colunas derivadas que as torres usam:

- ``binomio``/``variante``/``sinonimos``: identificação e agrupamento de variantes;
- ``uso``: ``agricultura`` ou ``silvicultura`` (filtro ligado por padrão no ranking);
- ``modo``: ``safra`` (anuais/bianuais: janela plantio → fim do ciclo) ou
  ``implantacao`` (perenes: avaliadas no ano inteiro);
- faixa de ciclo (``ciclo_min``/``ciclo_max``) para o modo safra;
- ``KTMP`` (temperatura letal na fase inicial) sempre preenchido, com ``ktmp_origem``
  (``ecocrop``/``imputado``); ``KTMPR`` (letal na planta estabelecida/dormente) como na base,
  sem imputação (quem usa cai no ``KTMP`` quando falta, o que é conservador);
- fotoperíodo: classes aceitas e se a espécie é sensível;
- ``colheita``: ``reprodutiva``, ``vegetativa`` ou ``indefinida`` (+ ``colheita_origem``);
- flags de qualidade do dado (``*_conhecido``/``*_conhecida``).

``expandir_ciclos`` gera uma linha por (espécie, duração da grade) para o modo safra.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Iterable

import polars as pl
import requests

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
CAMINHO_PADRAO = ROOT / "data" / "raw" / "ecocrop" / "EcoCrop_DB.csv"
URL_ECOCROP = "https://raw.githubusercontent.com/OpenCLIM/ecocrop/main/EcoCrop_DB.csv"

# Bytes da faixa 0x80–0x9F que não são Latin-1 válido no arquivo. Identificados pelo contexto
# das palavras (ex.: "Réglisse", "múskathýði" em islandês, "año").
TRADUCAO_BYTES = {
    0x80: "ñ",
    0x82: "é",
    0x87: "ý",
    0x88: "–",
    0x8C: "ʻ",
    0x92: "'",
    0x9B: "ð",
}
RE_CONTROLE = re.compile("[\u0080-\u009f]")

# Durações de ciclo avaliadas no modo safra (dias). Mais densa nos ciclos curtos,
# onde estão as hortaliças e onde se concentram os GMIN (p5 = 30, mediana = 90).
GRADE_CICLO = (30, 45, 60, 75, 90, 105, 120, 150, 180, 210, 240, 300, 365)

# Faixa usada quando GMIN/GMAX = 0 (ciclo desconhecido): mediana das anuais com ciclo conhecido.
CICLO_PADRAO = (90, 180)

# Sem LISPA (tempo de vida), a espécie é tratada como safra se o ciclo MÍNIMO conhecido for até este valor.
# O mínimo separa melhor que o máximo: milho genérico (65–365) → safra; cana (210–365) → implantação.
GMIN_LIMITE_SAFRA = 180

# KTMP ausente → mediana das espécies com KTMP conhecido na mesma faixa de TMIN
# (TMIN < 15 °C: −1 °C; TMIN ≥ 15 °C: 0 °C). O KTMP do ECOCROP varia pouco (p10–p90 ≈ −5 a 0 °C).
KTMP_LIMITE_TROPICAL = 15
KTMP_IMPUTADO = {"temperada": -1, "tropical": 0}

# Uma espécie entra se tiver pelo menos uma categoria de uso agrícola OU indicação de cultivo.
CATEGORIAS_AGRICOLAS = (
    "cereals & pseudocereals",
    "pulses (grain legumes)",
    "vegetables",
    "fruits & nuts",
    "roots/tubers",
    "forage/pasture",
    "cover crop",
    "medicinals & aromatic",
)
INDICACAO_CULTIVO = ("grown on large scale", "grown on small scale")

# Silvicultura: categoria florestal, ou árvore usada para materiais, sem uso alimentar/forrageiro.
CATEGORIAS_ALIMENTO = CATEGORIAS_AGRICOLAS

# Tipo de colheita (decide qual mensagem o alerta de fotoperíodo mostra).
CATEGORIAS_REPRODUTIVAS = ("cereals & pseudocereals", "pulses (grain legumes)", "fruits & nuts")
CATEGORIAS_VEGETATIVAS = ("roots/tubers", "forage/pasture", "cover crop")
# "vegetables" mistura fruto e folha/raiz: decide pelo gênero; gênero fora das duas listas → indefinida.
GENEROS_HORTALICAS_VEGETATIVAS = (
    "Allium", "Apium", "Beta", "Brassica", "Cichorium", "Coriandrum", "Daucus", "Eruca",
    "Lactuca", "Nasturtium", "Petroselinum", "Raphanus", "Spinacia",
)
GENEROS_HORTALICAS_REPRODUTIVAS = (
    "Abelmoschus", "Capsicum", "Citrullus", "Cucumis", "Cucurbita", "Cyphomandra", "Lagenaria",
    "Luffa", "Lycopersicon", "Momordica", "Phaseolus", "Physalis", "Pisum", "Sechium", "Solanum",
    "Vigna", "Zea",
)

# Correções manuais do tipo de colheita para espécies importantes sem CAT na base.
COLHEITA_MANUAL = {
    "Ipomoea batatas": "vegetativa",        # batata-doce: raiz
    "Saccharum officinarum": "vegetativa",  # cana: colmo
}

# Parâmetros que precisam ser idênticos para duas entradas do mesmo binômio serem fundidas.
CHAVE_DUPLICATA = ["binomio", "TMIN", "TOPMN", "TOPMX", "TMAX", "RMIN", "ROPMN", "ROPMX", "RMAX", "GMIN", "GMAX"]

COLUNAS_SAIDA = [
    "id_ecoport", "especie", "binomio", "variante", "sinonimos", "familia", "nomes_comuns",
    "LISPA", "LIFO", "CAT", "PLAT",
    "uso", "modo", "modo_inferido", "colheita", "colheita_origem",
    "TMIN", "TOPMN", "TOPMX", "TMAX", "KTMP", "ktmp_origem", "KTMPR", "RMIN", "ROPMN", "ROPMX", "RMAX",
    "fonte_parametros", "ciclo_min", "ciclo_max",
    # requisitos de solo (Torre 3): ótimo / absoluto
    "PHMIN", "PHOPMN", "PHOPMX", "PHMAX", "TEXT", "TEXTR", "DRA", "DRAR", "DEP", "DEPR", "FER", "FERR", "SAL", "SALR",
    "foto_curto", "foto_neutro", "foto_longo", "foto_sensivel",
    "categoria_conhecida", "ciclo_conhecido", "chuva_conhecida", "foto_conhecido",
]


def baixar_ecocrop(destino: Path = CAMINHO_PADRAO, url: str = URL_ECOCROP) -> Path:
    """Baixa o EcoCrop_DB.csv (só se ainda não existir)."""
    destino = Path(destino)
    if destino.exists():
        return destino
    destino.parent.mkdir(parents=True, exist_ok=True)
    log.info("Baixando ECOCROP de %s", url)
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    destino.write_bytes(r.content)
    return destino


def ler_ecocrop_bruto(caminho: Path | str = CAMINHO_PADRAO) -> pl.DataFrame:
    """Lê o CSV original (Latin-1 + correção dos bytes de ``TRADUCAO_BYTES``, ``NA`` → nulo)."""
    texto = Path(caminho).read_bytes().decode("latin-1").translate(
        {byte: char for byte, char in TRADUCAO_BYTES.items()}
    )
    restantes = sorted({hex(ord(c)) for c in RE_CONTROLE.findall(texto)})
    if restantes:
        log.warning("ECOCROP: bytes de controle sem tradução em TRADUCAO_BYTES: %s", restantes)
    return pl.read_csv(texto.encode(), null_values=["NA", ""], infer_schema_length=None)


def separar_nome(nome: str) -> tuple[str, str, str | None]:
    """Normaliza o nome científico e o separa em (nome, binômio, variante).

    Híbridos ("Musa acuminata x balbisiana") são tratados como um binômio próprio, sem variante.
    """
    nome = " ".join(nome.replace(",", " ").split())
    toks = nome.split(" ")
    if any(t.lower() in ("x", "×") for t in toks[1:3]):
        return nome, nome, None
    return nome, " ".join(toks[:2]), (" ".join(toks[2:]) or None)


def _contem_algum(col: str, termos: tuple[str, ...]) -> pl.Expr:
    """True se a coluna de texto (lista separada por vírgula) contém algum dos termos."""
    return pl.any_horizontal([pl.col(col).fill_null("").str.contains(t, literal=True) for t in termos])


def fundir_duplicatas(df: pl.DataFrame) -> pl.DataFrame:
    """Funde entradas do mesmo binômio com parâmetros climáticos e de ciclo idênticos.

    Fica o nome mais curto (o mais genérico); os outros vão para ``sinonimos``. Para os
    demais campos, vale o primeiro valor não nulo, priorizando a entrada mais completa.
    O KTMP fica com o menor valor conhecido (conservador).
    """
    n_info = pl.sum_horizontal([pl.col(c).is_not_null() for c in df.columns])
    tam = pl.col("especie").str.len_chars()
    outras = [c for c in df.columns if c not in CHAVE_DUPLICATA + ["especie", "id_ecoport", "KTMP", "nomes_comuns"]]

    fundido = (
        df.with_columns(_n_info=n_info).sort("_n_info", descending=True, maintain_order=True)
        .group_by(CHAVE_DUPLICATA, maintain_order=True)
        .agg(
            especie=pl.col("especie").sort_by(tam).first(),
            id_ecoport=pl.col("id_ecoport").sort_by(tam).first(),
            sinonimos=pl.col("especie").sort_by(tam).slice(1),
            KTMP=pl.col("KTMP").min(),
            nomes_comuns=pl.col("nomes_comuns").drop_nulls().str.join(", "),
            **{c: pl.col(c).drop_nulls().first() for c in outras if c != "_n_info"},
        )
        .with_columns(
            sinonimos=pl.when(pl.col("sinonimos").list.len() > 0).then(pl.col("sinonimos").list.join("; ")),
            nomes_comuns=pl.when(pl.col("nomes_comuns") != "").then(pl.col("nomes_comuns")),
        )
    )
    n = df.height - fundido.height
    if n:
        log.info("ECOCROP: %d entradas duplicadas fundidas", n)
    return fundido


def carregar_ecocrop(caminho: Path | str | None = None, baixar: bool = True,
                     readmitir: Iterable[str] = (), modo_forcado: dict[str, str] | None = None,
                     extras: pl.DataFrame | None = None) -> pl.DataFrame:
    """ECOCROP limpo, com uma linha por espécie e as colunas derivadas (ver docstring do módulo).

    - ``readmitir``: espécies que entram mesmo sem categoria agrícola/indicação de cultivo
      (culturas obrigatórias, ex.: Pinus taeda). Continuam sujeitas à validação de temperatura.
    - ``modo_forcado``: {espécie: "safra"|"implantacao"} (ex.: mandioca → safra).
    - ``extras``: linhas no formato do CSV bruto para espécies ausentes do ECOCROP
      (ver ``towers.data.culturas``), com a coluna ``fonte_parametros``.
    """
    caminho = Path(caminho) if caminho else CAMINHO_PADRAO
    if not caminho.exists():
        if not baixar:
            raise FileNotFoundError(caminho)
        baixar_ecocrop(caminho)

    bruto = ler_ecocrop_bruto(caminho).with_columns(fonte_parametros=pl.lit("ECOCROP (FAO)"))
    if extras is not None and extras.height:
        bruto = pl.concat([bruto, extras], how="diagonal_relaxed")
    n0 = bruto.height
    readmitir = [separar_nome(n)[0] for n in readmitir]
    modo_forcado = {separar_nome(k)[0]: v for k, v in (modo_forcado or {}).items()}
    if set(modo_forcado.values()) - {"safra", "implantacao"}:
        raise ValueError(f"modo inválido em modo_forcado: {set(modo_forcado.values())}")

    nomes = [separar_nome(n) for n in bruto["ScientificName"].to_list()]
    df = bruto.rename({"EcoPortCode": "id_ecoport", "FAMNAME": "familia", "COMNAME": "nomes_comuns"}).with_columns(
        especie=pl.Series([n[0] for n in nomes]),
        binomio=pl.Series([n[1] for n in nomes]),
    ).drop("ScientificName")

    # 1) Uso agrícola: categoria agrícola OU indicação de cultivo. Espécies sem nenhuma das duas
    #    informações (ex.: cana-de-açúcar) ficam, marcadas com categoria_conhecida = False.
    #    (A lista de culturas obrigatórias, em etapa posterior, readmite as que forem importantes.)
    df = df.with_columns(categoria_conhecida=pl.col("CAT").is_not_null() | pl.col("PLAT").is_not_null()).filter(
        ~pl.col("categoria_conhecida")
        | _contem_algum("CAT", CATEGORIAS_AGRICOLAS)
        | _contem_algum("PLAT", INDICACAO_CULTIVO)
        | pl.col("especie").is_in(readmitir)
    )
    n_uso = df.height

    # 2) Temperatura é obrigatória: sem ela não há score. As faixas têm de ser ordenadas e
    #    fisicamente possíveis (há erros de digitação na base, ex.: TOPMN = 160).
    df = df.drop_nulls(["TMIN", "TOPMN", "TOPMX", "TMAX"]).filter(
        (pl.col("TMIN") <= pl.col("TOPMN"))
        & (pl.col("TOPMN") <= pl.col("TOPMX"))
        & (pl.col("TOPMX") <= pl.col("TMAX"))
        & (pl.col("TMAX") <= 60)
        & (pl.col("TMIN") >= -60)
    )
    n_temp = df.height

    # 3) Duplicatas idênticas (ex.: "Zea mays" e "Zea mays ssp. mays") viram uma entrada só.
    df = fundir_duplicatas(df)
    df = df.with_columns(
        variante=pl.Series([separar_nome(n)[2] for n in df["especie"].to_list()], dtype=pl.String),
    )

    # 4) Flags de qualidade dos demais parâmetros (sem eliminar a espécie).
    df = df.with_columns(
        chuva_conhecida=(
            pl.all_horizontal(pl.col("RMIN", "ROPMN", "ROPMX", "RMAX").is_not_null())
            & (pl.col("RMIN") >= 0)
            & (pl.col("RMIN") <= pl.col("ROPMN"))
            & (pl.col("ROPMN") <= pl.col("ROPMX"))
            & (pl.col("ROPMX") <= pl.col("RMAX"))
        ).fill_null(False),
        ciclo_conhecido=(
            (pl.col("GMIN") > 0) & (pl.col("GMAX") > 0) & (pl.col("GMIN") <= pl.col("GMAX"))
        ).fill_null(False),
    )

    # 5) KTMP: valor da base ou mediana da faixa de TMIN.
    df = df.with_columns(
        ktmp_origem=pl.when(pl.col("KTMP").is_not_null()).then(pl.lit("ecocrop")).otherwise(pl.lit("imputado")),
        KTMP=pl.coalesce(
            pl.col("KTMP"),
            pl.when(pl.col("TMIN") >= KTMP_LIMITE_TROPICAL)
            .then(KTMP_IMPUTADO["tropical"]).otherwise(KTMP_IMPUTADO["temperada"]),
        ),
    )

    # 6) Uso: silvicultura = categoria florestal, ou árvore para materiais, sem uso alimentar/forrageiro.
    eh_arvore = pl.col("LIFO").fill_null("").str.contains("tree", literal=True)
    df = df.with_columns(
        uso=pl.when(
            ~_contem_algum("CAT", CATEGORIAS_ALIMENTO)
            & (_contem_algum("CAT", ("forest/wood",)) | (eh_arvore & _contem_algum("CAT", ("materials",))))
        ).then(pl.lit("silvicultura")).otherwise(pl.lit("agricultura")),
    )

    # 7) Modo de avaliação. Com LISPA: "annual"/"biennial" → safra, senão implantação.
    #    Sem LISPA: safra se o ciclo mínimo conhecido for curto (≤ 180 dias).
    df = df.with_columns(
        modo_inferido=pl.col("LISPA").is_null(),
        modo=(
            pl.when(pl.col("LISPA").str.contains("annual|biennial")).then(pl.lit("safra"))
            .when(pl.col("LISPA").is_not_null()).then(pl.lit("implantacao"))
            .when(pl.col("ciclo_conhecido") & (pl.col("GMIN") <= GMIN_LIMITE_SAFRA)).then(pl.lit("safra"))
            .otherwise(pl.lit("implantacao"))
        ),
    ).with_columns(
        modo=pl.col("especie").replace_strict(modo_forcado, default=pl.col("modo"), return_dtype=pl.String),
    )

    # 8) Faixa de ciclo (só faz sentido no modo safra). Desconhecido → 90–180 dias.
    eh_safra = pl.col("modo") == "safra"
    df = df.with_columns(
        ciclo_min=pl.when(eh_safra).then(
            pl.when(pl.col("ciclo_conhecido")).then(pl.col("GMIN")).otherwise(CICLO_PADRAO[0])
        ),
        ciclo_max=pl.when(eh_safra).then(
            pl.when(pl.col("ciclo_conhecido")).then(pl.col("GMAX").clip(upper_bound=365))
            .otherwise(CICLO_PADRAO[1])
        ),
    )

    # 9) Fotoperíodo. Classes ECOCROP: curto < 12 h | neutro 12–14 h | longo > 14 h.
    #    Nulo ou "not sensitive" → aceita todas. Sensível = não aceita alguma das três.
    sem_info = pl.col("PHOTO").is_null() | pl.col("PHOTO").str.contains("not sensitive", literal=True)
    df = df.with_columns(
        foto_conhecido=pl.col("PHOTO").is_not_null(),
        foto_curto=sem_info | pl.col("PHOTO").str.contains("short", literal=True),
        foto_neutro=sem_info | pl.col("PHOTO").str.contains("neutral", literal=True),
        foto_longo=sem_info | pl.col("PHOTO").str.contains("long", literal=True),
    ).with_columns(
        foto_sensivel=~(pl.col("foto_curto") & pl.col("foto_neutro") & pl.col("foto_longo")),
    )

    # 10) O que se colhe. Sem pista confiável → "indefinida" (a espécie não é exibida, a menos que
    #     a lista de culturas obrigatórias a defina).
    genero = pl.col("especie").str.split(" ").list.first()
    df = df.with_columns(
        colheita=(
            pl.when(pl.col("uso") == "silvicultura").then(pl.lit("vegetativa"))
            .when(_contem_algum("CAT", CATEGORIAS_REPRODUTIVAS)).then(pl.lit("reprodutiva"))
            .when(_contem_algum("CAT", ("roots/tubers",))).then(pl.lit("vegetativa"))
            .when(_contem_algum("CAT", ("vegetables",)) & genero.is_in(GENEROS_HORTALICAS_VEGETATIVAS))
            .then(pl.lit("vegetativa"))
            .when(_contem_algum("CAT", ("vegetables",)) & genero.is_in(GENEROS_HORTALICAS_REPRODUTIVAS))
            .then(pl.lit("reprodutiva"))
            .when(_contem_algum("CAT", ("vegetables",))).then(pl.lit("indefinida"))
            .when(_contem_algum("CAT", CATEGORIAS_VEGETATIVAS)).then(pl.lit("vegetativa"))
            .otherwise(pl.lit("indefinida"))
        ),
    ).with_columns(
        colheita_origem=pl.when(pl.col("especie").is_in(list(COLHEITA_MANUAL))).then(pl.lit("manual"))
        .when(pl.col("colheita") == "indefinida").then(pl.lit("indefinida"))
        .otherwise(pl.lit("categoria")),
        colheita=pl.col("especie").replace_strict(COLHEITA_MANUAL, default=pl.col("colheita")),
    )

    df = df.select(COLUNAS_SAIDA).sort("especie")
    log.info(
        "ECOCROP: %d espécies brutas → %d com uso agrícola → %d com temperatura válida → %d após fundir "
        "duplicatas (%d safra, %d implantação; %d silvicultura; %d com colheita indefinida)",
        n0, n_uso, n_temp, df.height,
        df.filter(pl.col("modo") == "safra").height, df.filter(pl.col("modo") == "implantacao").height,
        df.filter(pl.col("uso") == "silvicultura").height, df.filter(pl.col("colheita") == "indefinida").height,
    )
    return df


def expandir_ciclos(eco: pl.DataFrame, grade: tuple[int, ...] = GRADE_CICLO, chave: str = "id_ecoport") -> pl.DataFrame:
    """Uma linha por (espécie em modo safra, duração da grade dentro de [ciclo_min, ciclo_max]).

    - Se nenhuma duração da grade cair na faixa, usa a mais próxima do ponto médio.
    - ``ciclo_tipico`` marca a duração mais próxima do ponto médio da faixa (referência realista,
      usada no ``score_t1_tipico``).
    - ``chave``: coluna que identifica cada linha de ``eco`` (``id_cultura`` no catálogo de culturas,
      onde a mesma espécie pode virar mais de uma cultura).
    """
    safra = eco.filter(pl.col("modo") == "safra")
    meio = (pl.col("ciclo_min") + pl.col("ciclo_max")) / 2
    dist = (pl.col("ciclo_dias") - meio).abs()

    return (
        safra.join(pl.DataFrame({"ciclo_dias": list(grade)}, schema={"ciclo_dias": pl.Int64}), how="cross")
        .with_columns(
            dentro=pl.col("ciclo_dias").is_between(pl.col("ciclo_min"), pl.col("ciclo_max")),
            _dist=dist,
        )
        .with_columns(
            _rank_dist=pl.col("_dist").rank("ordinal").over(chave),
            _algum_dentro=pl.col("dentro").any().over(chave),
        )
        .filter(pl.col("dentro") | (~pl.col("_algum_dentro") & (pl.col("_rank_dist") == 1)))
        .with_columns(
            ciclo_tipico=pl.col("_dist") == pl.col("_dist").min().over(chave),
        )
        # Empate no ponto médio (ex.: faixa 60–120 → 75 e 105 equidistantes de 90): fica o menor.
        .with_columns(
            ciclo_tipico=pl.col("ciclo_tipico")
            & (pl.col("ciclo_dias") == pl.col("ciclo_dias").filter(pl.col("ciclo_tipico")).min().over(chave))
        )
        .drop("dentro", "_dist", "_rank_dist", "_algum_dentro")
        .sort(chave, "ciclo_dias")
    )
