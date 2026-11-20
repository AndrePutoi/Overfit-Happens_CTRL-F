-- CTRL+F — reclamações dos cidadãos sobre o mobiliário urbano
-- Pode correr mais do que uma vez: a API corre este ficheiro ao arrancar, para que uma base de
-- dados já existente ganhe a tabela sem ser preciso apagá-la (docker compose down -v).

CREATE TABLE IF NOT EXISTS complaint (
  id              serial PRIMARY KEY,
  -- referência pelo id externo (sem FK), para sobreviver às reimportações da entrega
  element_ext_id  text NOT NULL,
  element_name    text,                 -- nome no momento da reclamação
  family          text,
  kind            text NOT NULL,   -- posicao, estado, tipo, duplicado, nao_mobiliario, outro (ver restrição abaixo)
  -- estado: o que se passa com o equipamento
  condition       text CHECK (condition IN ('partido', 'sujo', 'vandalizado', 'outro')),
  -- posicao: onde o cidadão diz que está
  suggested_lat   double precision,
  suggested_lon   double precision,
  -- tipo: o tipo que o cidadão diz ser o certo {class, subclass, install_type, color}
  suggested       jsonb,
  suggested_label text,
  -- duplicado: o outro elemento
  duplicate_of    text,
  message         text CHECK (length(message) <= 1000),
  photo_path      text,                 -- relativo a UPLOAD_DIR; só o técnico vê
  status          text NOT NULL DEFAULT 'por_resolver' CHECK (status IN ('por_resolver', 'a_resolver', 'resolvido')),
  response        text CHECK (length(response) <= 1000),   -- resposta da câmara, pública
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  updated_by      text,
  resolved_at     timestamptz,
  CHECK (kind <> 'posicao' OR (suggested_lat IS NOT NULL AND suggested_lon IS NOT NULL)),
  CHECK (kind <> 'estado' OR condition IS NOT NULL),
  CHECK (kind <> 'tipo' OR suggested IS NOT NULL),
  CHECK (kind <> 'duplicado' OR duplicate_of IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS complaint_status_idx ON complaint (status, created_at DESC);
CREATE INDEX IF NOT EXISTS complaint_element_idx ON complaint (element_ext_id);

-- Tipos de reclamação (refeito sempre, para uma base de dados criada com a lista antiga)
ALTER TABLE complaint DROP CONSTRAINT IF EXISTS complaint_kind_check;
ALTER TABLE complaint ADD CONSTRAINT complaint_kind_check
  CHECK (kind IN ('posicao', 'estado', 'tipo', 'duplicado', 'nao_mobiliario', 'outro'));
-- "Outros" precisa de uma descrição
ALTER TABLE complaint DROP CONSTRAINT IF EXISTS complaint_outro_message_check;
ALTER TABLE complaint ADD CONSTRAINT complaint_outro_message_check
  CHECK (kind <> 'outro' OR length(coalesce(message, '')) >= 5);
