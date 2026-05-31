CREATE EXTENSION IF NOT EXISTS pgcrypto;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'tipo_evento') THEN
    CREATE TYPE tipo_evento AS ENUM ('normal', 'advertencia', 'infraccion', 'grave');
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'estado_revision') THEN
    CREATE TYPE estado_revision AS ENUM ('automatica', 'pendiente', 'aprobado', 'rechazado');
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'estado_notificacion') THEN
    CREATE TYPE estado_notificacion AS ENUM ('pendiente', 'enviado', 'error');
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'tipo_notificacion') THEN
    CREATE TYPE tipo_notificacion AS ENUM ('felicitacion', 'infraccion');
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'estado_vehiculo') THEN
    CREATE TYPE estado_vehiculo AS ENUM ('activo', 'inactivo', 'bloqueado');
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS usuarios_sistema (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  nombre VARCHAR(120) NOT NULL,
  correo VARCHAR(180) NOT NULL UNIQUE,
  rol VARCHAR(60) NOT NULL DEFAULT 'administrador',
  activo BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS vehiculos (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  placa VARCHAR(12) NOT NULL UNIQUE,
  marca VARCHAR(80),
  modelo VARCHAR(80),
  color VARCHAR(60),
  propietario_nombre VARCHAR(160) NOT NULL,
  propietario_correo VARCHAR(180) NOT NULL,
  propietario_telefono VARCHAR(40),
  estado estado_vehiculo NOT NULL DEFAULT 'activo',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT vehiculos_placa_formato CHECK (placa = UPPER(placa))
);

CREATE TABLE IF NOT EXISTS eventos (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  vehiculo_id UUID REFERENCES vehiculos(id) ON DELETE SET NULL,
  placa_ocr VARCHAR(12) NOT NULL,
  placa_validada VARCHAR(12),
  velocidad NUMERIC(6,2) NOT NULL CHECK (velocidad >= 0),
  limite_velocidad NUMERIC(6,2) NOT NULL CHECK (limite_velocidad > 0),
  tipo_evento tipo_evento NOT NULL,
  estado_revision estado_revision NOT NULL,
  estado_notificacion estado_notificacion NOT NULL DEFAULT 'pendiente',
  nivel_riesgo VARCHAR(40) NOT NULL,
  dias_sancion_sugeridos INTEGER NOT NULL DEFAULT 0 CHECK (dias_sancion_sugeridos >= 0),
  confianza_ocr NUMERIC(5,4) NOT NULL CHECK (confianza_ocr >= 0 AND confianza_ocr <= 1),
  reincidencias INTEGER NOT NULL DEFAULT 0 CHECK (reincidencias >= 0),
  imagen_frame TEXT NOT NULL,
  imagen_placa TEXT NOT NULL,
  observacion_admin TEXT,
  fecha_hora TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  revisado_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT eventos_placa_ocr_formato CHECK (placa_ocr = UPPER(placa_ocr)),
  CONSTRAINT eventos_placa_validada_formato CHECK (placa_validada IS NULL OR placa_validada = UPPER(placa_validada)),
  CONSTRAINT eventos_revision_normal CHECK (
    (tipo_evento = 'normal' AND estado_revision = 'automatica')
    OR tipo_evento <> 'normal'
  )
);

CREATE TABLE IF NOT EXISTS evento_vision_computadora (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  evento_id UUID NOT NULL UNIQUE REFERENCES eventos(id) ON DELETE CASCADE,
  vehiculo_detectado BOOLEAN NOT NULL DEFAULT FALSE,
  confianza_vehiculo NUMERIC(5,4) CHECK (confianza_vehiculo IS NULL OR (confianza_vehiculo >= 0 AND confianza_vehiculo <= 1)),
  bbox_vehiculo JSONB,
  placa_detectada BOOLEAN NOT NULL DEFAULT FALSE,
  confianza_placa NUMERIC(5,4) CHECK (confianza_placa IS NULL OR (confianza_placa >= 0 AND confianza_placa <= 1)),
  bbox_placa JSONB,
  ruta_placa_detectada TEXT,
  ruta_placa_enderezada TEXT,
  ruta_placa_filtrada TEXT,
  ruta_segmentacion TEXT,
  caracteres_segmentados INTEGER CHECK (caracteres_segmentados IS NULL OR caracteres_segmentados >= 0),
  resultado_ocr VARCHAR(12),
  confianza_ocr NUMERIC(5,4) CHECK (confianza_ocr IS NULL OR (confianza_ocr >= 0 AND confianza_ocr <= 1)),
  metadata JSONB NOT NULL DEFAULT '{}'::JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS evento_sistema_difuso (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  evento_id UUID NOT NULL UNIQUE REFERENCES eventos(id) ON DELETE CASCADE,
  exceso_velocidad NUMERIC(6,2) NOT NULL DEFAULT 0,
  pertenencia_velocidad JSONB NOT NULL DEFAULT '{}'::JSONB,
  pertenencia_reincidencia JSONB NOT NULL DEFAULT '{}'::JSONB,
  pertenencia_confianza_ocr JSONB NOT NULL DEFAULT '{}'::JSONB,
  nivel_riesgo VARCHAR(40) NOT NULL,
  dias_sancion_sugeridos INTEGER NOT NULL DEFAULT 0,
  reglas_activadas JSONB NOT NULL DEFAULT '[]'::JSONB,
  salida_crisp NUMERIC(8,4),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS notificaciones (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  evento_id UUID NOT NULL REFERENCES eventos(id) ON DELETE CASCADE,
  correo_destino VARCHAR(180) NOT NULL,
  tipo_notificacion tipo_notificacion NOT NULL,
  asunto VARCHAR(220) NOT NULL,
  mensaje TEXT NOT NULL,
  estado_envio estado_notificacion NOT NULL DEFAULT 'pendiente',
  error_envio TEXT,
  fecha_envio TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS auditoria_cambios (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  evento_id UUID NOT NULL REFERENCES eventos(id) ON DELETE CASCADE,
  usuario_id UUID REFERENCES usuarios_sistema(id) ON DELETE SET NULL,
  usuario_nombre VARCHAR(120) NOT NULL,
  campo_modificado VARCHAR(100) NOT NULL,
  valor_anterior TEXT,
  valor_nuevo TEXT,
  motivo TEXT NOT NULL,
  fecha_hora TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_vehiculos_placa ON vehiculos (placa);
CREATE INDEX IF NOT EXISTS idx_eventos_fecha_hora ON eventos (fecha_hora DESC);
CREATE INDEX IF NOT EXISTS idx_eventos_placa_validada ON eventos (placa_validada);
CREATE INDEX IF NOT EXISTS idx_eventos_tipo_estado ON eventos (tipo_evento, estado_revision);
CREATE INDEX IF NOT EXISTS idx_notificaciones_estado ON notificaciones (estado_envio);
CREATE INDEX IF NOT EXISTS idx_auditoria_evento ON auditoria_cambios (evento_id, fecha_hora DESC);

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_vehiculos_updated_at ON vehiculos;
CREATE TRIGGER trg_vehiculos_updated_at
BEFORE UPDATE ON vehiculos
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_eventos_updated_at ON eventos;
CREATE TRIGGER trg_eventos_updated_at
BEFORE UPDATE ON eventos
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
