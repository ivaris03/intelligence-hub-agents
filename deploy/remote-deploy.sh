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

database_password="$(awk -F= '
    $1 == "INTELLIGENCE_POSTGRES_PASSWORD" {
        sub(/^[^=]*=/, "")
        sub(/\r$/, "")
        print
        exit
    }
' "$ENV_FILE")"

if [[ -z "$database_password" ]]; then
    echo "INTELLIGENCE_POSTGRES_PASSWORD is missing" >&2
    exit 1
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
"${compose[@]}" up -d --remove-orphans --wait
"${compose[@]}" ps

echo "Removing dangling images..."
docker image prune -f
