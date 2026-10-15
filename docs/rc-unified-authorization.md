# v0.9 RC: Unified Default Authorization (Blocking Contract)

Status: P0 NOT IMPLEMENTED. This document is a release acceptance contract, not a claim of completed work.

## Product invariants

- There is exactly one CloudFile authorization capability. Etech and any other application keep their existing Seafile session/OAuth/OIDC and ordinary file API contracts without selecting an authorization mode or passing new flags.
- Management permission and content permission remain separate. system_admin has an implicit all-library rw baseline but still obeys directory ACL and hard read-only; daily_admin never gets implicit cross-library content rw.
- Current cf_dir_acl plus share_mode is the only current directory grant store. Retired cf_dir_share rows are NOT migrated to ACL. The 042 migration drops the table directly (Hub 720a622; Docker 491f9ff).

## Verified blocker

2026-10-15 DEV evidence records that once any ACL enrolls a repository into cf_managed_library, legacy FileServer upload/download and native write paths are refused (403). Deleting that ACL does not undo the managed status. This is intentional fail-closed behavior, not a cache bug.

Relevant native guards: common/cf-acl.c, server/cloudfile-policy.c (cf_policy_check_legacy_library), fileserver/fileop.go (legacyLibraryAllowed), and common/branch-mgr.c final publication. The legacy FileServer token does not automatically carry a verified v0.9 subject epoch, session proof, scoped path grant, or transaction-level revocation check.

## Safe implementation order

1. At existing authenticated Seafile API entrypoints, resolve the actual native account and trusted OAuth/OIDC/Seafile session or token. NEVER accept client-asserted userId or mode.
2. Transparently issue and consume a server-owned managed transfer authorization at the existing file API/URL boundary. At the native final gate, revalidate current account, repo, path, directory ACL/share_mode, subject epoch, lifecycle, library hard read-only, file version and revocation. Re-check read grants while serving bytes and Range. Keep anonymous/public-link flows isolated.
3. Unify directory API routing and service assembly in Hub. Administrative authenticated requests and ordinary authenticated requests share the same policy store and C ACL. Do not rely on mutually exclusive CLOUDFILE_ADMIN_POLICY_ENABLED vs CLOUDFILE_AUTHORIZATION_ENABLED routing. Unavailable required dependencies yield 503; never fall back to weak native repo rw.
4. Use the current instance's trusted identity provider without hardcoded etech. The local system_admin account must retain ordinary rights without an invented EAP Profile. No new grant table or per-library implicit admin records.
5. Remove obsolete routing/setup code only after the old file APIs have passed the managed-library acceptance matrix.

## RC acceptance matrix

- Unchanged Etech HTTP OAuth + native/OIDC login and file requests can list, preview, download/Range, upload, modify and detect conflict on both normal and managed libraries.
- Directory-only recipients reach only the authorized subtree; deny/invisible, revocation, account deactivation and stale file versions stop bytes and final publication.
- system_admin implicit content access works, daily_admin does not escalate, and existing ordinary/group library administrators are unaffected.
- Permission refusal -> 403; unavailable policy/storage -> 503; conflict -> 409. A disabled or absent optional third-party service must not make baseline authorization weaker.
- Three matching Hub/Server/Docker SHAs, amd64 artifact digest, all CI, DEV real requests and rollback evidence are required.

Prohibited shortcuts: never clear cf_managed_library, never remove legacyLibraryAllowed/cf_policy_check_legacy_library guards without equivalent native proof and final checks, never treat is_staff or repo rw as a directory content grant.

## Completed separately

Unused cf_dir_share data conversion was removed with immutable 040/042 DDL retained: Hub commit 720a622, Docker 491f9ff. Fourteen isolated MySQL 8 upgrade tests and both GitHub CI checks passed.
