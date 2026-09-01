#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_COMPOSE_FILE="$SCRIPT_DIR/docker/docker-compose.yaml"
DB_COMPOSE_FILE="$SCRIPT_DIR/database/docker-compose.yaml"
ENV_FILE="$SCRIPT_DIR/.env"

if [[ ! -f "$APP_COMPOSE_FILE" ]]; then
    echo "Error: compose file not found at $APP_COMPOSE_FILE" >&2
    exit 1
fi

if [[ ! -f "$DB_COMPOSE_FILE" ]]; then
    echo "Error: compose file not found at $DB_COMPOSE_FILE" >&2
    exit 1
fi

compose_args=()
if [[ -f "$ENV_FILE" ]]; then
    compose_args+=(--env-file "$ENV_FILE")
fi

echo "Stopping application stack..."
docker compose "${compose_args[@]}" -f "$APP_COMPOSE_FILE" stop

echo "Stopping database stack..."
docker compose "${compose_args[@]}" -f "$DB_COMPOSE_FILE" stop

echo "Docker containers stopped."
