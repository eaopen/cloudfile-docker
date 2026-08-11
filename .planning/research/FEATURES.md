# Feature Landscape

**Domain:** Production-oriented Seafile CE 14 extension milestone
**Researched:** 2026-08-11
**Confidence:** HIGH for project scope and current implementation state; MEDIUM for ecosystem expectations because this classification is based on project/codebase evidence rather than a new competitor survey

## Table Stakes

Features users expect. Missing = product feels incomplete or unsafe to operate.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Correctness and security gates | A production file platform cannot expose ACL-protected names/content, fail open during authorization outages, or ship with red mutation-path acceptance tests. | High | First release gate. Fix search ACL trimming, sync fail-closed behavior, file-operation route/fact coverage, lock generation fencing, local/CI gate parity, and skipped-test reporting before widening enablement. |
| OnlyOffice integration | Browser-based office editing is expected in a collaborative file platform, but it is usable only when registration, configuration, callback authentication, retry idempotency, and locking agree end to end. | High | Register the capability at Hub startup; require matching non-empty JWT configuration; generation-fence callback releases; verify save, retry, conflict, and lock lifecycle in a real container matrix. |
| Generic Authentik OAuth2/OIDC | Enterprise deployments expect standards-based SSO, secure claim mapping, logout/session behavior, and an outage-recovery administrator. | Medium | Use Seahub's generic Authorization Code/OIDC path. Validate against the latest stable Authentik, including discovery/configuration, redirect and issuer/audience checks, group/claim mapping boundaries, secret rotation, logout, and local-admin recovery. |
| Directory and file tags | Metadata attached only to definitions is incomplete; users expect binding to files/directories and predictable behavior through rename, move, recovery, and permission changes. | High | Complete binding, inheritance semantics, move/recovery behavior, authorization, and UI/API coverage. Keep semantics aligned with native Seafile metadata rather than creating a parallel taxonomy engine. |
| Mutation audit coverage | Administrators need attributable records for file and directory changes across browser, API, sync, and WebDAV paths. | High | Cover create/update/delete/move/copy/rename/recover and denied or aborted operations as explicitly specified. Define retention, export, indexing, pagination, and the boundary between operational history and a compliance ledger. |
| Immutable release provenance | Operators must know exactly which Docker, Hub, Server, upstream, schema, and extension-contract revisions produced an image and its CI evidence. | Medium | Replace moving product refs for release builds with one immutable tuple; embed it in build/image metadata; bind E2E results and rollback instructions to that tuple. |

## Differentiators

Features that set the product apart. Not universally expected, but valuable when the table-stakes foundation is green.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Secure local view/edit actions | Opens Seafile content in installed desktop applications through a one-time ticket and Native Messaging bridge without exposing browser cookies, long-lived tokens, or a localhost HTTP service. | High | Fix the Hub/frontend response contract and use update rather than create semantics for write-back. Verify descriptor download, claim, app launch, heartbeat, stable-write detection, conflict handling, expiry, and stale-generation refusal across Hub, Chrome extension, and local agent. Keep client releases independent from Docker. |
| User-selectable per-library storage classes | Lets CE users place each library on an allowed local or MinIO-backed class while retaining normal Seafile behavior and operator control. | High | Add safe create/manage selection atop existing routing. Migration, rollback, GC, and FSCK must enumerate and verify commit, filesystem-object, and block data as one lifecycle. Claim compatibility only for MinIO in this milestone. |
| Permission-trimmed Seafile AI with external LLM choice | Reuses Seafile's AI/indexing path while allowing operator-selected model endpoints, creating value without a second AI backend or duplicated permission model. | High | Depends on metadata/Redis and trustworthy ACL trimming. Add provider configuration, disabled/failure behavior, request and result authorization, data-egress controls, audit boundaries, and tests for unavailable/malformed external LLM responses. |

## Anti-Features

Features to explicitly NOT build in this milestone.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| External virtual-directory federation | OpenList/rclone adapters, credential isolation, containment, virtual mounts, and AI ingestion form a separate high-risk system and would distract from closing current security and lifecycle gaps. | Defer federation to the independent later project; keep this milestone limited to native Seafile libraries and the declared storage classes. |
| Custom Authentik protocol or Authentik-specific identity subsystem | It increases security and maintenance surface while reducing interoperability. | Configure Authentik through standard OAuth2/OIDC and Seahub's existing identity seams. |
| S3-provider compatibility claims beyond MinIO | “S3 compatible” does not guarantee identical signatures, pagination, consistency, or lifecycle behavior; untested claims put migration and recovery at risk. | Keep the backend architecture provider-neutral, but publish support only for the MinIO matrix until each provider has its own suite. |
| Independent AI backend | It duplicates Seafile AI's indexing, permissions, configuration, and failure-handling architecture. | Reuse Seafile AI and expose configurable external LLM providers with explicit egress controls. |
| Bundling the native local editor into the Docker/Hub release | It collapses browser, server, and desktop trust boundaries and makes cross-platform signing/release management inseparable from the server image. | Release the Chrome extension and local agent independently against a versioned session protocol. |
| Capability expansion while foundational gates are red | New enabled paths cannot be trusted while search isolation, sync fail-closed behavior, mutation facts, or exact release evidence are unresolved. | Keep affected combinations default-off and finish the correctness/provenance gates first. |

## Feature Dependencies

```text
Correctness/security gates -> every production capability claim
Immutable release provenance -> trustworthy cross-repository CI evidence -> release

Correctness/security gates -> lock/write lifecycle correctness
lock/write lifecycle correctness -> secure local view/edit actions
lock/write lifecycle correctness -> OnlyOffice save/callback lifecycle

Storage routing foundation -> allowed storage-class policy -> library create/manage selection
library selection -> verified offline migration + rollback -> GC/FSCK safety

Native metadata service -> tag binding semantics -> move/recovery/permission coverage
write lifecycle coverage -> complete mutation audit -> retention/export boundaries

Generic OIDC configuration -> Authentik validation -> claim/logout/recovery coverage

Effective ACL trimming + metadata/Redis -> Seafile AI integration
Seafile AI integration -> external LLM failure handling + egress controls + audit

Federation is intentionally outside this graph for the current milestone.
```

## MVP Recommendation

Prioritize:

1. **Correctness/security gates and immutable provenance** — establish a green, attributable foundation before feature enablement.
2. **Local actions and OnlyOffice** — close known contract, write-back, authentication, and fencing defects with end-to-end evidence.
3. **Generic Authentik OIDC** — qualify the standard identity path and recovery behavior without custom protocol work.
4. **Per-library local/MinIO storage selection** — expose the existing routing safely, then prove migration, rollback, GC, and FSCK lifecycle behavior.
5. **Tags and audit completeness** — finish cross-operation semantics and operational boundaries across every mutation protocol.
6. **Seafile AI with external LLM providers** — enable only after permission trimming, metadata prerequisites, egress policy, and failure isolation are proven.

Defer: **External virtual-directory federation** — it is an independent later project and is not required to validate this milestone's native-library MVP.

## Sources

- `.planning/PROJECT.md` — authoritative active requirements, constraints, scope exclusions, and milestone decisions (HIGH confidence).
- `.planning/codebase/ARCHITECTURE.md` — repository ownership, runtime boundaries, permission/write flows, and capability dependencies (HIGH confidence).
- `.planning/codebase/CONCERNS.md` — current defects, security risks, recommended ordering, missing completion evidence, and explicit rewrite hazards (HIGH confidence).
- `.planning/codebase/INTEGRATIONS.md` — current Authentik/OIDC, OnlyOffice, storage, metadata, AI, and local-client integration state (HIGH confidence).
- `.planning/codebase/STACK.md` — current runtime/service versions and repository boundaries (HIGH confidence).
- `.planning/codebase/STRUCTURE.md` — authoritative implementation and verification locations (HIGH confidence).
- `.planning/codebase/TESTING.md` — current green/red acceptance evidence and missing E2E matrices (HIGH confidence).

