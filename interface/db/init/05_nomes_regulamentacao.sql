-- Sinais de regulamentação sem tipo (desconhecido ou regulatory_outro): um só nome, "Sinal de regulamentação por identificar".
-- Pode correr mais do que uma vez (a API corre-o ao arrancar).
UPDATE element SET name = 'Sinal de regulamentação por identificar'
WHERE family = 'sinal' AND sign_group = 'regulamentacao'
  AND (subclass IS NULL OR subclass IN ('desconhecido', 'regulatory_outro'))
  AND name IS DISTINCT FROM 'Sinal de regulamentação por identificar';
