-- CTRL+F — esquema da base de dados (PostgreSQL 16 + PostGIS + pgvector), versão 2
-- Alinhado com a entrega do pipeline (esquema 1.x; as colunas da 1.3 estão em 04_entrega_v13.sql).
-- Coordenadas guardadas em WGS84 (EPSG:4326); distâncias calculadas em PT-TM06 (EPSG:3763).

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS vector;

-- Município e zona piloto (uma linha por município)
CREATE TABLE municipality (
  id              serial PRIMARY KEY,
  name            text NOT NULL,
  code_prefix     text NOT NULL DEFAULT 'EL',
  pilot_zone_name text,
  area            geometry(Polygon, 4326)
);

-- Fontes de imagem, com licença e atribuição
CREATE TABLE source (
  id                     serial PRIMARY KEY,
  key                    text UNIQUE NOT NULL,   -- mapillary | kartaview | panoramax | video | streetview
  name                   text NOT NULL,
  license                text NOT NULL,
  attribution            text NOT NULL,
  url                    text,
  enabled                boolean NOT NULL DEFAULT true,
  requires_authorization boolean NOT NULL DEFAULT false
);

-- Técnicos da câmara (autenticação simples por token)
CREATE TABLE technician (
  id              serial PRIMARY KEY,
  municipality_id int REFERENCES municipality,
  name            text NOT NULL,
  role            text,
  token           text UNIQUE NOT NULL
);

-- Cada importação de uma entrega do pipeline
CREATE TABLE import_run (
  id                bigserial PRIMARY KEY,
  schema_version    text,
  pipeline_commit   text,
  generated_at      timestamptz,
  imported_at       timestamptz NOT NULL DEFAULT now(),
  folder            text,
  counts            jsonb,
  decisions_applied int NOT NULL DEFAULT 0,
  decisions_skipped int NOT NULL DEFAULT 0
);

-- Processamentos (vídeo enviado, recolha de uma fonte aberta)
CREATE TABLE job (
  id              bigserial PRIMARY KEY,
  municipality_id int REFERENCES municipality,
  source_id       int REFERENCES source,
  name            text NOT NULL,
  status          text NOT NULL DEFAULT 'na_fila'
                  CHECK (status IN ('na_fila', 'a_processar', 'concluido', 'erro')),
  progress        smallint NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 100),
  n_images        int NOT NULL DEFAULT 0,
  n_detections    int NOT NULL DEFAULT 0,
  n_elements      int NOT NULL DEFAULT 0,
  params          jsonb NOT NULL DEFAULT '{}'::jsonb,
  input_path      text,
  gpx_path        text,
  error           text,
  created_by      text,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now()
);

-- Imagens. Só se guarda caminho para imagens já desfocadas.
CREATE TABLE image (
  id              bigserial PRIMARY KEY,
  ext_id          text UNIQUE NOT NULL,     -- id do pipeline, ex.: 1000180939467653_y180
  source_id       int NOT NULL REFERENCES source,
  job_id          bigint REFERENCES job ON DELETE SET NULL,
  source_image_id text,
  pano_id         text,
  yaw             real,
  captured_at     timestamptz,
  cam             geometry(Point, 4326),
  heading         real,                      -- graus, 0 = norte, sentido horário
  hfov_deg        real,                      -- campo de visão horizontal
  camera_type     text,                      -- perspective | 360
  width           int,
  height          int,
  blurred         boolean NOT NULL DEFAULT false,
  blur_audited    boolean NOT NULL DEFAULT false,  -- auditoria manual do desfoque feita?
  image_path      text,                      -- relativo a MEDIA_DIR
  thumb_path      text,
  CONSTRAINT image_must_be_blurred CHECK ((image_path IS NULL AND thumb_path IS NULL) OR blurred)
);

-- Grupos de possíveis duplicados sugeridos pelo pipeline
CREATE TABLE duplicate_group (
  id             text PRIMARY KEY,           -- ex.: dup-lz-0001
  family         text NOT NULL,
  suggested_keep text,                       -- ext_id do elemento sugerido
  max_distance_m real,
  resolved       boolean NOT NULL DEFAULT false
);

-- Elementos: o que existe na rua
CREATE TABLE element (
  id                     bigserial PRIMARY KEY,
  ext_id                 text UNIQUE NOT NULL,   -- id do pipeline, ex.: sin-aveiro-00001
  municipality_id        int NOT NULL REFERENCES municipality,
  parent_id              bigint REFERENCES element ON DELETE SET NULL,
  family                 text NOT NULL CHECK (family IN ('sinal', 'iluminacao', 'residuos')),
  class                  text NOT NULL,          -- sinal | poste_luz | candeeiro | contentor | subterraneo
  subclass               text,                   -- tipo do sinal (MTSD), ex.: regulatory_stop
  sign_group             text,                   -- grupo em português (só sinais), ex.: prioridade
  code                   text,                   -- código oficial, quando conhecido (ex.: B2)
  name                   text NOT NULL,
  install_type           text,                   -- subterraneo | ilha | indiferenciado | NULL (por classificar)
  color                  text,
  n_units                int,                    -- número de contentores juntos
  geom                   geometry(Point, 4326) NOT NULL,   -- posição ajustada à estrada
  position_original      geometry(Point, 4326),            -- antes do ajuste
  geo_method             text,                   -- vista_unica_profundidade | triangulado | manual
  geo_residual           real,                   -- metros (triangulação)
  position_reliable      boolean NOT NULL DEFAULT false,
  road_adjustment_m      real,
  road_adjustment_method text,
  osm_ref_match          boolean,
  address                text,
  confidence             real CHECK (confidence BETWEEN 0 AND 1),
  n_views                int NOT NULL DEFAULT 1,
  best_detection_id      bigint,
  duplicate_group_id     text REFERENCES duplicate_group ON DELETE SET NULL,
  status                 text NOT NULL DEFAULT 'auto'
                         CHECK (status IN ('auto', 'validado', 'corrigido', 'rejeitado', 'fundido')),
  merged_into            bigint REFERENCES element ON DELETE SET NULL,
  split_from             bigint REFERENCES element ON DELETE SET NULL,
  first_seen_at          timestamptz,
  created_at             timestamptz NOT NULL DEFAULT now(),
  updated_by             text,
  updated_at             timestamptz,
  CONSTRAINT element_class CHECK (
       (family = 'sinal'      AND class = 'sinal')
    OR (family = 'iluminacao' AND class IN ('candeeiro', 'poste_luz'))
    OR (family = 'residuos'   AND class IN ('contentor', 'subterraneo'))
  ),
  CONSTRAINT element_install_type CHECK (
       install_type IS NULL
    OR (class = 'subterraneo' AND install_type = 'subterraneo')
    OR (class = 'contentor'   AND install_type IN ('ilha', 'indiferenciado'))
  ),
  CONSTRAINT element_merged CHECK ((status = 'fundido') = (merged_into IS NOT NULL))
);

-- Deteções: uma caixa numa imagem (todas, também as que ficaram fora do catálogo)
CREATE TABLE detection (
  id              bigserial PRIMARY KEY,
  ext_id          text UNIQUE NOT NULL,     -- ex.: det-sn-00910
  image_id        bigint NOT NULL REFERENCES image ON DELETE CASCADE,
  element_id      bigint REFERENCES element ON DELETE SET NULL,
  family          text NOT NULL,
  class           text NOT NULL,            -- nos sinais: regulamentacao | perigo | informacao | ...
  subtype         text,                     -- tipo do sinal (MTSD)
  score           real NOT NULL CHECK (score BETWEEN 0 AND 1),
  quality         real,
  rank            int,                      -- ordem dentro do elemento (1 = melhor)
  bbox            real[] NOT NULL CHECK (array_length(bbox, 1) = 4),  -- [x1, y1, x2, y2] em píxeis da imagem original
  azimuth         real,
  est_distance    real,
  in_catalog      boolean NOT NULL DEFAULT true,
  excluded_reason text,                     -- papeleira_filter | catalog_filter
  suggested_class text,
  crop_path       text,                     -- relativo a MEDIA_DIR
  extra           jsonb NOT NULL DEFAULT '{}'::jsonb,
  track_id        text,
  embedding       vector(384),
  created_at      timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE element
  ADD CONSTRAINT element_best_detection_fk
  FOREIGN KEY (best_detection_id) REFERENCES detection ON DELETE SET NULL;

-- Pares de possíveis duplicados
CREATE TABLE duplicate_pair (
  id           bigserial PRIMARY KEY,
  group_id     text REFERENCES duplicate_group ON DELETE CASCADE,
  element_a    text NOT NULL,               -- ext_id
  element_b    text NOT NULL,
  family       text,
  distance_m   real,
  same_class   boolean,
  shared_image boolean
);

-- Histórico de decisões do técnico. Não tem chave estrangeira para element de propósito:
-- sobrevive à reimportação da entrega, que apaga e volta a criar os elementos, e é
-- reaplicado depois pelo ext_id. A coluna decision está no formato "decisoes" do pipeline.
CREATE TABLE edit_log (
  id             bigserial PRIMARY KEY,
  element_ext_id text NOT NULL,
  who            text NOT NULL,
  action         text NOT NULL CHECK (action IN ('validar', 'corrigir', 'mover', 'rejeitar', 'repor',
                                                  'fundir', 'separar', 'melhor_imagem')),
  at             timestamptz NOT NULL DEFAULT now(),
  before         jsonb,
  after          jsonb,
  decision       jsonb NOT NULL
);

CREATE INDEX element_geom_idx      ON element USING gist (geom);
CREATE INDEX element_status_idx    ON element (status);
CREATE INDEX element_family_idx    ON element (family, class);
CREATE INDEX element_dup_idx       ON element (duplicate_group_id);
CREATE INDEX image_cam_idx         ON image USING gist (cam);
CREATE INDEX detection_elem_idx    ON detection (element_id);
CREATE INDEX detection_image_idx   ON detection (image_id);
CREATE INDEX duplicate_pair_a_idx  ON duplicate_pair (element_a);
CREATE INDEX duplicate_pair_b_idx  ON duplicate_pair (element_b);
CREATE INDEX edit_log_elem_idx     ON edit_log (element_ext_id, at DESC);
CREATE INDEX job_status_idx        ON job (status, created_at);

-- Vista usada pela API e pelas exportações
CREATE VIEW v_element AS
SELECT
  e.*,
  e.ext_id AS public_id,
  ST_Y(e.geom) AS lat,
  ST_X(e.geom) AS lon,
  ST_Y(e.position_original) AS orig_lat,
  ST_X(e.position_original) AS orig_lon,
  CASE WHEN e.status IN ('validado', 'corrigido') THEN 'verificado'
       WHEN e.status = 'auto' THEN 'por_rever'
       ELSE e.status END AS review_state,
  d.ext_id     AS best_detection_ext_id,
  d.bbox       AS best_bbox,
  d.crop_path  AS best_crop_path,
  i.ext_id     AS best_image_ext_id,
  i.image_path AS best_image_path,
  i.width      AS best_image_width,
  i.height     AS best_image_height,
  i.blur_audited AS best_image_blur_audited,
  s.key        AS source_key,
  s.name       AS source_name,
  s.license    AS source_license,
  s.attribution AS source_attribution,
  p.ext_id     AS parent_ext_id,
  mg.ext_id    AS merged_ext_id,
  sf.ext_id    AS split_from_ext_id
FROM element e
LEFT JOIN detection d ON d.id = e.best_detection_id
LEFT JOIN image i     ON i.id = d.image_id
LEFT JOIN source s    ON s.id = i.source_id
LEFT JOIN element p   ON p.id = e.parent_id
LEFT JOIN element mg  ON mg.id = e.merged_into
LEFT JOIN element sf  ON sf.id = e.split_from;
