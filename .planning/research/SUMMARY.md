# Project Research Summary

**Project:** CloudFile CE Extension
**Domain:** Production-oriented, multi-repository Seafile CE 14 extension for secure enterprise file collaboration
**Researched:** 2026-08-11
**Confidence:** HIGH for scope, architecture, known defects, and official integration contracts; MEDIUM for unverified end-to-end behavior

## Executive Summary

CloudFile is not a new file platform; it is a controlled extension of Seafile CE 14 across Docker, Hub, Server, local-agent, and browser-extension repositories. Experts should preserve Seafile's native ownership of libraries, commits, blocks, sync, WebDAV, OAuth, metadata, search, office, and AI, then add small feature-gated seams for missing policy and lifecycle behavior. The Server/fileserver boundary must remain authoritative for permissions and writes, while Hub and optional services provide orchestration, candidates, and user-facing prechecks without becoming bypassable authorities.

The milestone should begin by restoring red correctness/security gates and closing known collaboration contract blockers: backend-independent ACL-trimmed search, fail-closed sync authorization, valid mutation lifecycle facts, generation-fenced locks, OnlyOffice registration/JWT/idempotent callbacks, and a versioned local-edit update contract. Next, make every later result attributable to an immutable cross-repository release tuple. Only then qualify generic Authentik OIDC, expose native per-library local/MinIO storage classes with safe migration, complete tags and audit, and enable official Seafile AI with permission trimming and explicit external-LLM egress policy. External federation remains a separate later project.

The dominant risks are false-green acceptance evidence, Hub-only authorization, mutable release inputs, partial storage migration, and optional services leaking or widening access. Mitigate them with tri-state fail-closed authority seams, positive/denial/outage/restart/rollback matrices, one digest-addressed image per immutable tuple, durable migration journals with separate cleanup authorization, and current ACL evaluation before search serialization or AI egress. Capability presence or a running Compose profile is never sufficient evidence of support.

## Key Findings

### Recommended Stack

Retain the existing Seafile CE 14 source-assembly and Docker Compose architecture; this milestone is integration and qualification work, not a framework migration. Formal release builds should resolve every product repository, maintained patch, base image, and optional service to immutable commits or digests in a canonical `release-lock.json`, then bind the tested image digest to OCI metadata, an SBOM, and GitHub artifact provenance.

**Core technologies:**
- **Seafile CE 14 + CloudFile forks:** Runtime baseline — keep the `14.0.0-cf.0` reference line and pin Docker, Hub, Server, and upstream inputs to full commits.
- **Seahub generic OAuth2/OIDC:** Authentik relying-party path — reuse Authorization Code integration rather than build an Authentik-specific protocol.
- **authentik `2026.5.6`:** Qualified IdP fixture — pin all core/outpost images to matching digests; do not use deprecated `latest` tags.
- **Native Seafile multiple-storage architecture + MinIO:** Per-library local/S3-compatible routing — qualify only MinIO Server `RELEASE.2025-10-15T17-29-55Z` and `mc` `RELEASE.2025-08-13T08-35-41Z`, both by digest.
- **Seafile AI 14 + Redis + Metadata Server:** AI execution layer — configure external models through `seafile_ai_config.yaml`, resolve `seafileltd/seafile-ai:14.0-latest` to a qualified digest, and do not create a parallel AI backend.
- **MariaDB 11.4 and Redis 7-alpine:** Existing state/cache baseline — retain current deployment boundaries and record actual release digests.
- **Python 3.12 standard library + OCI/SLSA/GitHub attestations:** Release locking and evidence — canonical JSON avoids a new manifest framework while digest-bound provenance makes cross-repository results traceable.

Critical version rules: never release from branch refs, rolling service tags, empty commit fields, or unfixed GitHub Action references. MinIO Community is an archived compatibility fixture, not a recommended production platform; Seafile AI's rolling tag is only a discovery input; and Authentik core, worker, and outposts must advance together through supported release trains.

### Expected Features

**Must have (table stakes):**
- Correctness and security gates — no ACL-protected search/sync leakage, no fail-open authority errors, valid operation facts, generation-fenced locks, honest PASS/SKIP reporting, and native disabled baselines.
- Collaboration contract closure — registered OnlyOffice with mandatory matching JWT and idempotent callbacks, plus versioned local-edit descriptors and existing-file update/conflict semantics.
- Generic Authentik OAuth2/OIDC — exact HTTPS callback, stable subject identity, minimal claims, key/secret rotation, logout decision, outage behavior, and a tested local break-glass administrator.
- Directory/file tags and mutation audit — explicit lifecycle semantics and complete browser/API/sync/WebDAV mutation coverage with retention/export boundaries.
- Immutable release provenance — exact Docker/Hub/Server/upstream/service inputs tied to one tested image digest, SBOM, result manifest, and verified attestation.

**Should have (competitive):**
- User-selectable per-library storage classes — allowed native local or MinIO class selection with complete commit/FS/block migration, rollback, GC, and FSCK evidence.
- Secure local view/edit — one-time origin-bound tickets and a minimal Native Messaging bridge without browser cookies, long-lived tokens, or localhost HTTP.
- Permission-trimmed Seafile AI — operator-selected external LLMs through the official AI layer with data minimization, failure isolation, and egress controls.

**Defer (v2+):**
- External virtual-directory federation through OpenList/rclone — separate project with its own containment and credential threat model, initially read-only.
- S3 compatibility claims beyond MinIO — add a provider-specific lifecycle suite before naming another provider.
- Custom identity or AI services — extend Seahub OIDC and Seafile AI rather than duplicate native authorities.
- Bundling native clients with the server release — agent and browser extension remain independently signed/released against a versioned protocol.

### Architecture Approach

Use a layered, native-first extension with versioned cross-repository contracts. `cloudfile-docker` owns the immutable build/deploy/test control plane; Hub owns browser/API orchestration and the generic OIDC flow; Server owns final ACL, lock, mutation, and storage lifecycle decisions; local clients form a separately released minimal native bridge; optional services only produce candidates or transformations. Security-sensitive seams distinguish inactive native pass-through, active valid allow/deny, and active unavailable/malformed states; the last state fails closed.

**Major components:**
1. **`cloudfile-docker`** — release tuple, source/image assembly, generated configuration, shared contracts, Compose profiles, cross-repository acceptance, provenance, and operator documentation.
2. **`cloudfile-hub`** — Seahub UI/APIs, generic OAuth/OIDC, search post-filter orchestration, storage/tag/audit interfaces, callbacks, and local session issuance.
3. **`cloudfile-server`** — authoritative ACL/lock/write decisions, PREPARE/COMMITTED/ABORTED facts, effective-path filtering, storage routing/migration, GC/FSCK safety, and internal RPC.
4. **Local agent + Chrome extension** — short-lived descriptor handoff, safe native execution, download/edit/write-back, and conflict recovery across an explicitly versioned contract.
5. **Authentik, MinIO, SeaSearch/Metadata, OnlyOffice, and Seafile AI** — independently pinned optional services that never become CloudFile permission authorities.

Key patterns are native capability first, candidate-producer-not-authority, tri-state fail-closed security seams, versioned contracts before multi-repository changes, and destructive lifecycle state machines (`plan -> enumerate -> copy -> verify -> cut over -> observe -> separately authorize cleanup`).

### Critical Pitfalls

1. **Hub-only authorization** — enforce final ACL/write decisions in Server/fileserver across REST, sync, WebDAV, archive, and direct data paths; treat active authority failure as denial.
2. **Search or AI leaks through stale/candidate data** — apply one backend-independent current ACL evaluator before totals, snippets, serialization, cache, or model egress; block unsafe provider combinations.
3. **Mutable inputs and false-green CI** — build once from a complete lock, test the same image digest, pin actions/services, dispatch exact owning-repository SHAs, and keep SKIP distinct from PASS.
4. **Partial storage migration** — freeze writers, journal and verify commits/FS objects/blocks, switch mapping atomically, retain source data through rollback evidence, and authorize cleanup separately.
5. **Asynchronous contract and lifecycle drift** — version local/OnlyOffice contracts, authenticate and deduplicate callbacks, generation-fence saves/releases, and use durable idempotent facts/cursors for tags and audit.
6. **External-service success mistaken for safe integration** — test denial, outage, restart, revocation, upgrade/rollback, secret redaction, and disabled-native behavior for every capability.

## Implications for Roadmap

Based on the combined research, use seven dependency-ordered phases. The first phase deliberately combines the currently red security gates with known local/OnlyOffice contract blockers; this resolves the inconsistent ordering across the individual research files and follows the project decision that feature expansion cannot continue on a bypassable or internally inconsistent foundation.

### Phase 1: Security and Collaboration Contract Closure
**Rationale:** Current search isolation and mutation acceptance are red, sync can fail open, and known collaboration schemas/registration are broken. These defects invalidate later qualification evidence and must close first.
**Delivers:** Effective ACL trimming for SeaSearch/Meilisearch; fail-closed sync/RPC behavior; valid bulk-delete and mutation lifecycle facts; generation-fenced lock release; canonical preflight and honest PASS/SKIP reporting; OnlyOffice startup registration, mandatory JWT, idempotent generation-aware saves; versioned local descriptor/session schema and existing-file update/conflict behavior.
**Addresses:** Correctness/security gates, OnlyOffice, secure local actions, and the shared mutation/locking prerequisites for audit and AI.
**Avoids:** Hub-only authorization, search leakage, half-enabled capabilities, stale callbacks/unlocks, create-vs-update data loss, and compatibility claims based only on happy paths.

### Phase 2: Immutable Release Tuple and Cross-Repository Evidence
**Rationale:** Every later service and feature matrix needs attributable evidence from the exact code and image that will ship.
**Delivers:** Canonical `release-lock.json`; full Docker/Hub/Server/upstream/patch/service identities; one built image fanned out to matrices; exact-ref cross-repository dispatch; OCI labels, SBOM, result manifest, digest-bound attestation, and verified rollback identity.
**Uses:** Python 3.12 standard library, OCI annotations, SLSA v1 provenance, and GitHub artifact attestations.
**Avoids:** Moving refs/tags, mismatched E2E inputs, action drift, unsigned build metadata, and skipped tests reported as success.

### Phase 3: Generic Authentik OIDC Qualification
**Rationale:** Identity is independently deliverable once security semantics and evidence are trustworthy; no storage or metadata dependency justifies delaying it.
**Delivers:** Digest-pinned Authentik profile; strict Authorization Code flow; exact HTTPS redirect; `openid profile email`; stable `(issuer, subject)` binding; explicit property/group mapping; startup validation; key and secret rotation; disable/logout/outage behavior; desktop system-browser coverage where claimed; and local-admin recovery.
**Addresses:** Generic Authentik OAuth2/OIDC table stakes without a custom identity subsystem.
**Avoids:** Login CSRF/mix-up, incomplete token validation, email-based account collisions, claim-driven privilege widening, mass deprovisioning on outage, and IdP lockout.

### Phase 4: CE Per-Library Multi-Storage and MinIO Lifecycle
**Rationale:** Existing routing can be safely exposed only after authority error semantics and release evidence are fixed; migration must precede any production self-service claim.
**Delivers:** Policy-limited storage-class selection at library create/manage; validated stable `storage_id`; no silent fallback; pinned MinIO profile; offline journaled migration of commit/FS/block domains; read-back and history verification; atomic cutover; backup, rollback, GC/FSCK, and separately authorized source cleanup.
**Addresses:** User-selectable native per-library local/MinIO storage and operational lifecycle safety.
**Avoids:** Split-brain libraries, incomplete enumeration, early source deletion, unsafe online repair, and generic S3 compatibility claims.

### Phase 5: Tags and Audit Lifecycle Completion
**Rationale:** Tags and audit share the authoritative mutation vocabulary repaired in Phase 1 and should be finished together so their identity, retry, and reconciliation semantics agree.
**Delivers:** Explicit tag entry identity and bind/inherit/override/move/copy/delete/recover/version behavior; permission enforcement; durable idempotent mutation facts; complete browser/API/sync/WebDAV coverage; reconciliation cursors; bounded indexed queries; retention/archive/export/SIEM and deletion boundaries.
**Addresses:** Directory/file tags and mutation audit table stakes.
**Avoids:** Path/object identity mismatch, missed or duplicate events, Hub-only observation, unbounded tables, raw-content logging, and accidental claims of an immutable compliance ledger.

### Phase 6: Permission-Trimmed Seafile AI and External-LLM Controls
**Rationale:** AI consumes the ACL/search, metadata, and audit foundations from earlier phases and creates a new outbound data boundary; it should be the last runtime capability enabled.
**Delivers:** Digest-qualified official Seafile AI 14, Metadata Server, and Redis integration; deterministic OpenAI-compatible model stub; current ACL checks at retrieval/prompt/return/cache boundaries; HTTPS origin/network allowlists; secret injection; minimized payloads; bounded timeout/retry; no-content logs; provider policy; failure isolation; and zero egress when disabled.
**Addresses:** Permission-trimmed Seafile AI with operator-configurable external LLMs.
**Avoids:** Restricted or stale context egress, arbitrary-provider SSRF, credential/prompt logging, cross-user cache leakage, unapproved fallback, and AI failures affecting core file operations.

### Phase 7: MVP Qualification and Operational Release
**Rationale:** Support claims should be published only after one immutable tuple passes the combined capability, failure, upgrade, backup, restore, and rollback matrices.
**Delivers:** One digest-addressed release with all enabled capability results, service digests, provenance/SBOM verification, operator runbooks, tested disabled baselines, support boundaries, and rollback evidence.
**Addresses:** Coherent production-oriented CE extension MVP and immutable release provenance.
**Avoids:** Documentation outrunning executable evidence, per-capability success masking integration failures, and unsupported provider/scale claims.

### Phase Ordering Rationale

- Security containment and known cross-repository contract blockers come first because current failures invalidate confidentiality, consistency, and all later acceptance evidence.
- Immutable provenance follows immediately so Authentik, storage, tags/audit, and AI are each qualified against the same attributable artifact model.
- Authentik precedes storage because it has no storage dependency and establishes stable operator/user identity; storage then supplies the complete native-library lifecycle that metadata and AI consume.
- Tags and audit are grouped around one authoritative mutation vocabulary; AI follows because it depends on current permission trimming, reliable metadata, and bounded audit/egress semantics.
- External federation is excluded rather than appended: OpenList/rclone credentials, containment, availability, caching, and mutation semantics require a separate threat model and roadmap.

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 1:** Design the cross-language bulk permission/pagination contract and versioned local/OnlyOffice protocol; both are confidentiality- or integrity-sensitive seams.
- **Phase 3:** Inspect pinned Seahub code line by line for issuer, audience, signature/JWKS refresh, nonce, and PKCE S256 behavior; generic OAuth configuration alone does not prove OIDC conformance.
- **Phase 4:** Specify migration-journal durability, crash resume, pagination, reused/versioned objects, encryption metadata, checksum/read-back criteria, and restoration scale before cleanup.
- **Phase 5:** Decide tag entry identity from native Seafile primitives and define audit durability/retention product semantics before freezing schemas.
- **Phase 6:** Capture exact Seafile AI 14 request payloads and permission call sites, then qualify provider-specific retention, training, residency, and deletion policies.

Phases with standard patterns (skip standalone research-phase):
- **Phase 2:** Canonical lockfiles, OCI metadata, SBOM, SLSA/GitHub attestations, and exact-ref CI are well documented; implementation still needs normal threat review.
- **Phase 7:** This is execution of already defined matrices and release evidence, not a new technical integration, unless an unresolved operational target emerges.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Seafile, Authentik, AI, MinIO, OCI, SLSA, and GitHub recommendations use current official sources; exact CloudFile integration remains to be qualified. |
| Features | HIGH for scope; MEDIUM for market classification | Active requirements and defects are directly evidenced, but no fresh competitor survey validates which differentiators are market-leading. |
| Architecture | HIGH | Repository ownership and native Seafile boundaries are directly mapped; MinIO production-scale failure behavior and million-user posture are not certified. |
| Pitfalls | HIGH for known/standards risks; MEDIUM for untested failure modes | Current red gates and code defects are explicit; AI payloads, migration faults, log exposure, and worker-scale behavior need targeted capture/injection. |

**Overall confidence:** HIGH in the recommended roadmap order and architectural boundaries; MEDIUM in capability readiness until the proposed matrices pass.

### Contradictions and Resolutions

- **Collaboration ordering:** FEATURES/PITFALLS prioritize local actions and OnlyOffice before identity/storage, while ARCHITECTURE delays full collaboration until after tags/audit. Resolve this by closing all known registration, schema, authentication, update, and fencing blockers in Phase 1; defer only artifact packaging/signing polish to release qualification.
- **Generic OAuth versus OIDC guarantees:** Stack guidance configures Seahub's generic OAuth endpoints, while architecture/pitfall guidance requires nonce, PKCE, issuer, audience, and JWKS validation. Treat these as required qualification outcomes, not assumed current behavior; Phase 3 must inspect and test the pinned client.
- **MinIO positioning:** The architecture is provider-neutral, but the recommended MinIO Community build is archived. Use it only as the frozen milestone fixture and support boundary, never as evidence of broad S3 or long-term production suitability.
- **Seafile AI documentation line:** Version-14 research uses `seafile_ai_config.yaml`, while some upstream references and the image name are rolling/latest. The CE 14 contract wins; resolve the image tag to a tested digest and reject configuration claims derived only from newer docs.
- **Evidence versus readiness:** The codebase shows many partial capabilities, while FEATURES calls some table stakes and architecture diagrams show them wired. Preserve conservative status labels: present or composed is not qualified until the immutable negative/recovery matrix passes.

### Gaps to Address

- **OIDC versus generic OAuth behavior:** Research agrees on generic Seahub integration but does not prove the pinned implementation performs full OIDC validation. Phase 3 must either demonstrate issuer/audience/signature/nonce/PKCE behavior or narrow the support claim and add the missing standard seam.
- **Collaboration phase placement:** FEATURES/PITFALLS put local actions and OnlyOffice early, while ARCHITECTURE placed full collaboration after tags/audit. The roadmap resolves this by closing known registration/schema/authentication/update blockers in Phase 1; any remaining packaging/signing polish belongs in Phase 7, not after AI.
- **OnlyOffice version contract:** Deployment declares OnlyOffice 8.2 while official documentation reflects newer releases. Test 8.2 directly or deliberately upgrade and requalify; do not infer callback semantics.
- **Tag identity:** Path, content/object ID, and version each produce different move/copy/recovery behavior. Phase 5 must make an explicit product/schema decision before implementation.
- **MinIO support boundary:** The Community repository is archived and lacks current large-scale/failure certification. Treat the pinned build only as a frozen compatibility fixture and never generalize results to other S3 providers.
- **Seafile AI version/payload boundary:** Version-14 YAML configuration is authoritative for this baseline, while some research sources reference `latest`; pin an accepted 14 image digest and capture actual outbound requests before declaring egress controls complete.
- **External LLM policy:** Retention, training, residency, and deletion are provider-specific contractual facts outside CloudFile. Expose them as operator qualification/policy, not a generic privacy promise.
- **Operational limits:** Worker concurrency/backpressure, audit volume, migration duration, restore scale, and capacity are unmeasured. Define test envelopes and publish measured limits rather than extrapolating to large deployments.

## Sources

### Primary (HIGH confidence)
- [STACK.md](./STACK.md) — technology versions, immutable release inputs, Authentik/AI/MinIO qualification baselines, and provenance design.
- [FEATURES.md](./FEATURES.md) — table stakes, differentiators, anti-features, dependencies, and MVP priority.
- [ARCHITECTURE.md](./ARCHITECTURE.md) — component authority, data flow, patterns, phase dependencies, scalability posture, and research flags.
- [PITFALLS.md](./PITFALLS.md) — failure modes, detection matrices, phase warnings, uncertainties, and official-source aggregation.
- [PROJECT.md](../PROJECT.md) — authoritative scope, current red gates, constraints, active requirements, and exclusions.
- [Seafile 14 OAuth](https://manual.seafile.com/14.0/config/oauth/) and [multiple storage backends](https://manual.seafile.com/14.0/setup/setup_with_multiple_storage_backends/) — native identity and per-library storage contracts.
- [Seafile 14 AI extension](https://manual.seafile.com/14.0/extension/seafile-ai/) and [Metadata Server](https://manual.seafile.com/14.0/extension/metadata-server/) — versioned AI/model and metadata prerequisites.
- [Authentik OAuth2/OIDC provider](https://docs.goauthentik.io/add-secure-apps/providers/oauth2/) and [2026.5 release notes](https://docs.goauthentik.io/releases/2026.5/) — protocol, redirect, issuer, scope, grant, binding, and upgrade behavior.
- [RFC 9700](https://www.rfc-editor.org/rfc/rfc9700.html) — current OAuth security best practices.
- [ONLYOFFICE callback](https://api.onlyoffice.com/docs/docs-api/usage-api/callback-handler/) and [signature](https://api.onlyoffice.com/docs/docs-api/additional-api/signature/) documentation — asynchronous callback and JWT contracts.
- [OCI image annotations](https://github.com/opencontainers/image-spec/blob/main/annotations.md), [SLSA build provenance](https://slsa.dev/spec/v1.2/build-provenance), and [GitHub artifact attestations](https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/use-artifact-attestations) — digest-bound release evidence.

### Secondary (MEDIUM confidence)
- Current repository documentation and `.planning/codebase/` maps — authoritative for intended boundaries and observed code state, but production-readiness claims remain subordinate to executable gates.
- Current MinIO object/version documentation — useful for test design, but the archived Community fixture and exact deployment still require fault-injected lifecycle qualification.
- Seafile 13 backup/recovery guidance — used for durable backup principles where a dedicated version-14 page was unavailable; validate commands against the pinned CE 14 baseline.

---
*Research completed: 2026-08-11*
*Ready for roadmap: yes*
