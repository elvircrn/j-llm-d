#!/bin/bash
set -e

MESSAGE="$1"
BASE_URL="$2"
NAMESPACE="$3"
GRAFANA_URL="$4"

echo "Fetching full deployment configs..."

# Get available configs (try LeaderWorkerSets first, fall back to pods)
DECODE_YAML=$(kubectl get leaderworkerset wide-ep-llm-d-decode -o yaml --namespace "$NAMESPACE" 2>/dev/null || \
              kubectl get pods -l llm-d.ai/role=decode -o yaml --namespace "$NAMESPACE" 2>/dev/null || \
              echo "decode config not found")
PREFILL_YAML=$(kubectl get leaderworkerset wide-ep-llm-d-prefill -o yaml --namespace "$NAMESPACE" 2>/dev/null || \
               kubectl get pods -l llm-d.ai/role=prefill -o yaml --namespace "$NAMESPACE" 2>/dev/null || \
               echo "prefill config not found")

# Create properly escaped JSON payload with full configs
FULL_TEXT="$MESSAGE

=== DECODE CONFIG ===
$DECODE_YAML

=== PREFILL CONFIG ===
$PREFILL_YAML"

# Use jq to properly escape the JSON
ESCAPED_TEXT=$(echo "$FULL_TEXT" | jq -Rs .)

TIMESTAMP=$(date +%s)000

curl -X POST "$GRAFANA_URL/api/annotations" \
  -u "admin:admin" \
  -H "Content-Type: application/json" \
  -d "{
    \"dashboardId\": 7,
    \"panelId\": 1,
    \"time\": $TIMESTAMP,
    \"text\": $ESCAPED_TEXT
  }" \
  2>/dev/null || true