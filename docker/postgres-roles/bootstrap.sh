#!/bin/sh
set -eu

umask 077

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
MIGRATOR_PGPASS=/run/ai-novel-db-auth/migrator/.pgpass
API_PGPASS=/run/ai-novel-db-auth/api/.pgpass
WORKER_PGPASS=/run/ai-novel-db-auth/worker/.pgpass

fail() {
    printf 'T1-G role bootstrap failed: %s\n' "$1" >&2
    exit 1
}

require_value() {
    variable_name=$1
    eval "variable_value=\${$variable_name-}"
    [ -n "$variable_value" ] || fail "$variable_name is required"
}

require_identifier() {
    value=$1
    label=$2
    case "$value" in
        ''|*[!a-z0-9_]*) fail "$label must match [a-z0-9_]+" ;;
    esac
    [ "${#value}" -le 63 ] || fail "$label exceeds PostgreSQL identifier length"
}

require_host() {
    value=$1
    case "$value" in
        ''|*[!A-Za-z0-9._-]*) fail "runtime host contains unsupported characters" ;;
    esac
}

require_port() {
    value=$1
    case "$value" in
        ''|*[!0-9]*) fail "port must be numeric" ;;
    esac
    [ "$value" -ge 1 ] 2>/dev/null && [ "$value" -le 65535 ] 2>/dev/null \
        || fail "port is outside 1..65535"
}

require_numeric_id() {
    value=$1
    label=$2
    case "$value" in
        ''|*[!0-9]*) fail "$label must be a non-negative integer" ;;
    esac
}

file_mode() {
    if stat -c '%a' "$1" >/dev/null 2>&1; then
        stat -c '%a' "$1"
    elif stat -f '%Lp' "$1" >/dev/null 2>&1; then
        stat -f '%Lp' "$1"
    else
        fail "cannot inspect file mode"
    fi
}

file_owner() {
    if stat -c '%u:%g' "$1" >/dev/null 2>&1; then
        stat -c '%u:%g' "$1"
    elif stat -f '%u:%g' "$1" >/dev/null 2>&1; then
        stat -f '%u:%g' "$1"
    else
        fail "cannot inspect file owner"
    fi
}

prepare_directory() {
    directory=$1
    target_uid=$2
    target_gid=$3
    [ ! -L "$directory" ] || fail "pgpass directory must not be a symlink"
    mkdir -p -- "$directory"
    [ -d "$directory" ] || fail "pgpass parent is not a directory"
    mountpoint -q "$directory" || fail "each runtime pgpass directory must be an independent mountpoint"
    chmod 0700 "$directory"
    if [ "$(id -u)" -eq 0 ]; then
        chown "$target_uid:$target_gid" "$directory"
    else
        [ "$(id -u)" -eq "$target_uid" ] \
            || fail "bootstrap must run as root or the target pgpass owner"
    fi
}

validate_pgpass() {
    path=$1
    expected_host=$2
    expected_port=$3
    expected_database=$4
    expected_role=$5

    [ ! -L "$path" ] || fail "pgpass file must not be a symlink"
    [ -f "$path" ] || fail "pgpass path must be a regular file"
    [ "$(file_mode "$path")" = 600 ] || fail "pgpass mode must be 0600"
    [ "$(wc -l < "$path" | tr -d ' ')" = 1 ] || fail "pgpass must contain exactly one record"

    IFS=: read -r record_host record_port record_database record_role record_password record_extra < "$path"
    [ "$record_host" = "$expected_host" ] || fail "pgpass host mismatch"
    [ "$record_port" = "$expected_port" ] || fail "pgpass port mismatch"
    [ "$record_database" = "$expected_database" ] || fail "pgpass database mismatch"
    [ "$record_role" = "$expected_role" ] || fail "pgpass role mismatch"
    [ -z "${record_extra:-}" ] || fail "pgpass record has extra fields"
    [ "${#record_password}" -eq 64 ] || fail "generated role password must be 32 bytes"
    case "$record_password" in
        *[!0-9a-f]*) fail "generated role password encoding is invalid" ;;
    esac
    unset record_password
}

ensure_pgpass() {
    path=$1
    expected_role=$2
    target_uid=$3
    target_gid=$4
    parent_directory=$(dirname -- "$path")

    prepare_directory "$parent_directory" "$target_uid" "$target_gid"
    if [ ! -e "$path" ]; then
        temporary_path="$path.bootstrap.$$"
        [ ! -e "$temporary_path" ] || fail "temporary pgpass path already exists"
        {
            printf '%s:%s:%s:%s:' \
                "$AI_NOVEL_RUNTIME_PGHOST" \
                "$AI_NOVEL_RUNTIME_PGPORT" \
                "$AI_NOVEL_EXPECTED_DATABASE" \
                "$expected_role"
            od -An -N32 -tx1 /dev/urandom | tr -d ' \n'
            printf '\n'
        } > "$temporary_path"
        chmod 0600 "$temporary_path"
        if [ "$(id -u)" -eq 0 ]; then
            chown "$target_uid:$target_gid" "$temporary_path"
        fi
        mv -- "$temporary_path" "$path"
    fi
    validate_pgpass \
        "$path" \
        "$AI_NOVEL_RUNTIME_PGHOST" \
        "$AI_NOVEL_RUNTIME_PGPORT" \
        "$AI_NOVEL_EXPECTED_DATABASE" \
        "$expected_role"
    [ "$(file_owner "$parent_directory")" = "$target_uid:$target_gid" ] \
        || fail "pgpass directory owner mismatch"
    [ "$(file_owner "$path")" = "$target_uid:$target_gid" ] \
        || fail "pgpass file owner mismatch"
}

command -v psql >/dev/null 2>&1 || fail "psql is required"
command -v od >/dev/null 2>&1 || fail "od is required"
command -v stat >/dev/null 2>&1 || fail "stat is required"
command -v mountpoint >/dev/null 2>&1 || fail "mountpoint is required"

[ -z "${PGPASSWORD:-}" ] || fail "PGPASSWORD is forbidden; use the admin PGPASSFILE"
require_value PGHOST
require_value PGPORT
require_value PGDATABASE
require_value PGUSER
require_value PGPASSFILE
require_value AI_NOVEL_EXPECTED_DATABASE
require_value AI_NOVEL_EXPECTED_ADMIN_ROLE
require_value AI_NOVEL_ROLE_BOOTSTRAP_CONFIRM
require_value AI_NOVEL_RUNTIME_PGHOST
require_value AI_NOVEL_RUNTIME_PGPORT
require_value AI_NOVEL_MIGRATOR_UID
require_value AI_NOVEL_MIGRATOR_GID
require_value AI_NOVEL_API_UID
require_value AI_NOVEL_API_GID
require_value AI_NOVEL_WORKER_UID
require_value AI_NOVEL_WORKER_GID

require_identifier "$AI_NOVEL_EXPECTED_DATABASE" AI_NOVEL_EXPECTED_DATABASE
require_identifier "$AI_NOVEL_EXPECTED_ADMIN_ROLE" AI_NOVEL_EXPECTED_ADMIN_ROLE
require_host "$AI_NOVEL_RUNTIME_PGHOST"
require_port "$PGPORT"
require_port "$AI_NOVEL_RUNTIME_PGPORT"
require_numeric_id "$AI_NOVEL_MIGRATOR_UID" AI_NOVEL_MIGRATOR_UID
require_numeric_id "$AI_NOVEL_MIGRATOR_GID" AI_NOVEL_MIGRATOR_GID
require_numeric_id "$AI_NOVEL_API_UID" AI_NOVEL_API_UID
require_numeric_id "$AI_NOVEL_API_GID" AI_NOVEL_API_GID
require_numeric_id "$AI_NOVEL_WORKER_UID" AI_NOVEL_WORKER_UID
require_numeric_id "$AI_NOVEL_WORKER_GID" AI_NOVEL_WORKER_GID

[ "$PGDATABASE" = "$AI_NOVEL_EXPECTED_DATABASE" ] || fail "PGDATABASE does not match the expected database"
[ "$PGUSER" = "$AI_NOVEL_EXPECTED_ADMIN_ROLE" ] || fail "PGUSER does not match the expected admin"
[ "$AI_NOVEL_ROLE_BOOTSTRAP_CONFIRM" = "$AI_NOVEL_EXPECTED_DATABASE:$AI_NOVEL_EXPECTED_ADMIN_ROLE" ] \
    || fail "AI_NOVEL_ROLE_BOOTSTRAP_CONFIRM mismatch"

[ ! -L "$PGPASSFILE" ] || fail "admin pgpass must not be a symlink"
[ -f "$PGPASSFILE" ] || fail "admin PGPASSFILE must be a regular file"
[ "$(file_mode "$PGPASSFILE")" = 600 ] || fail "admin PGPASSFILE mode must be 0600"

actual_identity=$(psql -X -q -A -t -v ON_ERROR_STOP=1 \
    -c "SELECT current_database() || ':' || session_user || ':' || current_user")
[ "$actual_identity" = "$AI_NOVEL_EXPECTED_DATABASE:$AI_NOVEL_EXPECTED_ADMIN_ROLE:$AI_NOVEL_EXPECTED_ADMIN_ROLE" ] \
    || fail "live database/admin identity mismatch"
unset actual_identity

ensure_pgpass "$MIGRATOR_PGPASS" ai_novel_migrator "$AI_NOVEL_MIGRATOR_UID" "$AI_NOVEL_MIGRATOR_GID"
ensure_pgpass "$API_PGPASS" ai_novel_api "$AI_NOVEL_API_UID" "$AI_NOVEL_API_GID"
ensure_pgpass "$WORKER_PGPASS" ai_novel_worker "$AI_NOVEL_WORKER_UID" "$AI_NOVEL_WORKER_GID"

psql -X -q -v ON_ERROR_STOP=1 \
    -v expected_database="$AI_NOVEL_EXPECTED_DATABASE" \
    -v expected_admin_role="$AI_NOVEL_EXPECTED_ADMIN_ROLE" \
    -f "$SCRIPT_DIR/bootstrap.sql" >/dev/null

printf 'T1-G database-role bootstrap complete: database=%s roles=4\n' \
    "$AI_NOVEL_EXPECTED_DATABASE"
