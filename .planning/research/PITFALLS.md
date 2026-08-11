# Domain Pitfalls

**Domain:** Production-oriented Seafile CE 14 extension milestone
**Researched:** 2026-08-11
**Overall confidence:** HIGH for current codebase risks; HIGH for standards and official product contracts; MEDIUM for failure modes that still require phase-specific fault injection

## Recommended Phase Vocabulary

This document assigns each pitfall to the earliest roadmap phase that must close it:

1. **Security containment and acceptance restoration** — effective ACL enforcement, search isolation, sync fail-closed behavior, file-operation route/fact repair, and canonical preflight.
2. **Immutable release tuple and CI provenance** — exact cross-repository refs, dependency/image pins, artifact identity, attestations, and cross-repository trigger correctness.
3. **Local actions and OnlyOffice contracts** — versioned browser/Hub/Agent schemas, update/conflict semantics, callback authentication, idempotency, and generation-fenced locking.
4. **Authentik OIDC qualification** — standards-based login, token validation, identity/claim mapping, key rotation, logout, and recovery access.
5. **Storage-class lifecycle and migration** — user policy, offline copy/verify/cutover, rollback, GC/FSCK, and MinIO qualification.
6. **Tags and audit lifecycle completion** — binding/inheritance semantics, complete mutation coverage, reconciliation, retention, and export.
7. **Permission-trimmed Seafile AI and egress controls** — authorization at retrieval and generation, provider allowlists, content minimization, failure handling, and audit.

Do not enable a later capability in production merely because its own happy-path test passes. Every later phase inherits the security and provenance exit criteria of Phases 1–2.

## Critical Pitfalls

### Pitfall 1: Treating Seahub as the Final Authorization Boundary

**What goes wrong:** ACL checks added only to browser/API handlers are bypassed by sync, WebDAV, fileserver, direct Server RPC, archive/download, search, or a newly added upstream path. The current Go sync restriction lookup also converts RPC errors into “no restricted path” and caches revocation-sensitive results, so an enabled authority can fail open.

**Why it happens:** Seafile has multiple protocol entry points implemented in Python, C, and Go. Friendly Hub pre-checks are easy to add, while the authoritative Server/fileserver call-path inventory is wider and partly manual.

**Consequences:** A user can read, synchronize, search for, or mutate protected content even while the UI appears to deny it. A transient RPC outage or stale negative cache becomes an authorization bypass.

**Warning signs:**
- A permission change touches only `cloudfile-hub`.
- “No rule,” “feature disabled,” “authority unavailable,” and “malformed reply” collapse to the same return value.
- A cache of “unrestricted” decisions has a TTL but no ACL revision key or immediate invalidation.
- A denial test lacks a nearby allowed control, or exercises only REST.
- New upstream file-operation/read paths are not added to a maintained call-path inventory.

**Prevention:** Keep UI checks for diagnostics, but make C/Go Server boundaries authoritative. Distinguish inactive/unsupported from active-but-unavailable; once the extension is active, RPC, schema, decode, and policy-data failures must deny. Use revision-keyed immutable snapshots or immediate invalidation rather than time-only negative caching. Maintain executable cross-language cases and adversarial E2E across REST, upload/download, archive, sync, WebDAV, and direct fileserver paths. Disabled extensions must still preserve native CE behavior.

**Detection:** Inject RPC timeout, connection refusal, malformed JSON, database failure, and an ACL rule change during an active sync session. Assert immediate denial and no data transfer while also proving an unrestricted repository still works.

**Phase:** Phase 1 — Security containment and acceptance restoration.

**Confidence:** HIGH — directly evidenced by `.planning/codebase/CONCERNS.md`, the mapped C/Go request flow, and current test gaps.

### Pitfall 2: Filtering Search Results Without Effective CloudFile ACL Semantics

**What goes wrong:** Search indexes contain content the requester may not currently access, and result handling filters only native repository visibility or backend-specific fields rather than effective `cf_dir_acl` permissions. The current completed SeaSearch matrix already returns cross-user results.

**Why it happens:** Indexing is asynchronous, ACLs change independently, and each search backend has different filtering and pagination behavior. Reusing upstream “invisible repository/path” metadata is not equivalent to CloudFile directory ACL evaluation.

**Consequences:** File names, paths, snippets, match counts, facets, or timing disclose protected content. Filtering only the displayed rows can still leak totals and can produce incorrect empty/short pages.

**Warning signs:**
- Search + directory ACL can be enabled without a startup compatibility gate.
- The provider accepts only `repo_id`/`search_path` and never calls the effective ACL evaluator.
- SeaSearch and Meilisearch have different permission code paths.
- Filtering happens after totals/facets are returned, with no bounded over-fetch/cursor strategy.
- Tests assert only that permitted results exist, not that forbidden names, snippets, counts, and direct result URLs are absent.

**Prevention:** Reject every ACL/search combination at startup until a backend-independent, fail-closed permission trimmer exists. Apply the same effective path decision to every candidate regardless of provider; do not trust stale index-side ACL copies as the only authority. Define pagination and total-count semantics after trimming, bound over-fetch work, and invalidate or re-evaluate immediately after ACL/group changes. Never expose an unfiltered provider response to serializers, telemetry, AI retrieval, or clients.

**Detection:** A two-user/two-subtree matrix must query unique terms that exist only in each protected subtree on both SeaSearch and Meilisearch. Cover rule creation/removal, group membership change, provider restart, backfill, stale index state, pagination boundaries, snippets, totals, and direct-open URLs.

**Phase:** Phase 1 — Security containment and acceptance restoration; this is also a hard prerequisite for Phase 7.

**Confidence:** HIGH — current code inspection and red E2E evidence are explicit. Official SeaSearch documentation describes deployment/indexing but does not establish CloudFile ACL semantics, so no provider claim substitutes for the combined matrix.

### Pitfall 3: Using Mutable Refs and Unbound CI Results as Release Evidence

**What goes wrong:** A workflow builds Hub and Server from moving `dev` refs, optional services/actions from mutable tags, and then reports a green result that cannot be tied to the shipped image. Hub/Server pull requests do not trigger the full Docker matrices against their exact PR commits.

**Why it happens:** The control-plane workflows live in one repository while the runtime source lives in several. Branch refs are convenient during development, but rebuild and cross-repository dispatch semantics are not release provenance.

**Consequences:** The same version can rebuild to different binaries; a regression can merge without its affected E2E; rollback cannot identify a known-good tuple; compromised/moved action or image tags can alter the build without a source change.

**Warning signs:**
- `release.yaml` contains branch refs or empty Hub/Server/Docker commit fields for a release build.
- Workflow logs are the only place resolved commits are recorded.
- `uses:` references tags instead of full commit SHAs, or service images use `latest`/`testing` without digests.
- A capability test was skipped but the aggregate summary says “all passed.”
- An image tag, not an OCI digest, is the subject of promotion or rollback.

**Prevention:** Resolve one immutable Docker/Hub/Server/upstream tuple before the build and reject release mode if any source identity is mutable. Pin third-party actions to reviewed full SHAs and production images to digests. Build once, embed tuple/schema/extension-contract metadata, generate an SBOM, fan capability jobs out against the same image digest, and preserve their result manifest. Generate and verify provenance/SBOM attestations for that digest. Dispatch exact PR SHAs from every owning repository. Treat attestation as traceability, not proof that the artifact is secure.

**Detection:** Rebuild the same lock twice and compare source tuple, SBOM, image configuration, and digest (allowing only documented nondeterminism). Verify the attestation against the expected repository/workflow and reject mismatched signer, subject digest, or tuple. A CI self-test should prove every capability workflow is reachable locally and from its owning repositories, and that SKIP is distinct from PASS.

**Phase:** Phase 2 — Immutable release tuple and CI provenance. Exact-ref dispatch and honest gate reporting begin in Phase 1 because later work cannot rely on ambiguous evidence.

**Confidence:** HIGH — current manifest/workflow behavior is mapped locally; GitHub officially supports digest-bound artifact attestations and full-SHA action policies.

### Pitfall 4: Treating OIDC Login Success as Identity Integration Completion

**What goes wrong:** The authorization-code callback accepts an injected/mixed-up response, validates tokens incompletely, maps accounts by mutable claims, or widens groups/roles based on untrusted claim values. Key rotation, IdP outage, logout, and deprovisioning then lock users out or leave sessions authorized.

**Why it happens:** A successful redirect proves only the happy path. OIDC identity is the tuple of issuer and stable subject, while email, username, groups, and verification state have separate lifecycle and trust semantics.

**Consequences:** Account collision/takeover, unintended admin/group grants, login CSRF, stale authorization after deprovisioning, or a full administrative lockout during Authentik failure.

**Warning signs:**
- Regex/wildcard redirect URIs where one exact HTTPS URI is sufficient.
- No transaction-bound `state` plus OIDC `nonce`, or no PKCE S256 despite provider support.
- ID token validation omits signature/JWKS, exact issuer, audience/client ID, expiry, and nonce.
- Account linking uses email alone or automatically treats `email_verified=true`; Authentik changed its default `email_verified` behavior in 2025.10.
- Raw `groups` claims directly grant CloudFile roles without an allowlist and reconciliation policy.
- There is no local break-glass administrator tested independently of the IdP.

**Prevention:** Use Authentik only as a standard OIDC provider through Seahub’s generic authorization-code flow. Pin the qualified stable release/image (the official latest endpoint returned `2026.5.6` on 2026-08-11), register an exact HTTPS callback, use discovery/JWKS, PKCE S256, state, and nonce, and validate issuer/audience/signature/time claims. Persist identity by `(issuer, subject)` and make account-linking explicit. Use minimal scopes, explicit Authentik property mappings, group/role allowlists, deterministic removal semantics, and a tested local administrator. Define session revocation/logout separately from token validation.

**Detection:** E2E must cover first and returning login, duplicate/missing/malformed claims, unverified or changed email, wrong issuer/audience/nonce/state, code replay, signing-key rotation, group add/remove, user disable, Authentik outage, back-channel/front-channel logout if claimed, and local-admin recovery.

**Phase:** Phase 4 — Authentik OIDC qualification.

**Confidence:** HIGH for protocol controls and current Authentik release; MEDIUM for Seahub gaps until phase-specific inspection tests every token-validation branch.

### Pitfall 5: Switching Storage Routing Before a Complete, Verified Migration

**What goes wrong:** The database mapping points a library to the destination while commits, filesystem objects, or blocks are missing, still changing, or only partly copied. Cleanup/GC then deletes the only recoverable source objects.

**Why it happens:** A Seafile library is one logical unit but spans commit, FS-object, and block stores plus a database mapping. Object-store listing is paginated and retryable, and online writes create a moving source. A basic upload/download smoke test does not prove history, deduplicated/reused objects, GC, FSCK, or rollback.

**Consequences:** Silent historical corruption, unreadable files, split-brain writes, incomplete restores, or irreversible loss after source cleanup.

**Warning signs:**
- Migration runs while Server/fileserver/WebDAV/sync writers remain active.
- The routing row changes before destination enumeration and independent verification finish.
- The tool has no durable checkpoint, manifest, dry run, fault injection, or idempotent resume.
- Only blocks are counted; commits and FS objects are not verified separately.
- Source deletion is coupled to copy success, or GC/repair can run during migration.
- “S3-compatible” is claimed from basic object operations without provider lifecycle tests.

**Prevention:** Freeze the target library or stop all writers; capture the source mapping/head and a backup before copy. Enumerate commits, FS objects, and blocks completely with pagination/retry checkpoints; copy idempotently; verify counts, IDs/hashes, repository history, download, and FSCK before an atomic mapping cutover. Retain the source through a rollback/grace window and make cleanup a separately authorized, dry-run-first operation. Fence GC/FSCK and routing changes with migration state. Qualify only MinIO in this milestone; provider-neutral code is not a compatibility claim.

**Detection:** Interrupt every phase, restart/resume, inject truncated listings, missing/corrupt objects, stale credentials, throttling, and destination outages. Verify both rollback before cutover and rollback after cutover. Exercise multi-block current content plus historical versions, deleted/recovered entries, GC dry run, FSCK, and new writes after the migration is complete.

**Phase:** Phase 5 — Storage-class lifecycle and migration.

**Confidence:** HIGH — Seafile’s official multiple-backend documentation states that mapping is per library and stored in the database; official S3 documentation separates commit, FS, and block buckets; official GC/backup guidance reinforces dry-run and database/object consistency risks.

### Pitfall 6: Treating OnlyOffice and Local Editing as Ordinary Request/Response APIs

**What goes wrong:** The office capability is never registered, JWT configuration is missing or fail-open, a retried/stale callback saves twice or releases a newer lock, or the local Agent “write-back” creates a renamed sibling instead of updating the original. The current frontend also reads fields absent from the issued local-session response.

**Why it happens:** OnlyOffice callbacks are asynchronous status events and may arrive after close, retry, reconnect, force-save, or a newer edit generation. Local editing crosses independently released browser, Hub, native Agent, filesystem, and Server contracts. Owner/path alone is not a fencing token.

**Consequences:** Forged saves, lost updates, duplicate files, stale overwrite, a newer editor losing its lock, content fetched from an attacker-controlled URL, or unbounded files written to a desktop workspace.

**Warning signs:**
- An enabled module defines `register()` but is absent from startup registration.
- An empty OnlyOffice JWT secret means “accept callback.”
- Callback deduplication uses only status or path, not document key/generation/event state.
- Lock release accepts owner/path without the generation that acquired it.
- Agent response/descriptor schemas are implicit and unversioned.
- Existing-file write-back calls a create RPC or lacks expected-head/version conflict handling.

**Prevention:** Version and test schemas across Hub/frontend/Chrome/Agent before implementation. Make OnlyOffice JWT mandatory on both sides, fail startup on missing/mismatched settings, validate callback issuer/algorithm/claims, and allowlist the Document Server host for callback download URLs. Put an unguessable session generation in the document key/callback state, require it for save and release, and make callback handling idempotent. For Agent edit, use the update RPC with expected head/file version; never silently rename on conflict. Preserve one-time ticket, exact origin allowlist, safe filename, private workspace, no-shell execution, bounded download, short write capability, stable-write detection, and cleanup.

**Detection:** Browser-to-Agent and OnlyOffice container matrices must cover registration/config startup failure, invalid/missing JWT, duplicate/out-of-order/delayed callbacks, reconnect and force-save statuses, stale generation, simultaneous editors, callback URL host abuse, update conflict, ticket replay/expiry, oversized content, symlink/workspace attacks, crash/restart, and lock expiry/release.

**Phase:** Phase 3 — Local actions and OnlyOffice contracts.

**Confidence:** HIGH — known defects are directly evidenced by mapped source. ONLYOFFICE’s official callback contract confirms asynchronous status-specific callbacks and user/tab-dependent callback selection.

### Pitfall 7: Binding Tags or Audit Only to the Happy-Path Event Stream

**What goes wrong:** Tags disappear or attach to the wrong entry after move/copy/rename/recovery, directory inheritance becomes ambiguous, and audit records omit mutations from sync/WebDAV/fileserver or disappear when an asynchronous consumer crashes after commit.

**Why it happens:** Path is mutable, while content-addressed FS/object IDs can be reused and therefore are not automatically a unique file-entry identity. Seafile metadata processing is asynchronous and explicitly has interrupted-initialization and missed-event reconciliation states. Post-commit observers cannot roll back an already committed write.

**Consequences:** Incorrect classification/permissions, orphaned metadata, audit gaps, duplicate facts on retry, unbounded audit tables, and false compliance claims.

**Warning signs:**
- Tag binding has no written identity and lifecycle rule for rename/move/copy/delete/recover/version restore.
- Inheritance is computed once and copied rather than resolved with a defined override model.
- Audit relies only on a Hub hook or `repo_update` event instead of authoritative C/Go mutation facts.
- Operation facts lack a unique event/operation ID, before/after paths, actor, protocol, result, and commit/head.
- There is no reconciliation cursor, dead-letter/retry visibility, retention policy, export boundary, or deletion policy.

**Prevention:** Specify binding semantics before schema: what is attached to a directory entry versus content/version, how moves preserve, copies duplicate or reset, recovery reattaches, and inheritance/overrides resolve. Drive lifecycle changes from the shared authoritative file-operation vocabulary. Emit idempotent PREPARE/COMMITTED/ABORTED facts with stable operation IDs; use a durable journal/outbox so consumers can retry and reconcile from repository history. Keep audit operational history distinct from an immutable compliance ledger. Define indexed queries, retention/archival, export/SIEM handoff, legal deletion boundaries, and redaction of content/secrets.

**Detection:** A shared matrix must exercise create/update/delete/bulk-delete/move/copy/rename/recover/version restore through REST, browser, sync, and WebDAV; repeat delivery; reorder delivery; crash between commit and consume; rebuild metadata from a prior cursor; permission loss/gain; inherited tag overrides; and retention/export at volume.

**Phase:** Phase 6 — Tags and audit lifecycle completion. The missing bulk-delete/file-operation fact must be repaired in Phase 1.

**Confidence:** HIGH for the lifecycle hazard and current route gap; MEDIUM for the final binding model because it is a product decision that the phase must settle explicitly.

### Pitfall 8: Sending AI Context Before Applying Current Permissions and Egress Policy

**What goes wrong:** Seafile AI or an external OpenAI-compatible endpoint receives restricted file content, stale search/index chunks, hidden metadata, secrets, or more context than the initiating request needs. Provider retries/logging/caches retain data outside CloudFile’s control.

**Why it happens:** Retrieval, metadata extraction, prompt construction, model execution, response caching, and audit are separate boundaries. Seafile AI supports many providers through LiteLLM/OpenAI-compatible URLs, making provider configuration an outbound data route rather than merely a model choice.

**Consequences:** Confidential data leaves the deployment or tenant boundary, revoked users continue querying cached context, prompts/results leak through logs, and an arbitrary provider URL becomes SSRF or credential exfiltration infrastructure.

**Warning signs:**
- AI is enabled before combined ACL/search isolation is green.
- Permission checks happen only when indexing, not again at retrieval/generation time.
- Operators can configure arbitrary schemes/hosts or redirects for LLM endpoints.
- One shared cache/keyspace serves users with different permissions without ACL revision/user scoping.
- Prompts, snippets, API keys, or full model responses appear in normal logs/audit exports.
- Disabled or failed AI falls back to an unapproved default provider.

**Prevention:** Keep AI default-off and require an explicit egress policy: allowed HTTPS origins, redirect/DNS/IP controls, TLS verification, secret-file injection, model allowlist, request size/type limits, timeout/retry budgets, and operator acknowledgement of provider retention terms. Apply current effective ACLs before retrieval, before prompt assembly, and before returning/caching results; scope/invalidate caches on ACL/group revisions. Minimize/redact context and metadata, never log content or credentials by default, record only bounded audit metadata, and fail closed without provider fallback. Separate locally hosted and external-provider profiles visibly.

**Detection:** E2E must attempt AI queries over an invisible path, revoke access between index and query, change groups during a session, poison a provider redirect/DNS response, inject malformed/oversized/slow LLM responses, exhaust retries, inspect all logs/cache/audit records for sentinel secrets, and confirm disabled mode causes no external DNS/network request.

**Phase:** Phase 7 — Permission-trimmed Seafile AI and egress controls; blocked by Phase 1 search/ACL correctness and Phase 6 metadata lifecycle confidence.

**Confidence:** HIGH for the egress boundary and dependency ordering; MEDIUM for exact upstream Seafile AI payload behavior until a phase-specific proxy capture documents each feature’s request shape.

## Moderate Pitfalls

### Pitfall 1: Startup Configuration Accepts Half-Enabled Capabilities

**What goes wrong:** A Compose profile starts an optional service while the Hub registry, Server provider, callback route, worker, schema, secret, or provider selection is absent. The system appears enabled but silently runs native behavior or fails only on use.

**Warning signs:** Feature switches and service profiles are treated as synonyms; generated Seahub settings can fail import; provider name validation is deferred to the first request; schema/version mismatches are warnings.

**Prevention:** Add a startup capability handshake that checks switch, registration, route, schema, extension contract, selected provider, secret presence, and required service health. Fail the affected capability closed with a targeted diagnostic. Keep an explicit disabled baseline test proving native CE behavior.

**Detection:** For every capability, test disabled, correctly enabled, missing-service, missing-secret, unknown-provider, old-schema, and mismatched Hub/Server contract states.

**Phase:** Phase 1 for the common handshake; each capability phase adds its own requirements.

**Confidence:** HIGH — OnlyOffice already demonstrates this class of defect.

### Pitfall 2: Destructive Maintenance Is Authorized by a Single Success Signal

**What goes wrong:** Migration cleanup, GC, FSCK repair, audit purge, tag rebuild, or index replacement proceeds because one preceding command exited zero, even though it skipped work or verified only part of the state.

**Warning signs:** PASS/SKIP are conflated; repair is available online; no immutable pre-operation manifest/backup; cleanup is automatic immediately after cutover.

**Prevention:** Require explicit plan/dry-run output, complete enumeration, backup identifier, independent verification report, operator authorization, and rollback evidence. Separate copy, cutover, observation, and cleanup commands. Use narrowly scoped explicit target IDs.

**Detection:** Fault-inject skips, partial enumeration, stale state, and nonzero mismatches; prove the destructive command remains unavailable.

**Phase:** Phase 5 for storage; Phase 6 for retention/rebuild; Phase 1 for honest gate semantics.

**Confidence:** HIGH.

### Pitfall 3: Asynchronous Workers Have No Durable Ownership or Backpressure

**What goes wrong:** One sequential worker accumulates search, metadata, directory-sync, audit-export, and external tasks; restart loses in-memory pending work or duplicate workers process the same library without leases.

**Warning signs:** Only interval and batch size are observable; no durable cursor/lease, queue depth, oldest-age metric, dead-letter state, or per-library serialization test.

**Prevention:** Give each task durable cursors and idempotency keys, explicit ownership/leases, bounded retries, per-capability concurrency budgets, and lag/error metrics. Preserve per-library ordering where lifecycle semantics require it.

**Detection:** Run large backfill plus live writes, kill/restart workers, run two workers, poison one item, and assert forward progress without gaps or duplicate effects.

**Phase:** Phase 6 for metadata/audit and Phase 7 for AI/index work; common worker telemetry may begin in Phase 1.

**Confidence:** MEDIUM — architecture exposes the risk, but production workload limits are not yet measured.

### Pitfall 4: External-Service Version Drift Changes a Qualified Contract

**What goes wrong:** Rebuilding with `latest`, `testing`, or a moved tag silently changes Authentik, SeaSearch, Metadata Server, Seafile AI, SeaDoc, MinIO, or another optional service and invalidates schema/API/security evidence.

**Warning signs:** A capability matrix records only a friendly tag, upgrade notes are not reviewed, and rollback does not retain the previous digest/data schema.

**Prevention:** Qualify an exact version and image digest per capability, record it in the release lock/SBOM, test upgrade and rollback with persisted data, and expand a supported range only after a compatibility matrix.

**Detection:** CI prints and asserts all resolved digests; a lock-diff job identifies changed service artifacts even when source is unchanged.

**Phase:** Phase 2 establishes the mechanism; each capability phase qualifies its service version.

**Confidence:** HIGH.

## Minor Pitfalls

### Pitfall 1: Documentation Status Outruns Executable Evidence

**What goes wrong:** “Implemented,” “supported,” or old gap text is interpreted as production readiness despite red, skipped, or never-triggered acceptance gates.

**Prevention:** Generate or validate feature status from the immutable tuple’s result manifest. Distinguish present, wired, tested, qualified, and supported. Archive superseded narratives and date all compatibility claims.

**Phase:** Phase 2, then enforced at every phase exit.

**Confidence:** HIGH.

### Pitfall 2: Logs Become a Secondary Disclosure Channel

**What goes wrong:** OAuth codes/tokens, callback JWTs, local tickets, storage credentials, file paths/snippets, prompts, or AI results enter workflow artifacts and persistent logs.

**Prevention:** Structured allowlist logging, header/body redaction, secret scanning of failure artifacts, short retention, and tests using sentinel credentials/content. Audit actor/action metadata without raw content.

**Phase:** Phase 1 common redaction; Phases 3, 4, and 7 add protocol-specific sentinels.

**Confidence:** HIGH for impact; MEDIUM for current exposure because no complete runtime log capture was performed in this research pass.

### Pitfall 3: Compatibility Claims Ignore Negative and Recovery Paths

**What goes wrong:** A successful create/login/edit/query is used to claim support while disablement, outage, retry, revocation, restore, and rollback remain undefined.

**Prevention:** Every acceptance matrix includes positive control, denial control, dependency outage, restart, upgrade/rollback where stateful, and disabled-feature native baseline.

**Phase:** All phases; enforced by the Phase 1 gate contract.

**Confidence:** HIGH.

## Phase-Specific Warnings

| Phase Topic | Likely Pitfall | Required Mitigation / Exit Evidence |
|-------------|----------------|-------------------------------------|
| 1. Security containment and acceptance restoration | Search leaks, sync fail-open, incomplete mutation route, false-green skips | Backend-independent effective ACL trimming on SeaSearch and Meilisearch; outage/revocation tests; valid bulk-delete route/fact; canonical preflight in all repositories; PASS/SKIP separation |
| 2. Immutable release tuple and CI provenance | Moving refs/tags, E2E against the wrong commits, unsigned build-info | Locked three-repository/upstream/service tuple; exact-ref dispatch; one tested image digest; full-SHA actions; SBOM and verified digest-bound provenance; result manifest |
| 3. Local actions and OnlyOffice contracts | Schema drift, create-vs-update, forged/replayed callback, stale unlock | Versioned contract tests; update with expected head; mandatory matching JWT; host-limited callback fetch; idempotent event handling; generation-fenced save/release; browser/container E2E |
| 4. Authentik OIDC qualification | Login CSRF/mix-up, mutable identity, claim privilege widening, lockout | Exact redirect, code + PKCE S256/state/nonce, full ID-token validation, `(iss, sub)` identity, explicit claim/group mapping, signing rotation, disable/logout/outage and local-admin recovery tests |
| 5. Storage-class lifecycle and migration | Partial/split-brain library, premature source deletion, GC/FSCK damage | Writer freeze; durable manifest/checkpoint; complete commit/FS/block copy and verification; atomic cutover; backup/rollback/grace period; fault injection; MinIO-only support claim |
| 6. Tags and audit lifecycle | Path/object identity mismatch, missed/duplicate events, unbounded tables | Written bind/inherit/move/copy/recover semantics; durable idempotent mutation facts; reconciliation; all-protocol matrix; indexed retention/archive/export policy; operational-vs-compliance boundary |
| 7. Permission-trimmed Seafile AI and egress controls | Restricted context sent externally, arbitrary provider SSRF, prompt/log retention | Current ACL check at retrieval/generation/return; cache invalidation; HTTPS provider allowlist and network controls; minimized payload; no-content logs; failure/no-fallback tests; zero egress while disabled |

## What Might Still Be Missed

- Seahub’s exact OIDC validation behavior (issuer, audience, nonce, PKCE, JWKS refresh) needs line-by-line phase research; generic OAuth settings alone do not prove an OIDC-conformant relying party.
- OnlyOffice 8.2 is the currently declared deployment version while current official API documentation covers newer releases. Phase 3 must test the pinned 8.2 behavior and either retain that qualification or upgrade deliberately; do not infer all callback behavior from current docs.
- The storage migration implementation needs provider-level inspection for pagination tokens, versioned buckets, server-side encryption metadata, and shared/reused object assumptions before cleanup semantics are frozen.
- Tag entry identity is an unresolved product/schema decision. Path, content/object ID, and version each have different move/copy/reuse behavior; Phase 6 must decide explicitly from native Seafile metadata primitives.
- External LLM retention, training, residency, and deletion guarantees are provider-specific contracts outside CloudFile. Phase 7 must expose them as operator policy, not make a generic promise.

## Sources

### Project and Codebase Evidence (HIGH confidence)

- `.planning/PROJECT.md` — active scope, constraints, current red gates, and release/storage/identity decisions.
- `.planning/codebase/ARCHITECTURE.md` — trust boundaries, request/write flows, repository ownership, extension registries, and local-client protocol.
- `.planning/codebase/CONCERNS.md` — direct evidence for search leakage, Go sync fail-open behavior, local-agent/OnlyOffice defects, mutable refs, and test gaps.
- `.planning/codebase/INTEGRATIONS.md` — current Authentik, OnlyOffice, storage, metadata, AI, and external-service wiring.
- `.planning/codebase/STACK.md`, `.planning/codebase/STRUCTURE.md`, `.planning/codebase/TESTING.md` — versions, authoritative locations, gate topology, and current green/red evidence.

### Primary Official Sources

- [Authentik OAuth2/OIDC provider documentation](https://docs.goauthentik.io/add-secure-apps/providers/oauth2/) — supported authorization-code/OIDC flow, PKCE, discovery/JWKS, redirect URI behavior, issuer modes, scopes, signing, and the `email_verified` change (HIGH confidence).
- [Authentik 2026.5.6 official release](https://github.com/goauthentik/authentik/releases/tag/version/2026.5.6) — stable release observed from the official latest-release endpoint on 2026-08-11 (HIGH confidence).
- [RFC 9700: OAuth 2.0 Security Best Current Practice](https://www.rfc-editor.org/rfc/rfc9700.html) — exact redirect matching, CSRF/mix-up defenses, PKCE S256, and authorization-code security (HIGH confidence).
- [ONLYOFFICE callback handler](https://api.onlyoffice.com/docs/docs-api/usage-api/callback-handler/) — asynchronous statuses, save timing, force-save, callback selection, and retry-sensitive behavior (HIGH confidence for current API; MEDIUM for the pinned 8.2 server until tested).
- [ONLYOFFICE request/callback signatures](https://api.onlyoffice.com/docs/docs-api/additional-api/signature/) — incoming/outgoing JWT configuration and secrets (HIGH confidence for current API).
- [Seafile 14 multiple storage backends](https://manual.seafile.com/14.0/setup/setup_with_multiple_storage_backends/) — per-library mapping, storage-class selection, and migration model (HIGH confidence).
- [Seafile 14 S3 backend](https://manual.seafile.com/14.0/setup/setup_with_s3/) — distinct commit, FS-object, and block backends plus provider-specific compatibility caveats (HIGH confidence).
- [Seafile 14 GC](https://manual.seafile.com/14.0/administration/seafile_gc/) and [Seafile backup/recovery](https://manual.seafile.com/13.0/administration/backup_recovery/) — dry run, destructive collection, database/object consistency, backup order, and FSCK after recovery (HIGH confidence for principles; backup page is version 13 because the 14.0 search surface redirects/omits a dedicated current page).
- [Seafile 14 Metadata Server](https://manual.seafile.com/14.0/extension/metadata-server/) — event pipeline, ordered commit traversal, interrupted initialization, reconciliation, and persistence dependencies (HIGH confidence).
- [Seafile AI extension](https://manual.seafile.com/latest/extension/seafile-ai/) — LiteLLM/OpenAI-compatible external provider configuration and arbitrary endpoint/key/model boundary (HIGH confidence for current upstream; MEDIUM for CloudFile’s pinned image until traffic is captured).
- [GitHub artifact attestations](https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/use-artifact-attestations) — digest-bound container provenance, SBOM attestations, and verification (HIGH confidence).
- [GitHub Actions repository policy](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-github-actions-settings-for-a-repository) — enforcement of full-length action commit SHAs (HIGH confidence).

---

*Pitfall research: 2026-08-11*
