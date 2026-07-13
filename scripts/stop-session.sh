#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────
# stop-session.sh — Destruye el cluster de Cloud Workstations al terminar
#
# Uso: ./stop-session.sh
#
# Qué hace:
#   terraform destroy -target=google_workstations_workstation_cluster.m5_cluster
#   Esto borra en cascada: workstation → workstation_config → cluster.
#   Con reclaim_policy = DELETE, el disco persistente se borra junto con
#   todo lo demás — no quedan recursos sueltos cobrando aparte.
#
#   Se usa -target aquí (a diferencia de start-session.sh) porque un
#   destroy completo borraría también el bucket, el dataset de BigQuery
#   y los bindings IAM — cosas que SÍ queremos conservar entre sesiones.
#
# Antes de correr esto: asegúrate de haber hecho push de cualquier cambio
# en el repo. Todo lo que no esté en GitHub o en GCS se pierde con el disco.
# ─────────────────────────────────────────────────────────────────────────
set -euo pipefail

TERRAFORM_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../terraform" && pwd)"

echo "═══════════════════════════════════════════════════════════"
echo " ¿Hiciste push de tus cambios? (git status / git push)"
echo " Todo lo que no esté en GitHub o GCS se pierde con el disco."
echo "═══════════════════════════════════════════════════════════"
read -p "Continuar con la destrucción del cluster? [y/N] " confirm
if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
  echo "Cancelado."
  exit 0
fi

cd "$TERRAFORM_DIR"
terraform destroy -target=google_workstations_workstation_cluster.m5_cluster

echo ""
echo "Cluster destruido. El cargo de \$0.20/h se detiene desde ahora."
echo "Verificación opcional (no debería haber discos sueltos con DELETE):"
echo "  gcloud compute disks list --filter=\"name~workstation\" --format='table(name,sizeGb,users)'"
