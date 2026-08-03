-- Privileged PostgreSQL 16/17 provisioning for LakatoTree storage access v1.
--
-- Run once (or rerun idempotently) as a direct bootstrap superuser before the
-- signed predeploy/startup access audits.  The application migrator and its
-- NOLOGIN owner intentionally cannot perform this bootstrap-owned,
-- database-local system-catalog ACL operation.
-- This resource narrows authority only; it creates no roles or application
-- objects and grants no privilege. Run it in each target database; pg_proc ACLs
-- are database-local catalog state. Re-run the audit/provisioning step after a
-- restore, initdb, or PostgreSQL major upgrade.

BEGIN;
SET LOCAL search_path = pg_catalog;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';

DO $lakatotree_large_object_acl$
DECLARE
  server_version integer;
  direct_superuser boolean;
  public_execute_count integer;
  routine_identity text;
  expected_oids oid[];
  observed_oids oid[];
BEGIN
  server_version := current_setting('server_version_num')::integer;
  IF server_version < 160000 OR server_version >= 180000 THEN
    RAISE EXCEPTION
      'LakatoTree large-object ACL provisioning supports PostgreSQL 16/17 only';
  END IF;

  SELECT r.rolsuper AND current_user = session_user
    INTO direct_superuser
  FROM pg_catalog.pg_roles AS r
  WHERE r.rolname = current_user;
  IF direct_superuser IS DISTINCT FROM TRUE THEN
    RAISE EXCEPTION
      'LakatoTree large-object ACL provisioning requires a direct superuser session';
  END IF;
  IF current_setting('transaction_read_only')::boolean THEN
    RAISE EXCEPTION
      'LakatoTree large-object ACL provisioning requires a writable transaction';
  END IF;

  -- PostgreSQL 16 and 17 carry the same exact built-in large-object API.
  -- Bind the complete inventory before changing any ACL: a renamed, missing,
  -- replacement, or provider-added routine must not be laundered by this step.
  WITH expected(signature) AS (VALUES
    ('pg_catalog.lo_close(pg_catalog.int4)'),
    ('pg_catalog.lo_creat(pg_catalog.int4)'),
    ('pg_catalog.lo_create(pg_catalog.oid)'),
    ('pg_catalog.lo_export(pg_catalog.oid,pg_catalog.text)'),
    ('pg_catalog.lo_from_bytea(pg_catalog.oid,pg_catalog.bytea)'),
    ('pg_catalog.lo_get(pg_catalog.oid)'),
    ('pg_catalog.lo_get(pg_catalog.oid,pg_catalog.int8,pg_catalog.int4)'),
    ('pg_catalog.lo_import(pg_catalog.text)'),
    ('pg_catalog.lo_import(pg_catalog.text,pg_catalog.oid)'),
    ('pg_catalog.lo_lseek(pg_catalog.int4,pg_catalog.int4,pg_catalog.int4)'),
    ('pg_catalog.lo_lseek64(pg_catalog.int4,pg_catalog.int8,pg_catalog.int4)'),
    ('pg_catalog.lo_open(pg_catalog.oid,pg_catalog.int4)'),
    ('pg_catalog.lo_put(pg_catalog.oid,pg_catalog.int8,pg_catalog.bytea)'),
    ('pg_catalog.lo_tell(pg_catalog.int4)'),
    ('pg_catalog.lo_tell64(pg_catalog.int4)'),
    ('pg_catalog.lo_truncate(pg_catalog.int4,pg_catalog.int4)'),
    ('pg_catalog.lo_truncate64(pg_catalog.int4,pg_catalog.int8)'),
    ('pg_catalog.lo_unlink(pg_catalog.oid)'),
    ('pg_catalog.loread(pg_catalog.int4,pg_catalog.int4)'),
    ('pg_catalog.lowrite(pg_catalog.int4,pg_catalog.bytea)')
  )
  SELECT pg_catalog.array_agg(
           signature::pg_catalog.regprocedure::pg_catalog.oid
           ORDER BY signature::pg_catalog.regprocedure::pg_catalog.oid
         )
    INTO expected_oids
  FROM expected;
  SELECT pg_catalog.array_agg(p.oid ORDER BY p.oid)
    INTO observed_oids
  FROM pg_catalog.pg_proc AS p
  JOIN pg_catalog.pg_namespace AS n ON n.oid = p.pronamespace
  WHERE n.nspname = 'pg_catalog'
    AND (
      pg_catalog.left(p.proname, 3) = 'lo_'
      OR p.proname IN ('loread', 'lowrite')
    );
  IF observed_oids IS DISTINCT FROM expected_oids THEN
    RAISE EXCEPTION
      'PostgreSQL large-object routine inventory differs from the PG16/17 baseline';
  END IF;

  IF EXISTS (
    SELECT 1 FROM pg_catalog.pg_proc AS p
    WHERE p.oid = ANY(expected_oids)
      AND (
        p.oid >= 16384
        OR p.proowner <> 10
        OR p.prokind <> 'f'
        OR p.prosecdef
        OR p.proconfig IS NOT NULL
      )
  ) THEN
    RAISE EXCEPTION
      'PostgreSQL large-object routine metadata differs from the PG16/17 baseline';
  END IF;

  SELECT count(*)
    INTO public_execute_count
  FROM pg_catalog.pg_proc AS p
  JOIN pg_catalog.pg_namespace AS n ON n.oid = p.pronamespace
  CROSS JOIN LATERAL pg_catalog.aclexplode(
    COALESCE(
      p.proacl,
      pg_catalog.acldefault('f'::"char", p.proowner)
    )
  ) AS acl
  WHERE n.nspname = 'pg_catalog'
    AND (
      pg_catalog.left(p.proname, 3) = 'lo_'
      OR p.proname IN ('loread', 'lowrite')
    )
    AND acl.grantee = 0
    AND acl.privilege_type = 'EXECUTE';
  IF public_execute_count > 17 THEN
    RAISE EXCEPTION
      'unexpected PUBLIC-executable large-object routine count: %',
      public_execute_count;
  END IF;

  FOR routine_identity IN
    SELECT pg_catalog.format(
      '%I.%I(%s)',
      n.nspname,
      p.proname,
      pg_catalog.pg_get_function_identity_arguments(p.oid)
    )
    FROM pg_catalog.pg_proc AS p
    JOIN pg_catalog.pg_namespace AS n ON n.oid = p.pronamespace
    CROSS JOIN LATERAL pg_catalog.aclexplode(
      COALESCE(
        p.proacl,
        pg_catalog.acldefault('f'::"char", p.proowner)
      )
    ) AS acl
    WHERE n.nspname = 'pg_catalog'
      AND (
        pg_catalog.left(p.proname, 3) = 'lo_'
        OR p.proname IN ('loread', 'lowrite')
      )
      AND acl.grantee = 0
      AND acl.privilege_type = 'EXECUTE'
    ORDER BY p.oid
  LOOP
    EXECUTE pg_catalog.format(
      'REVOKE EXECUTE ON FUNCTION %s FROM PUBLIC',
      routine_identity
    );
  END LOOP;

  SELECT count(*)
    INTO public_execute_count
  FROM pg_catalog.pg_proc AS p
  JOIN pg_catalog.pg_namespace AS n ON n.oid = p.pronamespace
  CROSS JOIN LATERAL pg_catalog.aclexplode(
    COALESCE(
      p.proacl,
      pg_catalog.acldefault('f'::"char", p.proowner)
    )
  ) AS acl
  WHERE n.nspname = 'pg_catalog'
    AND (
      pg_catalog.left(p.proname, 3) = 'lo_'
      OR p.proname IN ('loread', 'lowrite')
    )
    AND acl.grantee = 0
    AND acl.privilege_type = 'EXECUTE';
  IF public_execute_count <> 0 THEN
    RAISE EXCEPTION
      'PUBLIC large-object EXECUTE remains after provisioning';
  END IF;
END
$lakatotree_large_object_acl$;

COMMIT;
