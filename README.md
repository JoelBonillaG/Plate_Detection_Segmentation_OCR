# Plate Detection Segmentation OCR

Sistema de monitoreo vehicular universitario. Detecta vehiculos, lee su placa,
estima velocidad y registra eventos para revision.

## Que hace

El sistema toma video de una camara o archivo, encuentra el carro, lee la placa,
calcula la velocidad por cruce entre dos lineas y guarda un evento. El operador
revisa los eventos y aprueba o rechaza la sancion.

La velocidad se mide rastreando el **carro** (grande y estable) entre dos lineas;
la **placa** solo aporta el mejor crop para el OCR.

## Arquitectura

```text
camara / video
  -> vision (deteccion carro/placa, segmentacion, OCR, velocidad)
  -> base de datos PostgreSQL
  -> API FastAPI (REST + WebSocket + MJPEG)
  -> frontend web
```

La vision puede correr sola (standalone). La API y la DB solo entran cuando se
quiere persistir eventos, publicar WebSocket o servir el video MJPEG.

## Componentes

- `backend/src/vision`: pipeline de vision y captura por camara.
- `backend/src/api`: API FastAPI, eventos, WebSocket, MJPEG y correo.
- `backend/database`: esquema PostgreSQL y seed.
- `ml`: datasets, modelos entrenados y scripts de entrenamiento.
- `frontend`: interfaz web del operador.

## Documentacion por modulo

- [Backend](backend/README.md)
- [API](backend/src/api/README.md)
- [Modelo de datos](backend/database/README.md)
- [Camara](backend/src/vision/camara/README.md)
- [Pipeline](backend/src/vision/pipeline/README.md)
- [Frontend](frontend/README.md)

## Estado actual

El sistema ya conecta camara, pipeline, base de datos y API. El frontend consume
eventos en tiempo real y permite revisar y aprobar o rechazar sanciones.

## Como empezar

1. Sigue [backend/README.md](backend/README.md) para preparar entorno y servicios.
2. Levanta PostgreSQL, la API y la vision.
3. Abre el frontend para ver eventos en vivo.
