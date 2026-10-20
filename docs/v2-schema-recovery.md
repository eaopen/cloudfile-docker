# CloudFile V2 database contract and DEV upload recovery

Current branch: **dev = V2**, no extra V2-named feature branches or repeated full builds.
This document describes the **current V2 contract**, not the historical
v0.x/v0.9 migrations in `cloudfile_extensions/schema/migrations/001..042`.

## What failed

- DEV Go fileserver observed SQL **1176** for
  `cf_edit_guard FORCE INDEX(cf_edit_guard_active)`, followed by repeated
  final Branch commits. This is a deterministic schema error, not ordinary
  concurrent uploads.
- The old `029_editing_core` creates `cf_edit_guard(resource_uid,
  lifecycle_ref, lease_until, ...)`. Current V2 requires
  `cf_edit_guard(repo_id, path_hash BINARY(32), path, lease_expires_at, ...)`
  and `cf_edit_guard_active(repo_id,guard_id)`. Merely adding an index does
  not repair the data model.
- The old `008/042` ACL and `006/007` group-map migrations also conflict
  with the current three-table V2 model.
- Old Docker bootstrap and fresh-install path invoked legacy DDL. They now
  use only `cloudfile-v2.sql` and optional `cloudfile-v2-edit.sql` on **new**
  volumes; existing volumes never upgrade automatically.
- Go Branch retries only true HEAD conflicts. Guard/ACL/SQL/layout errors
  propagate immediately and do not write new Branch pointers.

## Canonical current V2 tables

| Area | Required schema | Ownership |
| --- | --- | --- |
| Library storage | `cf_library_storage` | V2 native storage |
| Directory ACL, including `share_mode` | `cf_dir_acl`, binary SHA-256 path hash | Hub V2 authority |
| UID, organization and role group projection | `cf_sso_group_map` | Hub V2 identity |
| Optional Checkout/local editing | `cf_edit_guard`, one Guard row/path, `cf_edit_guard_active` | current V2 Guard |

Core: **three** extension tables. With Checkout: **four**. Do not create
`cf_resource`, `cf_commit_intent`, `cf_edit_session` or
`cf_schema_migration` as a prerequisite for current V2.

The final Go/C Guard checks preserve the lock and fail closed; a corrupt
Guard is **not** treated as absent, and is not disabled to restore uploads.

## DEV preflight (read-only, no build)

Run within the matching release container with existing
`SEAFILE_MYSQL_DB_*` environment. No credentials are printed:

```sh
python3 /scripts/cloudfile-v2-schema.py plan
python3 /scripts/cloudfile-v2-schema.py check
```

The first command returns table states and **all extra `cf_*` table names**.
The second exits non-zero when current V2 cannot be established. Both use
`information_schema` SELECT only and never issue CREATE/ALTER/DROP,
change schema ledgers or inspect user content.

After confirming the exact database and that the table exists, optionally
count active checkout reservations with a **read-only query**:

```sql
SELECT COUNT(*) AS active_guard_rows
FROM cf_edit_guard
WHERE guard_id IS NOT NULL;
```

Run that query only after verifying the `guard_id` column exists; active
records, nonzero generations and foreign resource references must be
preserved. Never infer that expired rows or an empty current session
automatically make a legacy Guard safe to destroy.

## Recovery of an existing DEV or production volume

1. Freeze writes and capture the **deployed image digest/source receipt**, the
   native database name, `SHOW CREATE TABLE` for every existing `cf_*`
   table, the current migration ledger and Guard active/row counts.
2. Back up MariaDB (including Seafile's Branch/Repo metadata), ccnet/seahub,
   `/shared/seafile` and any object storage. Confirm recovery before DDL.
3. Categorize **each** table as current, legacy, missing, or incompatible.
   A mixed legacy `cf_dir_acl` / group-map / Guard layout is not a normal
   additive upgrade. Do **not** turn a 1176 into silent authorization.
4. Prepare an explicit, reviewed **offline** data migration for the actual
   snapshot. Preserve original tables in separately named backups and map
   old resource UID/lifecycle rows to canonical path and binary hash only
   with confirmed identity, collision and generation checks. Stop on
   ambiguous, active or orphaned records. Never issue an unconditional
   `DROP TABLE`, truncate Guard, reset generations, mark old migrations
   applied, or use `ALTER ADD INDEX` as the entire fix.
5. After migration, restart the matching Server/Hub/fileserver images
   together; the Go fileserver must report a **current Guard layout** on
   startup. Retry only real concurrent Branch conflicts.
6. Validate one small file with a normal Etech user and then a directory-only
   `rw` shared user: upload link, bytes, final Branch commit, download,
   rename, effective read/write, revoke, and root/sibling denial. Confirm
   that neither ACL/Guard errors nor EXDEV storage staging errors recur.

**No automatic legacy-to-V2 data migration is intentionally provided.**
The correct transformation depends on the live data, active reservations,
native library/group mappings and rollback evidence, which cannot be
deduced from the three GitHub source repositories.

## Limited cost verification

- Go: targeted `TestCFV2GuardSchemaContract` and
  `TestCFUploadRetriesOnlyHeadConflict`; C file-lock source now targets the
  current one-table Guard.
- Hub: `test_schema_inventory.py`, pure metadata classification without a
  database.
- Docker: `test_fresh_schema.py`, `test_v2_schema_inventory_command.py`.
- PRs use quick static source checks; do not automatically run expensive
  full C/Go builds, migration/recovery scripts or full E2E on every edit.
