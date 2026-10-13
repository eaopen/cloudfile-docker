# Directory authority schema

`cf_dir_acl`, `cf_dir_admin` and `cf_dir_share` belong to the native Seafile
database (`SEAFILE_MYSQL_DB_SEAFILE_DB_NAME`, normally `seafile_db`). Hub policy
configuration must point to that same database. EAP never creates these tables.

The Hub versioned schema runner is their sole DDL owner. Migrations 008/009/040
create the three tables; 036/041 add pagination indexes. Do not add duplicate
definitions to Server bootstrap SQL, Django migrations or EAP SQL. Existing
migration checksums remain unchanged.

All three share UUID identifiers, SHA-256 path/subject hashes, qualified subjects
(`subject_type`, `provider`, `namespace`, `external_id`) and revision tokens.
The field types, nullability and collations are checked against the immutable
creation DDL. Each table keeps its business-specific fields:

| Table | Meaning |
| --- | --- |
| `cf_dir_acl` | Operation permission and inheritance |
| `cf_dir_admin` | Delegated administration permission and inheritance |
| `cf_dir_share` | Shared-directory discovery and default read qualification; lifecycle and creator facts |

A share never creates an ACL row. Removing it never removes an ACL. Do not add
`permission` to shares merely to make the three tables look identical.

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

The bounded command only upgrades the five directory migrations, preserving
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
