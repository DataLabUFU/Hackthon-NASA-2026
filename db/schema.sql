-- Esquema do banco do recomendador (NeonDB / Postgres 18).
-- Aplicado e carregado por scripts/carregar_neon.py (idempotente: recria o conteúdo de cada tabela).
-- Nomes de colunas em minúsculas (no código, as colunas do ECOCROP são maiúsculas: TMIN → tmin).

-- Registro de cada carga: de onde veio, quantas linhas e quando.
create table if not exists cargas (
    tabela        text primary key,
    linhas        integer not null,
    origem        text not null,
    sha256_origem text,
    carregado_em  timestamptz not null default now()
);

-- Arquivos brutos pequenos que o código lê como arquivo (ECOCROP, manifesto do ZARC).
create table if not exists arquivos (
    caminho       text primary key,          -- relativo à raiz do repositório, ex.: data/raw/ecocrop/EcoCrop_DB.csv
    conteudo      bytea not null,
    bytes         integer not null,
    sha256        text not null,
    atualizado_em timestamptz not null default now()
);

-- IBGE: municípios com coordenada da sede (data/raw/ibge/municipios.csv).
create table if not exists municipios (
    codigo_ibge  integer primary key,        -- = geocódigo do ZARC
    nome         text not null,
    latitude     double precision not null,
    longitude    double precision not null,
    capital      boolean not null,
    codigo_uf    smallint not null,
    siafi_id     integer,
    ddd          smallint,
    fuso_horario text
);

-- Embrapa (Teixeira et al., 2021): água disponível por textura, usada pela T2 e pela classe de solo do ZARC.
create table if not exists ptf_zarc (
    areia      smallint not null,            -- AT, %
    silte      smallint not null,            -- SIL, %
    argila     smallint not null,            -- ARG, %
    ad_mm_cm   double precision not null,    -- ADm2_mm_cm
    classe_ad  text not null,                -- ClasseAD_m2 (AD 0 .. AD 6)
    li_ic      double precision,             -- limite inferior do intervalo de confiança
    ls_ic      double precision,             -- limite superior
    primary key (areia, silte, argila)
);

-- GBIF / Flora e Funga do Brasil: nomes populares em português por espécie.
create table if not exists gbif_nomes (
    especie     text primary key,
    gbif_key    bigint,
    gbif_rank   text,
    gbif_match  text,
    nome_aceito text,
    nomes_pt    text[],
    fontes_pt   text[]
);

-- Catálogo final de culturas (saída de towers.data.culturas.carregar_culturas): para consulta e auditoria.
create table if not exists culturas (
    id_cultura text primary key,
    nome_pt text,
    especie text,
    fonte_inclusao text,
    observacao text,
    id_ecoport integer,
    binomio text,
    variante text,
    sinonimos text,
    familia text,
    nomes_comuns text,
    lispa text,
    lifo text,
    cat text,
    plat text,
    uso text,
    modo text,
    modo_inferido boolean,
    colheita text,
    colheita_origem text,
    tmin integer,
    topmn integer,
    topmx integer,
    tmax integer,
    ktmp integer,
    ktmp_origem text,
    ktmpr integer,
    rmin integer,
    ropmn integer,
    ropmx integer,
    rmax integer,
    fonte_parametros text,
    ciclo_min integer,
    ciclo_max integer,
    phmin double precision,
    phopmn double precision,
    phopmx double precision,
    phmax double precision,
    text text,
    textr text,
    dra text,
    drar text,
    dep text,
    depr text,
    fer text,
    ferr text,
    sal text,
    salr text,
    foto_curto boolean,
    foto_neutro boolean,
    foto_longo boolean,
    foto_sensivel boolean,
    categoria_conhecida boolean,
    ciclo_conhecido boolean,
    chuva_conhecida boolean,
    foto_conhecido boolean,
    nome_pt_origem text,
    obrigatoria boolean,
    nomes_pt_alternativos text[],
    conflito_nome boolean,
    daninha boolean,
    exibivel boolean,
    escala_cultivo smallint,
    tipo_cultura text
);

-- ZARC/MAPA: portarias da safra vigente de cada cultura.
create table if not exists zarc_portarias (
    id         smallint primary key,
    id_cultura text not null,
    safra_ini  smallint not null,
    portaria   text not null,
    unique (id_cultura, safra_ini, portaria)
);

-- ZARC/MAPA: Tábua de Risco da safra vigente, uma linha por município × cultura × manejo × solo × ciclo.
-- Climas e "outros manejos" agregados pelo menor risco indicado (o mesmo critério da T4 e da T6).
-- riscos: 36 caracteres, um por decêndio (posição 1 = dec1): '0' não indicado, '2' 20%, '3' 30%, '4' 40%,
-- '5' 50%, '-' sem valor na tábua.
create table if not exists zarc_vigente (
    geocodigo   char(7) not null,
    id_cultura  text not null,
    irrigado    boolean not null,
    cod_solo    text not null,
    cod_ciclo   text not null,
    portaria_id smallint not null references zarc_portarias (id),
    riscos      char(36) not null,
    primary key (geocodigo, id_cultura, irrigado, cod_solo, cod_ciclo)
);

-- Cache do NASA POWER: série diária de uma célula da grade (o mesmo parquet de data/cache/power).
create table if not exists power_cache (
    lat_c          numeric(7, 3) not null,
    lon_c          numeric(8, 3) not null,
    padrao_horario text not null,            -- 'utc'
    parquet        bytea not null,
    n_dias         integer not null,
    data_ini       date not null,
    data_fim       date not null,
    atualizado_em  timestamptz not null default now(),
    primary key (lat_c, lon_c, padrao_horario)
);

-- SoilGrids pré-calculado para o Brasil (scripts/preparar_soilgrids.py): grade de 0,01° em blocos de 1°.
-- bloco = npz comprimido (numpy) com os arrays 100 × 100 do bloco; ver towers/data/soilgrids_grade.py.
create table if not exists soilgrids_grade (
    lat_n smallint not null,                 -- borda norte do bloco (graus)
    lon_w smallint not null,                 -- borda oeste do bloco (graus)
    bloco bytea not null,
    primary key (lat_n, lon_w)
);

-- Cache do SoilGrids (API): uma consulta (textura, química ou classe WRB) por coordenada.
create table if not exists soilgrids_cache (
    tipo          text not null check (tipo in ('textura', 'quimica', 'classe')),
    lat           numeric(7, 3) not null,
    lon           numeric(8, 3) not null,
    dados         jsonb,                     -- null = consultado e sem dado válido
    atualizado_em timestamptz not null default now(),
    primary key (tipo, lat, lon)
);
