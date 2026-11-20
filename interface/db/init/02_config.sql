-- Configuração base: município, zona piloto, fontes de imagem e técnicos.
-- Os elementos, imagens e deteções não vêm daqui: importam-se da entrega do pipeline
-- (docker compose exec api python -m app.importar).

-- Zona piloto fixada a 15/11: Pontes / Praça Melo Freitas até meio da Av. Dr. Lourenço Peixinho
-- Caixa (S, O, N, E) = 40.6405, -8.6560, 40.6460, -8.6440
INSERT INTO municipality (id, name, code_prefix, pilot_zone_name, area) VALUES
  (1, 'Aveiro', 'AV', 'Aveiro — Pontes à Av. Dr. Lourenço Peixinho',
   ST_GeomFromText('POLYGON((-8.6560 40.6405, -8.6440 40.6405, -8.6440 40.6460, -8.6560 40.6460, -8.6560 40.6405))', 4326));

INSERT INTO source (id, key, name, license, attribution, url, enabled, requires_authorization) VALUES
  (1, 'mapillary',  'Mapillary',  'CC BY-SA 4.0', 'Imagens © colaboradores do Mapillary, CC BY-SA 4.0 (mapillary.com)', 'https://www.mapillary.com', true, false),
  (2, 'kartaview',  'KartaView',  'CC BY-SA 4.0', 'Imagens © KartaView e contribuidores, CC BY-SA 4.0', 'https://kartaview.org', false, false),
  (3, 'panoramax',  'Panoramax',  'Depende da instância (CC BY-SA 4.0 ou etalab-2.0)', 'Imagens © Panoramax e contribuidores', 'https://panoramax.fr', false, false),
  (4, 'video',      'Vídeo de rua', 'Própria (dados da equipa, RGPD)', 'Vídeo gravado pela equipa CTRL+F', NULL, true, false),
  (5, 'streetview', 'Google Street View', 'Termos do Google Maps Platform', 'Imagens © Google', 'https://cloud.google.com/maps-platform/terms', false, true),
  (6, 'osm',        'OpenStreetMap', 'ODbL', '© colaboradores do OpenStreetMap (ODbL)', 'https://www.openstreetmap.org/copyright', true, false);

INSERT INTO technician (municipality_id, name, role, token) VALUES
  (1, 'Ana Teixeira', 'Técnica de validação', 'demo-ana');

SELECT setval('municipality_id_seq', (SELECT max(id) FROM municipality));
SELECT setval('source_id_seq', (SELECT max(id) FROM source));
