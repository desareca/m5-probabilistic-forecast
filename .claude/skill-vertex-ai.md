---
name: vertex-ai
file: skill-vertex-ai.md
description: >
  Patrones y decisiones de diseño para entrenar, registrar y servir modelos
  con Vertex AI. Usar cuando el usuario necesite: empaquetar código de
  entrenamiento en Docker, lanzar Custom Training Jobs, registrar modelos
  en Model Registry, correr Batch Prediction Jobs, construir pipelines KFP,
  o configurar reentrenamiento automático. También usar para seleccionar
  machine types, troubleshooting de jobs fallidos, o decidir entre online
  serving y batch prediction.
---

# Vertex AI — Patrones para proyectos MLE

## Principios de diseño

**Batch prediction sobre online serving para portfolio.** Un endpoint online
en Vertex AI cuesta ~$50–80/mes si se deja encendido. Para un proyecto de
portfolio donde el horizonte es 28 días y no hay usuarios reales, batch
prediction es la decisión correcta — corre bajo demanda, cuesta centavos,
y demuestra el mismo conocimiento de la plataforma.

**Todo el código de entrenamiento va en un script Python, no en un notebook.**
Vertex AI ejecuta scripts empaquetados en Docker, no notebooks. El script
debe recibir hiperparámetros como argumentos de línea de comandos y guardar
los artefactos en GCS al terminar. Esta separación entre exploración
(notebooks) y producción (scripts) es una práctica MLE estándar.

**Artefactos siempre en GCS, nunca locales.** El Training Job corre en una
VM temporal que se destruye al terminar. Todo lo que no esté en GCS al
finalizar se pierde. Guardar modelos, métricas y logs en GCS es obligatorio.

**Credenciales automáticas dentro de Vertex AI.** Los Training Jobs y
Pipeline Components tienen permisos IAM inyectados automáticamente. No
pasar credenciales explícitas en el código — usar los clientes de Google
Cloud normalmente y funcionarán dentro del job.

## Empaquetado del código

El Dockerfile debe ser minimalista: imagen base de Vertex AI (ya tiene
las dependencias de GCP), instalar solo las librerías adicionales necesarias
(LightGBM, pandas, etc.), y un ENTRYPOINT que apunte al script de
entrenamiento. Mantener el `requirements.txt` con versiones fijas para
reproducibilidad.

Subir la imagen a Artifact Registry, no a Docker Hub. Usar la región
`us-central1` para que esté en la misma región que los Training Jobs.

## Custom Training Job

El script de entrenamiento debe seguir este flujo: recibir parámetros via
argparse → cargar datos desde BigQuery → entrenar modelo → guardar artefactos
en GCS → loguear métricas. Mantener el script simple y sin lógica de
orquestación — eso va en el Pipeline.

Para LightGBM Cuantil, entrenar un modelo por percentil en el mismo job
es más eficiente que lanzar un job por percentil. Guardar cada modelo como
archivo separado en GCS.

Selección de machine type: para LightGBM CPU es suficiente — no requiere GPU.
`n1-standard-8` da buen balance entre memoria y costo para el tamaño del M5.

## Model Registry

Registrar el modelo con labels que incluyan las métricas principales
(Pinball Loss por percentil). Esto permite comparar versiones directamente
en la consola de Vertex AI sin necesidad de código. El `artifact_uri` debe
apuntar a la carpeta en GCS donde están los archivos del modelo.

El Model Registry no ejecuta código — solo registra metadata y apunta a
artefactos. El serving container se necesita solo si se va a desplegar un
endpoint online, lo cual no es el caso aquí.

## Vertex AI Pipelines

El pipeline orquesta las fases del proyecto como componentes independientes.
Cada componente es una función Python decorada que corre en su propia VM.
Los componentes se conectan pasando outputs como inputs del siguiente.

La ventaja principal es reproducibilidad: el pipeline YAML compilado es
un artefacto versionable que describe exactamente cómo se entrenó el modelo.
Esto es lo que diferencia un proyecto de portfolio serio de un conjunto de
notebooks.

Mantener los componentes simples — cada uno hace una sola cosa. La lógica
compleja va en los scripts de `src/`, no dentro de los componentes del
pipeline.

## Troubleshooting

Cuando un job falla, el primer lugar para revisar son los logs en Cloud
Logging, no el mensaje de error del SDK que suele ser genérico. En la
consola: Vertex AI → Training → Custom Jobs → Ver logs. Los errores más
comunes son: imagen Docker no encontrada (verificar que el push a Artifact
Registry completó), out of memory (subir machine type o reducir batch size),
y permisos insuficientes para acceder a GCS o BigQuery (verificar service
account del job).
