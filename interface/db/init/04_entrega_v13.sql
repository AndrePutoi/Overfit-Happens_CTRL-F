-- CTRL+F — entrega do pipeline v1.3: bancos (família mobiliario), ilhas de reciclagem, inventário único.
-- Pode correr mais do que uma vez: a API corre este ficheiro ao arrancar, para atualizar uma base de dados
-- já existente sem a apagar.

ALTER TABLE element DROP CONSTRAINT IF EXISTS element_family_check;
ALTER TABLE element ADD CONSTRAINT element_family_check
  CHECK (family IN ('sinal', 'iluminacao', 'residuos', 'mobiliario'));

ALTER TABLE element DROP CONSTRAINT IF EXISTS element_class;
ALTER TABLE element ADD CONSTRAINT element_class CHECK (
     (family = 'sinal'      AND class = 'sinal')
  OR (family = 'iluminacao' AND class IN ('candeeiro', 'poste_luz'))
  OR (family = 'residuos'   AND class IN ('contentor', 'subterraneo'))
  OR (family = 'mobiliario' AND class = 'banco')
);

ALTER TABLE element ADD COLUMN IF NOT EXISTS position_method  text;     -- triangulada_catalogo | vista_unica_k | fundida_...
ALTER TABLE element ADD COLUMN IF NOT EXISTS position_sigma_m real;     -- incerteza (m) dos de vista única
ALTER TABLE element ADD COLUMN IF NOT EXISTS clip_suspect     boolean;  -- aviso do CLIP: pode não ser o que o detetor diz
ALTER TABLE element ADD COLUMN IF NOT EXISTS auto_merged      boolean NOT NULL DEFAULT false;
ALTER TABLE element ADD COLUMN IF NOT EXISTS merged_from      text[];   -- ids fundidos automaticamente pelo pipeline
ALTER TABLE element ADD COLUMN IF NOT EXISTS duplicate_level  text;     -- provavel | possivel
ALTER TABLE element ADD COLUMN IF NOT EXISTS ilha             jsonb;    -- ilha de reciclagem (ilhas.json), só resíduos
ALTER TABLE element ADD COLUMN IF NOT EXISTS fluxo_sugerido   text;     -- resíduos: tipo sugerido pelo modelo (indiferenciado, papel, embalagens, vidro)
ALTER TABLE element ADD COLUMN IF NOT EXISTS fluxo_p          real;     -- probabilidade dessa sugestão

ALTER TABLE duplicate_group ADD COLUMN IF NOT EXISTS level          text;
ALTER TABLE duplicate_group ADD COLUMN IF NOT EXISTS confidence     real;
ALTER TABLE duplicate_group ADD COLUMN IF NOT EXISTS recommendation text;

-- a vista tem e.*: refazê-la para incluir as colunas novas
DROP VIEW IF EXISTS v_element;
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
