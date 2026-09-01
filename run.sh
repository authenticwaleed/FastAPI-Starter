#!/usr/bin/env bash
#
# Baton — bring the API up with one command.
#
#   ./run.sh            migrate to head, then serve
#   ./run.sh --reset    rebuild the database from empty first, then the above
#   PORT=8001 ./run.sh  serve somewhere other than 8000
#
# --reset drops the database. It exists because a database stamped at a
# revision that no longer has a file cannot be migrated forward, and that
# is only escapable by starting again. It is not the default for the
# obvious reason.

set -euo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-8000}"

if [ ! -f .env ]; then
    echo "run.sh: no .env here. Copy the example and give it a signing key:" >&2
    echo "  cp .env.example .env" >&2
    echo "  python -c 'import secrets; print(secrets.token_urlsafe(32))'  # -> JWT_SECRET_KEY" >&2
    exit 1
fi

uv sync --quiet

# The connection is configured in exactly one place, DATABASE_URL. Read it
# back out through the application's own settings rather than parsing .env
# a second time here, so this script cannot disagree with what the app will
# actually connect to.
eval "$(uv run python <<'PY'
from app.core.config import get_settings

url = get_settings().database_url
# PostgresDsn is a MultiHostUrl, because a Postgres URL is allowed to carry
# several hosts for failover. This application connects to one, so take it.
host = url.hosts()[0]
print(f'DB_NAME={url.path.lstrip("/")}')
print(f'DB_HOST={host["host"]}')
print(f'DB_PORT={host["port"] or 5432}')
print(f'DB_USER={host["username"]}')
print(f'export PGPASSWORD={host["password"] or ""}')
PY
)"

# Free the port first. A server left over from a previous run makes uvicorn
# exit with a bind error that reads like a fault in the application, and it
# would also hold the connections that the drop below has to wait on.
lsof -ti:"$PORT" -sTCP:LISTEN 2>/dev/null | xargs -r kill || true
sleep 1

# Anything still holding the port belongs to another user, so this script
# cannot clear it. Stop here and say why. The check is before the rebuild
# below deliberately: failing at the end instead means uvicorn reports
# "Address already in use" only after the database has been dropped and
# remigrated, which is a long way to travel to learn the port was busy.
if ss -ltn "sport = :$PORT" 2>/dev/null | grep -q ":$PORT"; then
    echo "run.sh: port $PORT is held by a process this script cannot kill." >&2
    echo "  identify it:  sudo ss -ltnp 'sport = :$PORT'" >&2
    echo "  or serve elsewhere:  PORT=8001 $0 ${1:-}" >&2
    exit 1
fi

if [ "${1:-}" = "--reset" ]; then
    echo "==> rebuilding $DB_NAME"
    # --force disconnects whatever is still attached (PostgreSQL 13+).
    dropdb -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" --if-exists --force "$DB_NAME"
    createdb -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" "$DB_NAME"
fi

echo "==> migrating $DB_NAME to head"
uv run alembic upgrade head

echo "==> serving on http://localhost:$PORT/docs"
exec uv run uvicorn app.main:app --reload --port "$PORT"
