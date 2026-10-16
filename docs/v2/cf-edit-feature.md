# CF-EDIT optional feature: Agent2 + PLM/CAD Checkout/Checkin

Status: **optional infrastructure only**. After 2026-10-16 indexed-lock
performance review, this foundation is permitted to merge into `dev` while
**disabled by default**. It is NOT ready to activate or deploy as an operational
Checkout/Checkin feature.
Based on the independent CE14 CloudFile V2 `dev` baseline. Do not restore the V0.9
schema, resource UID service, local edit sessions, outbox or old locks/v1 HTTP API.

## Isolation

Repositories: `eaopen/cloudfile-server`, `cloudfile-hub`, `cloudfile-docker`,
each on `feature/cf-edit`; native source pins in `build/v2/source-set.json`.
The existing three-table `cloudfile-v2.sql` stays unchanged. An independent
`cloudfile-v2-edit.sql` adds exactly:

| Table | Owner / purpose |
| --- | --- |
| `cf_edit_guard` | One permanent file slot per repo+path hash; lock/checkout mode, monotonic generation, credential epoch, owner, client, optimistic baseline, renewable/persistent lease and pending intent |
| `cf_commit_intent` | Durable request digest and prepare/published/cancelled receipt, expected/staged/result file IDs and final native Commit ID; shared by optimistic Agent saves and exclusive Commit/Checkin |

Both are **in seafile_db, InnoDB**, so the final Branch update, published
receipt, and released/advanced Guard can share one database transaction.
`FreshSchema(connection, core_ddl)` still verifies exactly three tables.
Only an explicit `FreshSchema(connection, core_ddl, edit_ddl=...)` opt-in
can install or verify the two feature tables in an isolated instance.

## Two clients, one server contract

- Agent2: authenticated user/registered device, renewable Checkout, local
  journal/snapshot, automatic optimistic saves or explicit exclusive Commit.
- External PLM/CAD integration (Teamcenter-like): delegated authenticated
  user and integration application identity, persistent Checkout if needed,
  direct file/block staging, explicit Commit/Checkin without Agent/Chrome.
  `client_ref` is only external correlation, never a source of authorization.
- One Guard per real `repo_id + path`. New Guard always increments generation.
  `credential_epoch` rotates on Resume; every write requires *current* ACL,
  current Guard proof, expected file version and prepared Intent.
- `commit` advances `base_file_id` and keeps Checkout; `checkin` releases
  only after successful native publication; `checkin-unchanged` releases
  atomically without forcing a new file version; `abandon` requires an
  explicit owner/management action and **no unresolved prepared Intent**.
- File changes and parent directory rename/delete affecting guarded files
  must be blocked from unscoped native writes. Unsupported paths fail closed
  once CF-EDIT enforcement is enabled; ordinary CE instances remain native.

## Current code and immediate checks

Completed on the feature branch:
1. Core schema and generic, authenticated-principal-only Guard/Intent contract
   and SQL Store (`editing_contract.py`, `editing_store.py`).
2. Transaction order Branch → Guard → Intent in the Hub Store.
3. C Branch and Go Fileserver final-CAS unscoped write fences. They compare the
   actual native old/new trees and refuse touching an occupied path; errors
   fail closed. Both use `[cloudfile] v2_edit_enabled` from `seafile.conf`,
   **default false**. They do not grant exclusive publishing by themselves.
4. Pure Python contract and lock-order tests, Go guarded-path unit tests,
   isolated MariaDB schema and atomic receipt tests; each has its own feature CI.

**BLOCKING FOR ACTIVATION / AGENT2 E2E**, not for merging disabled
infrastructure. Do NOT set `v2_edit_enabled=true` in any shared or production
instance yet:

- A native C controlled-publish method that atomically checks the authenticated
  ACL, prepared Intent, live Guard/epoch/proof, real File ID under locked Branch,
  and writes published receipt + updated/released Guard + Branch in one
  transaction. The existing generic C/Go fences intentionally deny unscoped
  edits including the owner; a user cannot yet Commit a Checkout.
- Trusted HTTP/SDK adapters for Agent2 and external integrations, including
  a secure staging/CDC path, identity-to-native-user mapping and read-only
  Intent result query. **No editing routes have been registered.**
- Runtime integration/compile validation against the exact immutable CE14
  source tree and MariaDB, Web/Sync/VirtualRepo bypass validation, restart and
  lost-response tests, and real Agent/PLM client E2E. Contract and DB tests
  cannot substitute for these.

## MVP verification and merge gate

Only after Etech core V2 M1/M2 is independently operational, run this isolated
feature MVP: (1) start from pinned clean CE14 with five reviewed tables;
(2) build native C + Go and run feature CI; (3) two concurrent Checkout
requests, one success; (4) another user's Web/C/Go/sync/rename attempt cannot
touch a checked-out file; (5) Agent saves and direct PLM Commit/Checkin use
one native transaction; (6) restart/lost HTTP receipt retry returns exactly one
native version; (7) revoked ACL/expired Agent lease/stale token rejects final
publish; (8) independent files remain editable and normal CE unguarded behavior
unchanged.

Updated acceptance (2026-10-16): merging **feature-off foundational code**
into `dev` is allowed after native build, test, and performance gate. Enabling
CF-EDIT or claiming Agent2 edit capability still requires the real E2E checks.
No feature table installation is part of standard 3-table V2 startup.
No PROD deployment or switch-on is approved by this merge. This document is
a status/boundary record, **not** a claim that MVP passed.

## Reviewed performance and Agent Rust compatibility

- Read/preview/download/list API paths do not invoke the CF-EDIT Branch
  final-write hook. With `v2_edit_enabled=false`, Go returns before SQL and
  native C returns before Guard SQL; default CE write paths are retained.
- With the flag enabled, native C+Go query only *active* Guard IDs using the
  reviewed index `cf_edit_guard_active (repo_id,guard_id)`. No active locks
  means no file-tree diff. A per-repository active-lock guardrail fails closed
  rather than scanning an unlimited result set. The 2026-10-16 disposable
  MariaDB test used **12,000 historical Guard rows and one active Guard**, then
  zero active Guards, asserting the chosen index and query results. It is
  **not** a real-life upload throughput benchmark. No guarantee of constant
  time for large multi-file writes while thousands of locks are active.
- `eaopen/cloudfile-local-agent2@dev` already has Rust
  `auto_upload.rs`, `exclusive.rs`, `journal.rs`, `cdc.rs` and P-256
  device signing. Its actual device endpoints remain
  `/api/v2.1/cloudfile/extensions/local-edit/v1/agent/` and browser pairing
  `.../local-edit/v1/devices/pair-start/`. In this V2 CF-EDIT foundation,
  **these routes and the signed device identity bridge do not exist**.
  Only the Guard/Intent storage primitives and unscoped native protection
  exist. Do not misreport Agent2 E2E as implemented; leave all Agent2 editing
  capabilities unavailable until an authenticated V2 adapter and controlled
  native final Commit/Checkin are completed.
- Teamcenter-like PLM direct API remains design-only per user instruction;
  it is NOT an activation or merge prerequisite. Focus future test passes on
  Agent2 optimistic local edits and exclusive Checkout/Commit/Checkin.
