#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────
# start-session.sh — Arma el cluster de Cloud Workstations para trabajar
#
# Uso: ./start-session.sh
#
# Qué hace:
#   1. terraform apply (completo, sin -target) — como el cluster/config/
#      workstation ya fueron destruidos, Terraform solo los vuelve a crear;
#      el resto de la infra (bucket, dataset, IAM) no cambia porque ya
#      coincide con el estado deseado. Usar apply completo aquí es más
#      seguro que -target: no hay riesgo de dejar el state desincronizado.
#   2. Arranca la workstation (la VM en sí).
#   3. Imprime la URL de acceso.
#
# Tiempo estimado: 15-20 min (creación de cluster) + ~1 min (arranque VM).
# ─────────────────────────────────────────────────────────────────────────
set -euo pipefail

TERRAFORM_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../terraform" && pwd)"
CLUSTER="m5-forecast-cluster"
CONFIG="m5-forecast-config"
WORKSTATION="m5-dev-workstation"
REGION="us-central1"

echo "═══════════════════════════════════════════════════════════"
echo " 1/3 · terraform apply (recrea cluster + config + workstation)"
echo "═══════════════════════════════════════════════════════════"
cd "$TERRAFORM_DIR"
terraform apply

echo ""
echo "═══════════════════════════════════════════════════════════"
echo " 2/3 · Arrancando la workstation..."
echo "═══════════════════════════════════════════════════════════"
gcloud workstations start "$WORKSTATION" \
  --cluster="$CLUSTER" \
  --config="$CONFIG" \
  --region="$REGION"

echo ""
echo "═══════════════════════════════════════════════════════════"
echo " 3/3 · Listo. Abre la workstation con:"
echo "═══════════════════════════════════════════════════════════"
gcloud workstations describe "$WORKSTATION" \
  --cluster="$CLUSTER" \
  --config="$CONFIG" \
  --region="$REGION" \
  --format="value(host)"

cat <<'EOF'

┌─────────────────────────────────────────────────────────────┐
│ CHECKLIST post-arranque (el disco es nuevo, /home está vacío) │
├─────────────────────────────────────────────────────────────┤
│ [ ] git clone https://github.com/desareca/m5-probabilistic-forecast.git │
│ [ ] sudo apt install -y python3.12-venv                       │
│ [ ] python3.12 -m venv venv && source venv/bin/activate       │
│ [ ] pip install -r requirements.txt                            │
│ [ ] recrear .env_local (token de Kaggle) — no vive en git      │
└─────────────────────────────────────────────────────────────┘
EOF
