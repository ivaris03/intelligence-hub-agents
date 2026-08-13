#!/usr/bin/env bash
set -Eeuo pipefail

DEPLOY_PATH="${DEPLOY_PATH:-/opt/intelligence-hub-agents}"
ENV_FILE="${DEPLOY_PATH}/.env.production"
SHARED_NETWORK="ivaris-shared"
SHARED_POSTGRES_PROJECT="deploy"

cd "$DEPLOY_PATH"

if [[ ! -r "$ENV_FILE" ]]; then
    echo "Deployment env file is missing or unreadable: ${ENV_FILE}" >&2
    exit 1
fi

env_value() {
    local key="$1"
    awk -F= -v key="$key" '
        $1 == key {
            sub(/^[^=]*=/, "")
            sub(/\r$/, "")
            print
            exit
        }
    ' "$ENV_FILE"
}

database_password="$(env_value INTELLIGENCE_POSTGRES_PASSWORD)"
auth_secret_key="$(env_value AUTH_SECRET_KEY)"

if [[ -z "$database_password" ]]; then
    echo "INTELLIGENCE_POSTGRES_PASSWORD is missing" >&2
    exit 1
fi

if (( ${#auth_secret_key} < 32 )); then
    echo "AUTH_SECRET_KEY is missing or shorter than 32 characters" >&2
    exit 1
fi
unset auth_secret_key

if ! docker network inspect "$SHARED_NETWORK" >/dev/null 2>&1; then
    docker network create "$SHARED_NETWORK" >/dev/null 2>&1 || true
    docker network inspect "$SHARED_NETWORK" >/dev/null
fi

postgres_container="$({
    docker ps \
        --filter "label=com.docker.compose.project=${SHARED_POSTGRES_PROJECT}" \
        --filter "label=com.docker.compose.service=postgres" \
        --format '{{.ID}}'
} | head -n 1)"

if [[ -z "$postgres_container" ]]; then
    echo "Shared PostgreSQL container was not found" >&2
    exit 1
fi

if ! docker network inspect "$SHARED_NETWORK" \
    --format '{{range .Containers}}{{println .Name}}{{end}}' \
    | grep -Fxq "$(docker inspect --format '{{.Name}}' "$postgres_container" | sed 's#^/##')"; then
    docker network connect --alias ivaris-postgres "$SHARED_NETWORK" "$postgres_container"
fi

docker exec -i \
    -e INTELLIGENCE_POSTGRES_PASSWORD="$database_password" \
    "$postgres_container" \
    sh -lc 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d postgres -v app_password="$INTELLIGENCE_POSTGRES_PASSWORD"' <<'SQL'
SELECT format('CREATE ROLE intelligence_hub LOGIN PASSWORD %L', :'app_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'intelligence_hub')
\gexec

ALTER ROLE intelligence_hub PASSWORD :'app_password';

SELECT 'CREATE DATABASE intelligence_hub_agents OWNER intelligence_hub'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'intelligence_hub_agents')
\gexec

\connect intelligence_hub_agents
CREATE EXTENSION IF NOT EXISTS vector;
GRANT ALL ON SCHEMA public TO intelligence_hub;
SQL

compose=(docker compose --env-file "$ENV_FILE" -f compose.production.yaml)

echo "Pulling Intelligence Hub images..."
"${compose[@]}" pull

echo "Starting Intelligence Hub..."
if "${compose[@]}" up -d --remove-orphans --wait; then
    "${compose[@]}" ps
else
    status=$?
    echo "Production services failed to become healthy" >&2
    "${compose[@]}" ps --all || true
    "${compose[@]}" logs --no-color --tail 100 migrate backend || true
    exit "$status"
fi

echo "Removing dangling images..."
docker image prune -f
