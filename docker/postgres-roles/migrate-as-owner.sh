#!/bin/sh
set -eu

fail() {
    printf 'T1-G migrator wrapper failed: %s\n' "$1" >&2
    exit 1
}

file_mode() {
    if stat -c '%a' "$1" >/dev/null 2>&1; then
        stat -c '%a' "$1"
    elif stat -f '%Lp' "$1" >/dev/null 2>&1; then
        stat -f '%Lp' "$1"
    else
        fail "cannot inspect migrator pgpass mode"
    fi
}

file_uid() {
    if stat -c '%u' "$1" >/dev/null 2>&1; then
        stat -c '%u' "$1"
    elif stat -f '%u' "$1" >/dev/null 2>&1; then
        stat -f '%u' "$1"
    else
        fail "cannot inspect migrator pgpass owner"
    fi
}

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd -P)

: "${AI_NOVEL_DB_HOST:?AI_NOVEL_DB_HOST is required}"
: "${AI_NOVEL_DB_PORT:?AI_NOVEL_DB_PORT is required}"
: "${AI_NOVEL_DB_NAME:?AI_NOVEL_DB_NAME is required}"
: "${AI_NOVEL_MIGRATOR_PGPASS_FILE:?AI_NOVEL_MIGRATOR_PGPASS_FILE is required}"

[ -z "${PGPASSWORD:-}" ] || fail "PGPASSWORD is forbidden; use the migrator pgpass file"
[ -z "${PGOPTIONS:-}" ] || fail "pre-existing PGOPTIONS is forbidden"
case "$AI_NOVEL_DB_HOST" in
    ''|*[!A-Za-z0-9._-]*) fail "AI_NOVEL_DB_HOST contains unsupported characters" ;;
esac
case "$AI_NOVEL_DB_PORT" in
    ''|*[!0-9]*) fail "AI_NOVEL_DB_PORT must be numeric" ;;
esac
case "$AI_NOVEL_DB_NAME" in
    ''|*[!a-z0-9_]*) fail "AI_NOVEL_DB_NAME must match [a-z0-9_]+" ;;
esac
[ "$AI_NOVEL_DB_PORT" -ge 1 ] 2>/dev/null && [ "$AI_NOVEL_DB_PORT" -le 65535 ] 2>/dev/null \
    || fail "AI_NOVEL_DB_PORT is outside 1..65535"
[ "${#AI_NOVEL_DB_NAME}" -le 63 ] || fail "AI_NOVEL_DB_NAME is too long"
[ ! -L "$AI_NOVEL_MIGRATOR_PGPASS_FILE" ] || fail "migrator pgpass must not be a symlink"
[ -f "$AI_NOVEL_MIGRATOR_PGPASS_FILE" ] || fail "migrator pgpass must be a regular file"
[ "$(file_mode "$AI_NOVEL_MIGRATOR_PGPASS_FILE")" = 600 ] \
    || fail "migrator pgpass mode must be 0600"
[ "$(file_uid "$AI_NOVEL_MIGRATOR_PGPASS_FILE")" = "$(id -u)" ] \
    || fail "migrator process must own its pgpass file"

export PGPASSFILE=$AI_NOVEL_MIGRATOR_PGPASS_FILE
export PGOPTIONS='-c role=ai_novel_schema_owner -c search_path=public,pg_catalog'
export AI_NOVEL_DATABASE_URL="postgresql+psycopg://ai_novel_migrator@${AI_NOVEL_DB_HOST}:${AI_NOVEL_DB_PORT}/${AI_NOVEL_DB_NAME}"

cd "$PROJECT_ROOT"
if [ -x "$PROJECT_ROOT/.venv/bin/python" ]; then
    PYTHON_EXECUTABLE=$PROJECT_ROOT/.venv/bin/python
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_EXECUTABLE=$(command -v python3)
else
    fail "a Python 3.11-compatible interpreter is required"
fi

if [ "$#" -eq 0 ]; then
    set -- upgrade head
fi
exec "$PYTHON_EXECUTABLE" -m alembic -c "$PROJECT_ROOT/alembic.ini" "$@"
