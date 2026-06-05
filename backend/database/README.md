# Modelo de datos

Este directorio contiene el esquema inicial para PostgreSQL.

- `init.sql` crea enums, tablas, constraints, indices, triggers de `updated_at` y datos seed.
- `docker-compose.yml` levanta Postgres usando las variables de `.env`.
- Las imagenes se guardan como rutas (`TEXT`), no como blobs.
- `eventos.placa_ocr` nunca se sobrescribe; correcciones humanas van en `placa_validada` y `auditoria_cambios`.
- El detalle del evento tiene tablas separadas para explicar el resultado:
  - `evento_vision_computadora`
  - `evento_sistema_difuso`

Comando:

```bash
docker compose up -d postgres
```

Valores principales esperados en `.env`:

```bash
POSTGRES_DB=monitoreo_vehicular
POSTGRES_USER=monitoreo_user
POSTGRES_PASSWORD=monitoreo_pass
POSTGRES_HOST_PORT=5433
```
