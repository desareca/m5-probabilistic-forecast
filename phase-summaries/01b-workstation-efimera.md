# Fase 1b: Migración a Cluster de Workstation Efímero — Resumen

**Fecha:** 2026-07-13
**Estado:** ✅ COMPLETADA

---

## Contexto

La Fase 1 (ver `01-setup-gcp.md`, Adenda del 2026-07-04/05) migró el entorno de trabajo de
WSL2 local a una Cloud Workstation dedicada (`m5-dev-workstation`), con disco persistente de
100GB y `reclaim_policy = RETAIN`. Esa configuración funcionó, pero tenía un problema de
costo no evidente al momento de diseñarla.

## Problema detectado

El **cluster** de Cloud Workstations (`m5-forecast-cluster`) tiene un cargo de control plane
de **~$0.20/hora que corre 24/7 mientras el cluster exista** — independientemente de si la
workstation individual está encendida o apagada. Apagar la workstation entre sesiones (el
hábito esperado) no detiene ese cargo; solo destruir el cluster completo lo hace.

Con uso esporádico del proyecto (sesiones de trabajo puntuales, no continuas), dejar el
cluster corriendo entre sesiones acumula costo fijo sin aportar nada mientras no se está
trabajando activamente.

## Decisión

Tratar el **cluster completo** (no solo la workstation) como recurso efímero: destruirlo al
final de cada sesión de trabajo y recrearlo al inicio de la siguiente, en vez de dejarlo
corriendo permanentemente.

### Por qué no bastaba con apagar la workstation

Apagar la workstation (`gcloud workstations stop`) detiene el cobro de la VM (`e2-standard-4`),
pero no el del cluster. Para eliminar el cargo por completo hay que destruir el cluster vía
Terraform (`terraform destroy -target=...` o, como se implementó acá, un `terraform apply`
completo que lo recrea desde cero en cada sesión).

### El obstáculo: `reclaim_policy`

El disco persistente (100GB, `pd-balanced`, montado en `/home`) estaba configurado con
`reclaim_policy = RETAIN`. Con esa política, destruir el cluster dejaba el disco **huérfano**
— no se puede volver a adjuntar a un cluster nuevo — y seguía generando costo de storage por
separado, sin ningún beneficio real (no hay forma de recuperar ese disco huérfano para
reutilizarlo).

**Fix:** cambiar `reclaim_policy` a `DELETE` en `terraform/workstation.tf`. Con `DELETE`,
destruir el cluster limpia también el disco — no quedan recursos sueltos generando costo.

**Costo de esta decisión:** se pierde el estado de `/home` entre sesiones (paquetes
instalados, archivos temporales, etc.). Se considera aceptable porque:
- El código vive en GitHub, no en el disco local de la workstation.
- Los artefactos de datos/modelos van a GCS, no al disco local.
- Lo único que hay que rehacer cada sesión es el entorno Python (`venv` + `pip install`) y
  clonar el repo — unos pocos minutos, documentado en el checklist de `start-session.sh`.

## Implementación

### `terraform/workstation.tf`
- `reclaim_policy = "DELETE"` en el bloque `persistent_directories` del
  `google_workstations_workstation_config`.

### `scripts/start-session.sh`
Arranca una sesión de trabajo:
1. `terraform apply` completo (sin `-target`) — recrea cluster + config + workstation; el
   resto de la infraestructura (bucket, dataset, IAM) no cambia porque ya coincide con el
   estado deseado en el `.tfstate`. Usar `apply` completo en vez de `-target` es más seguro
   acá: no hay riesgo de dejar el state desincronizado entre recursos relacionados.
2. `gcloud workstations start` — arranca la VM.
3. Imprime la URL de acceso y un checklist post-arranque (el disco es nuevo, `/home` vacío):
   clonar el repo, `sudo apt install python3.12-venv`, crear el venv, `pip install -r
   requirements.txt`, recrear `.env_local` (token de Kaggle, no vive en git).

**Tiempo estimado:** 15-20 min para recrear el cluster + ~1 min para arrancar la VM.

### `scripts/stop-session.sh`
Destruye el cluster al terminar la sesión — libera todo el costo fijo hasta la próxima vez.

## Resultado

- Costo de control plane: de "~$0.20/h continuo" a "~$0.20/h solo durante sesiones activas
  de trabajo" — con el patrón de uso esporádico del proyecto, esto representa una reducción
  sustancial del costo acumulado del componente de mayor gasto fijo de la infraestructura.
- El flujo de trabajo pasa de "encender/apagar la workstation" a "levantar/destruir la
  sesión completa" — un paso extra (`terraform apply`/`destroy` en cada sesión, ~15-20 min de
  espera al inicio), a cambio de no pagar por tiempo inactivo.

## Pendiente / notas para el futuro

- Si el patrón de uso cambiara a sesiones diarias muy frecuentes, valdría la pena reevaluar
  si el costo de recrear el cluster cada vez (tiempo, no dinero) supera el ahorro — con uso
  esporádico actual, la relación favorece claramente el modelo efímero.
- El checklist de reinstalación post-arranque (`python3.12-venv`, etc.) es manual hoy; podría
  automatizarse con un script de bootstrap si el ciclo de sesiones se vuelve más frecuente.
