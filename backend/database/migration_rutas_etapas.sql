-- Migracion: imagenes de etapas faltantes (placa detectada cruda + segmentacion).
-- Additiva y nullable -> compatible con eventos existentes. Idempotente.

ALTER TABLE evento_vision_computadora
  ADD COLUMN IF NOT EXISTS ruta_placa_detectada TEXT,
  ADD COLUMN IF NOT EXISTS ruta_segmentacion    TEXT;
