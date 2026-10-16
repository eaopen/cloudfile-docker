# v0.9 RC: Unified Default Authorization (Blocking Contract)

Status: P0 IN PROGRESS. Native single-file download adapters are implemented
and locally tested; chunked upload, structural writes and real deployment
acceptance remain incomplete. This is not a release claim.

## Etech v0.9 closeout boundary (2026-10-16)

The release consumer is the existing Etech drive. Independent Hub pages,
sync/WebDAV/third-party clients and v2.0 compatibility are outside this
closeout. Existing guards remain mandatory for unadapted entries.

Closeout now prioritizes the existing Etech happy path: listing, upload/resume/
overwrite, single-file download/preview, folder creation and ordinary file
operations. Use one ordinary library, one managed library and existing real
accounts. Do not expand negative-test or authentication/entrypoint matrices;
run only focused checks needed by the changed behavior or an observed failure.
Retain existing guards and regression tests. This consumer-specific scope
supersedes broader acceptance requirements later in this document.

Exclusive editing, Checkout/checkin, editing leases/sessions and Rust Agent
development, pairing, packaging and acceptance are excluded from v0.9.
They are neither delivery requirements nor dependencies of ordinary drive
operations. v2.0 is being rebuilt separately; no compatibility work is required.

The native single-file GET adapter preserves `/api2/repos/{repo}/file/` and
returns a JSON URL string, as CE does. It issues an existing path/head-bound
60-second native read ticket after current C-policy preflight. Browser navigation
uses `/cloudfile/files/{ticket}/{filename}` on the configured FileServer root;
this adapter reuses the guarded reader and audit path. It never issues a legacy
ticket, accepts client-selected identities, or enables legacy managed reads.
Every byte chunk and Range request still invokes the native read authority.
Tickets remain single-use; a new request requires a fresh URL.

The supported credentials are the existing signed OAuth browser session and
the native v1 user Token used by Etech. The latter stores only a SHA-256 digest
in private ticket conditions. At issuance, consumption and each chunk, Server
locks the exact owner's current `api2_token` row on the configured identity
database, compares its digest and requires InnoDB. Rotation/deletion, account
disablement, identity/context changes and ACL revocation cannot reuse a cached
grant. This proof is read-only and is refused by final write publication.
Other token kinds fail closed until explicitly implemented.
Token issuance uses a distinct native RPC name, so a newer Hub paired with
an older Server refuses instead of dropping an unknown credential proof.

This increment does not complete native chunked upload, structural writes or
the Etech DEV acceptance gate. Hub/Server must be deployed together.

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

## v0.9 directory-address and Internal Link increment (2026-10-15)

The CloudFile-native OAuth adapter now exposes the same authenticated
read-only shared-directories, directory-address and directory-entries
endpoint shapes as the hosted policy adapter. Seafile existing Smart Link
directory creation/token lookup reuses those scoped checks for users who
cannot pass its original native repo permission; it adds root_path,
initial_path and permission, without creating additional access grants.
For plain CE access, the original Smart Link handler remains unchanged.
See docs/v09-permission-and-internal-links.md for the permission contract.

This is not a claim that clicking a legacy browser Smart Link from a user
without whole-library membership renders the old Seafile library page, nor
that the old managed-library upload/download transport guard is solved.
The latter remains P0 and MUST keep fail-closed until native proof reaches
its byte and final-publication check.
