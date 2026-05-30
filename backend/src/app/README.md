# Backend app

API inicial para conectar el frontend con Postgres y SMTP.

## Instalar dependencias

```bash
pip install -r backend/src/app/requirements.txt
```

## Ejecutar API

Desde la raiz del proyecto:

```bash
python -m uvicorn backend.src.app.main:app --reload --host 127.0.0.1 --port 8000
```

## Endpoints iniciales

- `GET /health`: estado general y configuracion visible no sensible.
- `GET /health/db`: prueba la conexion a Postgres.
- `POST /notifications/test-email`: envia un correo de prueba por SMTP.
- `POST /notifications/send-pending`: toma notificaciones pendientes de la base, las envia y actualiza su estado.

El backend lee variables desde `.env` en la raiz del proyecto.
