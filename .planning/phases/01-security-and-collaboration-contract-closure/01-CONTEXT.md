# Phase 1: Security and Collaboration Contract Closure - Context

**Gathered:** 2026-08-11
**Status:** Ready for planning

<domain>
## Phase Boundary

Restore trustworthy cross-repository security and mutation gates, then close the known local-edit and OnlyOffice contracts. This phase delivers correctness and end-to-end evidence for existing capabilities; it does not add identity, storage self-service, tags/audit expansion, AI, federation, or release-provenance features.

</domain>

<decisions>
## Implementation Decisions

### ACL Search And Sync Authority
- Apply one backend-independent effective CloudFile ACL evaluator to every search candidate before totals, snippets, serialization, caching, or return; SeaSearch and Meilisearch must obey identical authorization semantics.
- Treat inactive ACL as native CE pass-through, active valid state as allow/deny, and active unavailable or malformed authority state as denial.
- Do not cache an unrestricted answer across ACL changes; use revision-aware invalidation or reevaluate current ACL state at the final boundary.
- Verify positive, invisible, denied, outage, malformed, immediate-revocation, restart, pagination, total, snippet, and cache behavior for both search backends and direct sync/fileserver paths.

### Mutation Facts And Lock Fencing
- Use one stable operation identity for a logical batch or write and require exactly one PREPARE followed by one terminal COMMITTED or ABORTED fact.
- Require the current generation for every racing mutation, save, callback, write-back, and lock release; stale or absent generations cannot release or overwrite newer work.
- A post-operation observer failure may be retried or audited but cannot roll back a completed native write or fabricate a second terminal fact.
- Cover browser/API, fileserver/sync, WebDAV, batch delete, retry, partial failure, callback, and abort paths using the shared file-operation vocabulary.

### Versioned Local Edit Contract
- Introduce an explicit protocol version and a canonical session/descriptor schema; the pre-claim response includes the file name and fields the frontend needs before ticket claim.
- Keep the ticket one-time, short-lived, origin-bound, and free of browser cookies or long-lived CloudFile credentials; fail closed on unsupported protocol versions.
- Write-back updates the existing file and carries version/generation preconditions; it never creates an unrelated replacement when the target already exists.
- Verify descriptor download, Chrome Native Messaging handoff, claim, download, app launch, heartbeat, stable-write detection, retry idempotency, conflict, expiry, and stale-generation refusal while preserving independent client releases.

### OnlyOffice And Truthful Gates
- Register OnlyOffice during Hub startup only when enabled, through the existing feature registry pattern.
- Enabling OnlyOffice requires matching, non-empty JWT configuration on Hub and Document Server; missing or inconsistent configuration fails startup rather than accepting unauthenticated callbacks.
- Authenticate, deduplicate, and generation-fence asynchronous save callbacks and lock release; retrying a callback returns the prior outcome without applying the write twice.
- Add one integrated collaboration matrix and make local/CI preflight share the same declared capability table; required but unavailable dependencies are FAIL, intentional optional omissions are SKIP, and executed assertions alone are PASS.

### the agent's Discretion
- Internal helper names, file layout within the owning repository, and the smallest compatible wire representation are at the agent's discretion provided the shared contracts and existing repository conventions are preserved.
- Plans may reorder independent fixes within this phase to restore a red gate sooner, but each commit and plan must remain independently verifiable.

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `tests/e2e/search_matrix.py`, `tests/e2e/fileop_matrix.py`, `docs/acl-cases.json`, and `docs/fileop-cases.json` already provide executable cross-language contract foundations.
- `../cloudfile-hub/cloudfile_ext/acl/`, `../cloudfile-hub/cloudfile_ext/search/`, and `../cloudfile-server/common/cf-ext.*` provide the current permission evaluators and extension seams.
- `../cloudfile-hub/cloudfile_ext/file_actions/`, `../cloudfile-hub/frontend/src/cloudfile/file-actions/`, `../cloudfile-local-agent/`, and `../cloudfile-chrome-extension/` contain the existing one-time session flow.
- `../cloudfile-hub/cloudfile_ext/office/` already contains a capability `register()` entry and callback wrapper that can be hardened instead of replaced.

### Established Patterns
- Capability packages register during startup, honor default-off `CF_ENABLE_*` switches, and preserve native CE behavior when inactive.
- Security-critical final enforcement belongs in Server/fileserver; Hub prechecks improve UX but cannot be the only authority.
- Shared JSON case files and container matrices define cross-repository semantics; provider/hook post-failures are isolated from committed native writes.
- Generated settings are rewritten idempotently on every startup and must be tested as executable Python, not only as text.

### Integration Points
- Search filtering connects Hub search adapters and upstream search endpoints to the CloudFile ACL evaluator before response totals and serialization.
- Sync fail-closed behavior connects `../cloudfile-server/fileserver/cf_ext.go` and sync routes to the C/RPC restricted-path authority.
- Mutation lifecycle and lock fencing connect C Server, Go fileserver, Hub file actions, WebDAV patch behavior, OnlyOffice callbacks, and the local agent update API.
- Gate parity connects `tools/preflight-checks.py`, `tools/run-checks.sh`, `tools/verify-local.sh`, capability tables, and GitHub E2E workflows.

</code_context>

<specifics>
## Specific Ideas

- Prefer Seafile's existing search, lock, metadata, office, and write APIs; add only the missing CloudFile authorization and lifecycle seams.
- Resolve the two already confirmed small blockers early: the frontend expects `session.file.name` but Hub omits `file`, and OnlyOffice defines `register()` but Hub startup does not invoke it.
- Preserve conservative maturity labels until integrated negative and recovery cases pass.

</specifics>

<deferred>
## Deferred Ideas

- Authentik OIDC qualification belongs to Phase 3.
- CE per-library storage selection and MinIO lifecycle belong to Phase 4.
- Tag and audit semantic expansion belongs to Phase 5.
- Seafile AI and external-LLM controls belong to Phase 6.
- OpenList/rclone external-data federation remains a separate post-MVP project.

</deferred>
