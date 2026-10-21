# 历史目录 Schema 迁移说明

> 2026-10-21 起，当前新版只确认四张新增业务表，开发期统一使用 [独立 SQL 交付](../database/README.md)。本文的 008/009/042、cf_dir_admin 及 Python apply 命令仅供对应历史版本追溯，不是新版初始化或发布入口。

# Directory authority schema

`cf_dir_acl` and `cf_dir_admin` belong to the native Seafile
database (`SEAFILE_MYSQL_DB_SEAFILE_DB_NAME`, normally `seafile_db`). Hub policy
configuration must point to that same database. EAP never creates these tables.

The Hub versioned schema runner is their sole DDL owner. Migrations 008/009 create the authority tables; 036/041 add pagination indexes.
Migration 042 adds the unified ACL columns/index and directly drops `cf_dir_share` (the independent feature was never enabled). Do not add duplicate
definitions to Server bootstrap SQL, Django migrations or EAP SQL. Existing
migration checksums remain unchanged.

Both tables use UUID identifiers, SHA-256 path/subject hashes, qualified subjects
(`subject_type`, `provider`, `namespace`, `external_id`) and revision tokens.
The field types, nullability and collations are checked against the immutable
creation DDL. Each table keeps its business-specific fields:

| Table | Meaning |
| --- | --- |
| `cf_dir_acl` | Operation permission, inheritance, sharing mode and lifecycle evidence |
| `cf_dir_admin` | Delegated administration permission and inheritance |

Sharing is an ACL attribute (`share_mode=1`), not a second grant. Compatibility
share creation creates a read ACL or enables an existing ACL without changing its
permission/inheritance. Disabling sharing retains the library ACL; deleting an
ACL revokes both. Non-members require current sharing and lifecycle evidence.

Migration 040 remains immutable for deployed schema ledgers. The unused
cf_dir_share table is dropped without importing any rows: it never
represented enabled user-facing authorizations. Existing cf_dir_acl rows
are preserved; new share_mode defaults to 0. No data merging, synthetic grant,
ID replacement or revision rotation occurs. Interrupted DDL resumes using
the canonical runner; a dropped table is not recreated.


## Release procedure

Ship matching Hub, native Server and deployment scripts before the cutover.
Run the commands inside the release container, with its normal mounted config
and `SEAFILE_MYSQL_DB_*` environment:

```sh
python3 /scripts/cloudfile-directory-schema.py plan
# Stop/drain all Hub, Server and workers using the directory tables first.
# Execute in a maintenance container; do not restart an old Server on new tables.
python3 /scripts/cloudfile-directory-schema.py apply --offline
python3 /scripts/cloudfile-directory-schema.py check
```

The command uses the native database configuration and rejects a policy-host
database mismatch. Normal startup does not perform this destructive layout
transition. `--offline` is an operator assertion, not automatic process control.

The bounded command only upgrades the six directory migrations, preserving
unrelated ledger entries. It is not a claim that the entire extension runtime
has been upgraded: use the full schema `check` and API/byte-access regression
gates before enabling a new policy host.

Empty legacy ACL/admin tables are atomically renamed to
`cf_dir_acl_legacy_v08` / `cf_dir_admin_legacy_v08`; canonical tables are then
created and recorded in the shared migration ledger. Backups are never deleted.
An interrupted operation can be rerun. Populated legacy tables, conflicting
backups, unknown layouts and checksum drift stop the operation; identity
conversion must be separately reviewed, never inferred from legacy strings.

The low-level equivalent for explicitly supplied `CLOUDFILE_DB_*` credentials:

```sh
python3 -m cloudfile_extensions.schema directory-plan
python3 -m cloudfile_extensions.schema directory-apply --offline
python3 -m cloudfile_extensions.schema directory-check
```

Existing full-schema apply now rejects incompatible directory layouts before
any DDL, rather than partially applying other migrations and failing on a
duplicate table. Missing indexes or type/collation drift fail the check; do not
mark migrations applied manually to bypass it.
