\set ON_ERROR_STOP on
\set ECHO none
\set QUIET on

-- Passwords are read by the psql client from the three isolated pgpass mounts.
-- They are never supplied through argv, a database URL, or stdout.
\set migrator_password `awk -F: 'NR == 1 { print $5 }' /run/ai-novel-db-auth/migrator/.pgpass`
\set api_password `awk -F: 'NR == 1 { print $5 }' /run/ai-novel-db-auth/api/.pgpass`
\set worker_password `awk -F: 'NR == 1 { print $5 }' /run/ai-novel-db-auth/worker/.pgpass`

BEGIN;
SET LOCAL client_min_messages = warning;
SET LOCAL password_encryption = 'scram-sha-256';
SELECT pg_catalog.set_config('ai_novel.bootstrap_expected_database', :'expected_database', true);
SELECT pg_catalog.set_config('ai_novel.bootstrap_expected_admin_role', :'expected_admin_role', true);

DO $bootstrap$
BEGIN
    IF current_database() <> current_setting('ai_novel.bootstrap_expected_database') THEN
        RAISE EXCEPTION 'database identity mismatch';
    END IF;
    IF session_user <> current_setting('ai_novel.bootstrap_expected_admin_role')
       OR current_user <> current_setting('ai_novel.bootstrap_expected_admin_role') THEN
        RAISE EXCEPTION 'bootstrap admin identity mismatch';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_roles
        WHERE rolname = current_user AND rolsuper
    ) THEN
        RAISE EXCEPTION 'bootstrap admin must be a PostgreSQL superuser';
    END IF;
END
$bootstrap$;

-- pgvector is an administrator-provisioned extension.  The application
-- migrations use CREATE EXTENSION IF NOT EXISTS, so pre-provisioning lets the
-- unprivileged migrator execute the complete Alembic chain under SET ROLE.
CREATE EXTENSION IF NOT EXISTS vector;

DO $bootstrap$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'ai_novel_schema_owner') THEN
        CREATE ROLE ai_novel_schema_owner;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'ai_novel_migrator') THEN
        CREATE ROLE ai_novel_migrator;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'ai_novel_api') THEN
        CREATE ROLE ai_novel_api;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'ai_novel_worker') THEN
        CREATE ROLE ai_novel_worker;
    END IF;
END
$bootstrap$;

ALTER ROLE ai_novel_schema_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOINHERIT NOREPLICATION NOBYPASSRLS;
ALTER ROLE ai_novel_migrator LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOINHERIT NOREPLICATION NOBYPASSRLS CONNECTION LIMIT -1 VALID UNTIL 'infinity';
ALTER ROLE ai_novel_api LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOINHERIT NOREPLICATION NOBYPASSRLS CONNECTION LIMIT -1 VALID UNTIL 'infinity';
ALTER ROLE ai_novel_worker LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOINHERIT NOREPLICATION NOBYPASSRLS CONNECTION LIMIT -1 VALID UNTIL 'infinity';

ALTER ROLE ai_novel_schema_owner RESET ALL;
ALTER ROLE ai_novel_migrator RESET ALL;
ALTER ROLE ai_novel_api RESET ALL;
ALTER ROLE ai_novel_worker RESET ALL;

-- Remove any pre-existing privilege-bearing memberships before installing the
-- single allowed edge.  This also repairs a partially configured prior run.
SELECT pg_catalog.format(
           'REVOKE %I FROM %I', granted.rolname, member_role.rolname
       )
FROM pg_catalog.pg_auth_members membership
JOIN pg_catalog.pg_roles granted ON granted.oid = membership.roleid
JOIN pg_catalog.pg_roles member_role ON member_role.oid = membership.member
WHERE member_role.rolname IN (
          'ai_novel_schema_owner', 'ai_novel_migrator', 'ai_novel_api', 'ai_novel_worker'
      )
   OR granted.rolname IN (
          'ai_novel_schema_owner', 'ai_novel_migrator', 'ai_novel_api', 'ai_novel_worker'
      )
\gexec

GRANT ai_novel_schema_owner TO ai_novel_migrator
    WITH INHERIT FALSE, SET TRUE, ADMIN FALSE;

SELECT pg_catalog.format(
           'ALTER ROLE ai_novel_migrator PASSWORD %L', :'migrator_password'
       )
\gexec
SELECT pg_catalog.format(
           'ALTER ROLE ai_novel_api PASSWORD %L', :'api_password'
       )
\gexec
SELECT pg_catalog.format(
           'ALTER ROLE ai_novel_worker PASSWORD %L', :'worker_password'
       )
\gexec

ALTER ROLE ai_novel_schema_owner SET search_path TO pg_catalog, public;
ALTER ROLE ai_novel_migrator SET search_path TO pg_catalog, public;
ALTER ROLE ai_novel_api SET search_path TO pg_catalog, public;
ALTER ROLE ai_novel_worker SET search_path TO pg_catalog, public;

SELECT pg_catalog.format(
           'ALTER DATABASE %I OWNER TO ai_novel_schema_owner', current_database()
       )
\gexec
SELECT pg_catalog.format(
           'REVOKE ALL PRIVILEGES ON DATABASE %I FROM PUBLIC', current_database()
       )
\gexec
SELECT pg_catalog.format(
           'GRANT CONNECT ON DATABASE %I TO ai_novel_migrator, ai_novel_api, ai_novel_worker',
           current_database()
       )
\gexec

ALTER SCHEMA public OWNER TO ai_novel_schema_owner;
REVOKE ALL PRIVILEGES ON SCHEMA public FROM PUBLIC;
GRANT ALL PRIVILEGES ON SCHEMA public TO ai_novel_schema_owner;
GRANT USAGE ON SCHEMA public TO ai_novel_migrator, ai_novel_api, ai_novel_worker;

-- Transfer every non-extension application relation/routine/type in public.
-- Extension members remain administrator-provisioned external objects.
SELECT pg_catalog.format(
           CASE relation.relkind
               WHEN 'r' THEN 'ALTER TABLE %I.%I OWNER TO ai_novel_schema_owner'
               WHEN 'p' THEN 'ALTER TABLE %I.%I OWNER TO ai_novel_schema_owner'
               WHEN 'S' THEN 'ALTER SEQUENCE %I.%I OWNER TO ai_novel_schema_owner'
               WHEN 'v' THEN 'ALTER VIEW %I.%I OWNER TO ai_novel_schema_owner'
               WHEN 'm' THEN 'ALTER MATERIALIZED VIEW %I.%I OWNER TO ai_novel_schema_owner'
               WHEN 'f' THEN 'ALTER FOREIGN TABLE %I.%I OWNER TO ai_novel_schema_owner'
           END,
           namespace.nspname,
           relation.relname
       )
FROM pg_catalog.pg_class relation
JOIN pg_catalog.pg_namespace namespace ON namespace.oid = relation.relnamespace
WHERE namespace.nspname = 'public'
  AND relation.relkind IN ('r', 'p', 'S', 'v', 'm', 'f')
  AND relation.relowner <> (SELECT oid FROM pg_catalog.pg_roles WHERE rolname = 'ai_novel_schema_owner')
  AND NOT EXISTS (
      SELECT 1
      FROM pg_catalog.pg_depend dependency
      WHERE dependency.classid = 'pg_catalog.pg_class'::pg_catalog.regclass
        AND dependency.objid = relation.oid
        AND dependency.deptype = 'e'
  )
ORDER BY namespace.nspname, relation.relname
\gexec

SELECT pg_catalog.format(
           'ALTER ROUTINE %I.%I(%s) OWNER TO ai_novel_schema_owner',
           namespace.nspname,
           routine.proname,
           pg_catalog.pg_get_function_identity_arguments(routine.oid)
       )
FROM pg_catalog.pg_proc routine
JOIN pg_catalog.pg_namespace namespace ON namespace.oid = routine.pronamespace
WHERE namespace.nspname = 'public'
  AND routine.proowner <> (SELECT oid FROM pg_catalog.pg_roles WHERE rolname = 'ai_novel_schema_owner')
  AND NOT EXISTS (
      SELECT 1
      FROM pg_catalog.pg_depend dependency
      WHERE dependency.classid = 'pg_catalog.pg_proc'::pg_catalog.regclass
        AND dependency.objid = routine.oid
        AND dependency.deptype = 'e'
  )
ORDER BY namespace.nspname, routine.proname, routine.oid
\gexec

SELECT pg_catalog.format(
           'ALTER TYPE %I.%I OWNER TO ai_novel_schema_owner',
           namespace.nspname,
           type_entry.typname
       )
FROM pg_catalog.pg_type type_entry
JOIN pg_catalog.pg_namespace namespace ON namespace.oid = type_entry.typnamespace
WHERE namespace.nspname = 'public'
  AND type_entry.typtype IN ('d', 'e', 'm', 'r')
  AND type_entry.typelem = 0
  AND type_entry.typowner <> (SELECT oid FROM pg_catalog.pg_roles WHERE rolname = 'ai_novel_schema_owner')
  AND NOT EXISTS (
      SELECT 1
      FROM pg_catalog.pg_depend dependency
      WHERE dependency.classid = 'pg_catalog.pg_type'::pg_catalog.regclass
        AND dependency.objid = type_entry.oid
        AND dependency.deptype = 'e'
  )
ORDER BY namespace.nspname, type_entry.typname
\gexec

-- Existing object ACLs: PUBLIC and runtime roles receive no implicit routine
-- execution or mutation rights.  API and worker both remain read-only until
-- audited stored procedures (or an equivalent narrow adapter) exist.
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public
    FROM PUBLIC, ai_novel_migrator, ai_novel_api, ai_novel_worker;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public
    FROM PUBLIC, ai_novel_migrator, ai_novel_api, ai_novel_worker;
REVOKE ALL PRIVILEGES ON ALL ROUTINES IN SCHEMA public
    FROM PUBLIC, ai_novel_migrator, ai_novel_api, ai_novel_worker;
GRANT EXECUTE ON ALL ROUTINES IN SCHEMA public TO ai_novel_schema_owner;

SELECT pg_catalog.format(
           'REVOKE ALL PRIVILEGES ON TYPE %I.%I '
           'FROM PUBLIC, ai_novel_migrator, ai_novel_api, ai_novel_worker',
           namespace.nspname,
           type_entry.typname
       )
FROM pg_catalog.pg_type type_entry
JOIN pg_catalog.pg_namespace namespace ON namespace.oid = type_entry.typnamespace
WHERE namespace.nspname = 'public'
  AND type_entry.typtype IN ('b', 'd', 'e', 'm', 'r')
  AND type_entry.typelem = 0
ORDER BY namespace.nspname, type_entry.typname
\gexec

GRANT SELECT ON ALL TABLES IN SCHEMA public TO ai_novel_api, ai_novel_worker;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO ai_novel_api;
SELECT pg_catalog.format(
           'GRANT USAGE ON TYPE %I.%I '
           'TO ai_novel_schema_owner, ai_novel_migrator, ai_novel_api, ai_novel_worker',
           namespace.nspname,
           type_entry.typname
       )
FROM pg_catalog.pg_type type_entry
JOIN pg_catalog.pg_namespace namespace ON namespace.oid = type_entry.typnamespace
WHERE namespace.nspname = 'public'
  AND type_entry.typtype IN ('b', 'd', 'e', 'm', 'r')
  AND type_entry.typelem = 0
ORDER BY namespace.nspname, type_entry.typname
\gexec

CREATE TEMPORARY TABLE ai_novel_protected_tables (
    table_name pg_catalog.name PRIMARY KEY
) ON COMMIT DROP;
\ir protected-tables.sql

SELECT pg_catalog.format(
           'REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER '
           'ON TABLE %I.%I FROM ai_novel_api, ai_novel_worker',
           namespace.nspname,
           relation.relname
       )
FROM pg_temp.ai_novel_protected_tables protected
JOIN pg_catalog.pg_class relation ON relation.relname = protected.table_name
JOIN pg_catalog.pg_namespace namespace ON namespace.oid = relation.relnamespace
WHERE namespace.nspname = 'public'
  AND relation.relkind IN ('r', 'p')
ORDER BY protected.table_name
\gexec

-- Future objects are fail-closed: SELECT/type use is available, but API DML and
-- all routine EXECUTE require a subsequent audited bootstrap/grant decision.
ALTER DEFAULT PRIVILEGES FOR ROLE ai_novel_schema_owner IN SCHEMA public
    REVOKE ALL PRIVILEGES ON TABLES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE ai_novel_schema_owner IN SCHEMA public
    GRANT SELECT ON TABLES TO ai_novel_api, ai_novel_worker;
ALTER DEFAULT PRIVILEGES FOR ROLE ai_novel_schema_owner IN SCHEMA public
    REVOKE ALL PRIVILEGES ON SEQUENCES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE ai_novel_schema_owner IN SCHEMA public
    GRANT SELECT ON SEQUENCES TO ai_novel_api;
-- PostgreSQL's built-in PUBLIC EXECUTE/USAGE defaults are global defaults;
-- schema-local REVOKE cannot subtract them.  Revoke globally for the owner,
-- then add only the schema-local grants listed above/below.
ALTER DEFAULT PRIVILEGES FOR ROLE ai_novel_schema_owner
    REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE ai_novel_schema_owner
    REVOKE ALL PRIVILEGES ON TYPES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE ai_novel_schema_owner IN SCHEMA public
    GRANT USAGE ON TYPES TO ai_novel_migrator, ai_novel_api, ai_novel_worker;

-- Defense in depth if somebody accidentally creates an object without the
-- required SET ROLE.  Such ownership is still rejected by validation.
ALTER DEFAULT PRIVILEGES FOR ROLE ai_novel_migrator IN SCHEMA public
    REVOKE ALL PRIVILEGES ON TABLES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE ai_novel_migrator IN SCHEMA public
    REVOKE ALL PRIVILEGES ON SEQUENCES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE ai_novel_migrator
    REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE ai_novel_migrator
    REVOKE ALL PRIVILEGES ON TYPES FROM PUBLIC;

-- No SECURITY DEFINER routine is introduced here.  If one already exists, it
-- must be fully schema-qualified and have an explicitly empty search_path.
DO $bootstrap$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_proc routine
        JOIN pg_catalog.pg_namespace namespace ON namespace.oid = routine.pronamespace
        WHERE namespace.nspname = 'public'
          AND routine.prosecdef
          AND NOT EXISTS (
              SELECT 1
              FROM pg_catalog.unnest(COALESCE(routine.proconfig, ARRAY[]::text[])) setting
              WHERE setting IN ('search_path=', 'search_path=""')
          )
    ) THEN
        RAISE EXCEPTION 'unsafe SECURITY DEFINER routine in public schema';
    END IF;
END
$bootstrap$;

COMMIT;

\unset migrator_password
\unset api_password
\unset worker_password
