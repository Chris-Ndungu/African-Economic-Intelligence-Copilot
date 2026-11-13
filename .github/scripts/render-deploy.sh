#!/usr/bin/env bash
# Steps shared by deploy-dev.yml and deploy-prod.yml. Secrets arrive as
# environment variables and are never echoed; GitHub masks their values.
#
#   render-deploy.sh check-secrets   names of unset secrets, never values
#   render-deploy.sh previous        image ref the service runs now (stdout)
#   render-deploy.sh url             the service URL (stdout)
#   render-deploy.sh migrate <image> alembic upgrade head with <image>
#   render-deploy.sh deploy <image>  deploy hook, then wait until live (deploy id on stdout)
#   render-deploy.sh smoke           /health and /api/meta at the service URL
set -euo pipefail

API=https://api.render.com/v1
WAIT_DEPLOY_SECONDS=${WAIT_DEPLOY_SECONDS:-600}
WAIT_SMOKE_SECONDS=${WAIT_SMOKE_SECONDS:-180}

render_api() {
  curl -fsS --retry 3 -H "Authorization: Bearer ${RENDER_API_KEY}" -H "Accept: application/json" "$@"
}

check_secrets() {
  local missing=0 name
  for name in RENDER_DEPLOY_HOOK_URL RENDER_SERVICE_ID RENDER_API_KEY DATABASE_URL; do
    if [ -n "${!name:-}" ]; then
      echo "$name: set"
    else
      echo "::error::$name is not set in this GitHub Environment"
      missing=1
    fi
  done
  return $missing
}

previous_image() {
  render_api "$API/services/$RENDER_SERVICE_ID/deploys?limit=20" \
    | jq -r '[.[].deploy | select(.status == "live")][0].image.ref // empty'
}

service_url() {
  render_api "$API/services/$RENDER_SERVICE_ID" | jq -r '.serviceDetails.url'
}

migrate() {
  # The URL is passed by name so it is not on the command line.
  docker run --rm -e DATABASE_URL "$1" alembic upgrade head
}

deploy() {
  local image=$1 encoded body code id="" deadline status
  encoded=$(printf %s "$image" | jq -sRr @uri)
  body=$(mktemp)
  code=$(curl -sS -o "$body" -w '%{http_code}' -X POST "${RENDER_DEPLOY_HOOK_URL}&imgURL=${encoded}")
  case "$code" in
    200) id=$(jq -r '.deploy.id // .id // empty' "$body") ;;
    202) echo "A deploy was already running; Render queued this one." >&2 ;;
    *) echo "::error::The deploy hook answered HTTP $code" >&2; return 1 ;;
  esac
  rm -f "$body"

  deadline=$((SECONDS + WAIT_DEPLOY_SECONDS))
  while [ "$SECONDS" -lt "$deadline" ]; do
    status=$(render_api "$API/services/$RENDER_SERVICE_ID/deploys?limit=10" \
      | jq -r --arg id "$id" --arg image "$image" '
          [.[].deploy | select(if $id != "" then .id == $id else .image.ref == $image end)][0]
          | "\(.id) \(.status)"')
    id=${status%% *}
    case "${status##* }" in
      live) echo "$id"; return 0 ;;
      build_failed|update_failed|pre_deploy_failed|canceled|deactivated)
        echo "::error::Render deploy $id ended as ${status##* }" >&2; return 1 ;;
    esac
    sleep 10
  done
  echo "::error::Render deploy ${id:-unknown} was not live after ${WAIT_DEPLOY_SECONDS}s" >&2
  return 1
}

smoke() {
  local url deadline
  url=$(service_url)
  deadline=$((SECONDS + WAIT_SMOKE_SECONDS))
  while [ "$SECONDS" -lt "$deadline" ]; do
    if curl -fsS --max-time 30 "$url/health" > /dev/null \
      && [ "$(curl -fsS --max-time 30 "$url/api/meta" | jq -r .data_mode)" = "demo" ]; then
      echo "Smoke test passed at $url"
      return 0
    fi
    sleep 10
  done
  echo "::error::Smoke test failed at $url (/health must return 200 and /api/meta data_mode must be demo)" >&2
  return 1
}

cmd=${1:?usage: render-deploy.sh <command> [image]}
case "$cmd" in
  check-secrets) check_secrets ;;
  previous) previous_image ;;
  url) service_url ;;
  migrate) migrate "${2:?image}" ;;
  deploy) deploy "${2:?image}" ;;
  smoke) smoke ;;
  *) echo "unknown command: $cmd" >&2; exit 2 ;;
esac
