# Architecture Patterns

**Domain:** Multi-repository Seafile CE 14 extension for secure enterprise file collaboration
**Project:** CloudFile CE Extension
**Researched:** 2026-08-11
**Confidence:** HIGH for current repository boundaries and Seafile/Authentik/Chrome patterns; MEDIUM for MinIO failure behavior at production scale

## Recommended Architecture

CloudFile should remain a layered extension of Seafile CE rather than becoming a parallel file platform. Native Seafile models and entry points own libraries, commits, FS objects, blocks, WebDAV, sync, OAuth login, metadata, search integration, office integration, and Seafile AI wherever the pinned CE 14 baseline provides them. CloudFile adds gated policy, lifecycle, configuration, and verification seams around those capabilities.

```text
 Build, release, deployment, and verification control plane
 ┌──────────────────────────────────────────────────────────────────────────┐
 │ cloudfile-docker                                                        │
 │ release tuple · source assembly · image · Compose · config generation   │
 │ shared contracts · feature status · cross-repository acceptance gates   │
 └───────────────────────────────┬──────────────────────────────────────────┘
                                 │ immutable refs + versioned contracts
                                 ▼
 Browser / API clients ──► cloudfile-hub (Seahub fork)
                           UI · HTTP APIs · generic OAuth/OIDC RP
                           provider orchestration · workers · local sessions
                                 │ authenticated identity + RPC
                                 ▼
 Sync / WebDAV / uploads ─► cloudfile-server (authoritative data plane)
                           final ACL/lock/write decisions · object lifecycle
                           repo operations · commit/FS/block storage routing
                                 │
                   ┌─────────────┼────────────────────┐
                   ▼             ▼                    ▼
             MariaDB/Redis   local storage       MinIO-verified S3

 Browser local-edit path (separately released)
 cloudfile-chrome-extension ──Native Messaging──► cloudfile-local-agent
       descriptor path only                       claim/download/open/write-back
                                                       │ short-lived capability
                                                       └────────► cloudfile-hub

 Optional external services
 Authentik ──generic OIDC──► Hub   SeaSearch/metadata/OnlyOffice/Seafile AI
                                      │ adapters and callbacks, never ACL authority

 Deferred beyond this milestone
 External-data federation (OpenList/rclone adapters, initially read-only)
```

The defining trust rule is: the layer that owns the mutable resource owns the final decision. Hub may preflight and improve errors, but Server must deny unauthorized file operations across browser, sync, WebDAV, fileserver, and direct RPC paths. Search and optional services may produce candidates or enrich data; they may never widen Server-authorized visibility. When an enabled security authority cannot decide, the operation fails closed. When the extension is disabled, the native CE behavior remains unchanged.

### Component Boundaries

| Component | Responsibility | Communicates With | Must Not Own |
|---|---|---|---|
| `cloudfile-docker` | Exact cross-repository release tuple, upstream pins, source/image assembly, Compose profiles, generated configuration, shared contracts, schema/API compatibility checks, integrated E2E and operator documentation | All repositories at build/test time; containers and optional services at deploy time | Runtime business logic, identity protocol implementation, or permission decisions |
| `cloudfile-hub` | Native Seahub reuse, browser UI, HTTP APIs, generic OAuth2/OIDC relying-party flow, stable claim mapping, provider selection, periodic work, search candidate post-filter orchestration, storage-class UI, tag/audit UI, OnlyOffice callbacks, local-session issuance | Browser, Authentik, Server RPC, Redis/MariaDB, optional services, local agent | A permission decision that sync, WebDAV, fileserver, or direct Server access can bypass |
| `cloudfile-server` | Authoritative library/file operations, ACL and lock decisions, PREPARE/COMMITTED/ABORTED lifecycle, effective-path filtering primitives, commit/FS/block storage routing, `RepoStorageId`, migration/GC/FSCK safety, CloudFile DDL and internal RPC | Hub, fileserver, seafdav, MariaDB, Redis, local storage, MinIO | UI, OAuth browser flow, directory synchronization, or network-dependent identity decisions |
| `cloudfile-local-agent` | Trusted native host, strict Native Messaging input validation, origin allowlist, one-time ticket claim, private workspace, safe app selection, bounded download/heartbeat/write-back, generation-aware conflict handling | Chrome extension over stdio; Hub over HTTPS | Browser cookies, long-lived Seafile tokens, arbitrary server-supplied executables, or server authorization |
| `cloudfile-chrome-extension` | Manifest V3 download observation and delivery of a completed `.cloudfile` descriptor path to one allowlisted native host | Chrome downloads/storage APIs and Native Messaging | File content parsing/editing, credentials, write-back, localhost server, or application discovery |
| Authentik | Upstream enterprise identity brokering, authentication policy/MFA, application access policy, standards-based OIDC provider | Enterprise identity sources and Hub's generic OAuth client | CloudFile-specific protocol, Seafile authorization, or implicit group synchronization |
| MinIO | The only S3-compatible implementation qualified in this milestone | Server storage clients and test tooling | A blanket compatibility claim for AWS S3, Ceph RGW, or other vendors |
| SeaSearch / Metadata Server / OnlyOffice / Seafile AI | Native or official optional capability services | Hub/Server through their existing adapters | Authoritative ACL decisions or independent CloudFile data models when Seafile already owns one |

### Security Authorities and Failure Semantics

| Decision | Authority | Friendly Pre-check | Failure Rule |
|---|---|---|---|
| Login identity | Seahub generic OAuth/OIDC client, backed by Authentik | Generated endpoint/claim validation at startup | New login fails; never auto-create from malformed/missing required claims; preserve a tested local break-glass administrator |
| Group/directory state | Hub SSO directory provider and last valid snapshot | Worker status/API | Provider outage or malformed snapshot retains prior state; it is never interpreted as an empty directory |
| Read/list/sync/WebDAV visibility | Server ACL provider and protocol-specific Server/fileserver gates | Hub API/UI check | If ACL is enabled and authority/RPC/schema is unavailable or malformed, deny; never treat error as unrestricted |
| Search visibility | Server-backed effective permission evaluator applied to every candidate | Hub can reject unsafe provider combinations at startup | Filter failure denies the response; totals/pagination are computed from authorized results, not leaked candidates |
| Write/lock eligibility | Server file-operation and generation-fenced lock provider | Hub action availability | PREPARE uncertainty denies; post-commit audit/index failures do not roll back an already committed write |
| Storage mapping | Server `RepoStorageId` plus validated storage-class registry | Hub allowed-class UI | Unknown/unavailable class or backend is an error; never fall back to another class or reinterpret transport failure as not-found |
| Local write-back | Server update operation plus expected file/head and lock generation | Hub validates session/capability | Expired/replayed ticket, stale generation, changed base, or ambiguous result returns conflict/denial; never create a sibling as a fallback |
| OnlyOffice save | JWT-authenticated Hub callback plus Server update/lock generation | Startup requires complete matching configuration | Missing secret, invalid token, stale generation, or malformed callback denies; retries are idempotent |

### Data Flow

#### Interactive File Request

1. Caddy/nginx route browser/API traffic to Hub and transfer/sync/WebDAV traffic to native Seafile entry points.
2. Hub authenticates the user and may perform a user-facing permission pre-check.
3. The request enters Server or fileserver for the final ACL/lock/write decision.
4. Server chains enabled providers using a never-widen rule and routes native commit, FS, and block objects to the mapped backend.
5. Disabled providers are pass-through; an enabled but unhealthy security provider denies with a diagnosable error.

#### Authentik Login

1. Docker generates Seahub's native OAuth settings from secrets and exact HTTPS endpoints; it does not add an Authentik-specific runtime adapter.
2. Hub uses Authorization Code as a confidential client, validates callback state, exchanges the code server-side, and obtains identity claims.
3. The stable Authentik `sub` maps to Seahub's external UID; `email` is contact data, not the durable identity key.
4. Authentik's per-provider issuer/discovery/JWKS endpoints are configuration evidence. The phase must verify whether the pinned Seahub flow validates issuer/JWT through discovery; unsupported guarantees must be recorded rather than inferred.
5. Authentik outage blocks new OIDC login but does not delete bindings or directory state. Local administrative recovery remains independently testable.

#### Library Creation and Storage Migration

1. Hub lists only storage classes allowed by native/CloudFile role policy and submits a stable `storage_id` at library creation.
2. Server validates the ID against the startup-loaded class registry and writes the library mapping; absence uses the single declared default.
3. All library commit/FS/block reads and writes resolve through that mapping; virtual libraries follow their origin library.
4. Migration runs offline: enumerate all three object domains, copy, read back/verify, then atomically update the database mapping.
5. Source objects remain intact through rollback evidence. Cleanup is a separate destructive operation after backup and a second verification pass.

#### Search

1. Native SeaSearch or a selected adapter returns candidate documents.
2. Hub normalizes repository/path identities and requests a bulk effective-permission decision from Server.
3. Unauthorized candidates and all associated names, paths, snippets, facets, and counts are removed.
4. The API fills pages from authorized candidates or returns a bounded partial-page contract without exposing the unfiltered total.
5. Until this path is green for a provider, startup rejects that provider when directory ACL is enabled.

#### Local Edit

1. Hub issues a short-lived one-time descriptor containing origin, expiry, mode, safe display name, and claim ticket; no browser cookie or content credential is embedded.
2. The extension forwards only the completed descriptor path to its allowlisted Native Messaging host.
3. The agent validates size/schema/origin, claims the ticket over HTTPS, downloads into a private workspace, and starts a locally configured/discovered application without a shell.
4. Edit sessions heartbeat and update the existing file with the expected base/head and lock generation. View sessions receive no write capability.
5. Hub/Server reject replay, stale generation, or concurrent modification. The agent keeps recoverable local content and reports a conflict rather than silently overwriting or creating another file.

#### Release and Evidence

1. Docker resolves immutable Docker/Hub/Server commits plus upstream pins into one release tuple.
2. The tuple and contract/schema versions are embedded in build metadata and the image, and attached to every CI result.
3. One image is built per tuple, then baseline and isolated capability jobs fan out against that exact image.
4. A capability advances only when native-disabled baseline, positive behavior, negative/failure controls, upgrade/rollback, and relevant protocol matrices pass.

## Patterns to Follow

### Pattern 1: Native Capability First, Gated Extension Second

**What:** Reuse Seafile's data model and public behavior, adding a small provider/hook/config seam only for missing CE behavior.

**When:** Every feature proposal, especially OAuth, storage classes, metadata, office, search, and AI.

**Example:** Authentik is configured through Seahub's generic OAuth client; CloudFile adds configuration generation and acceptance tests, not a custom Authentik protocol stack.

### Pattern 2: Tri-State Security Seam

**What:** Distinguish `inactive` (native pass-through), `active and allowed/denied`, and `active but unavailable/malformed`.

**When:** ACL, lock, write lifecycle, storage registry, callback authentication, and any RPC used for final authorization.

```text
inactive                 -> preserve native CE decision
active + valid allow     -> continue
active + valid deny      -> deny
active + error/malformed -> deny and emit a targeted diagnostic
```

This pattern should replace the current Go sync behavior that collapses RPC error and unrestricted access into the same empty result.

### Pattern 3: Versioned Cross-Repository Contract

**What:** Define wire/schema semantics in Docker-owned documents and executable fixtures before changing Hub, Server, or clients.

**When:** ACL results, file-operation vocabulary, local-session descriptors, lock generations, search-filter batches, storage mapping/migration journals, and release provenance.

**Example:** A local-session schema version is consumed by Hub, extension, and agent; unsupported major versions are rejected instead of guessed.

### Pattern 4: Candidate Producer Is Not an Authority

**What:** Search, AI, metadata, and external services may produce candidate data only. A local authoritative permission trim runs before user-visible output or model egress.

**When:** Search results, AI retrieval, metadata/tag browse, previews, exports, and future federation.

**Example:** SeaSearch returns candidates; Server evaluates effective ACLs; Hub serializes only the authorized subset.

### Pattern 5: Destructive Lifecycle as a State Machine

**What:** Separate plan, dry run, copy, verify, switch, observe, and cleanup with a durable journal and explicit rollback point.

**When:** Storage migration, schema upgrades, GC/FSCK repair, identity-provider migration, and release rollback.

```text
PLANNED -> ENUMERATED -> COPIED -> VERIFIED -> MAPPING_SWITCHED -> OBSERVED
                    \---------------- rollback -----------------/
OBSERVED + backup approval -> SOURCE_CLEANUP
```

### Pattern 6: Minimal Native Client Bridge

**What:** Keep the browser extension event-only and move filesystem/application work into an installed native host with OS permissions and explicit origin trust.

**When:** Local view/edit on every supported desktop platform.

Chrome's native host manifest provides a non-wildcard extension allowlist; CloudFile must additionally validate every message because the extension-to-agent boundary is not an authorization substitute.

## Dependency-Ordered Roadmap Phases

| Order | Phase | Primary Owners | Depends On | Architectural Exit Condition |
|---|---|---|---|---|
| 1 | Security Authority Closure and Red-Gate Repair | Server, Hub, Docker | Existing CE 14 baseline | Go sync fails closed on active ACL outage/malformed replies; search is ACL-trimmed or blocked; batch delete/file-operation route emits valid lifecycle facts; lock release requires generation; combined negative E2E is green |
| 2 | Immutable Release Tuple and Cross-Repo Evidence | Docker, Hub, Server | Phase 1 semantics | Exact three-repository commits and contract/schema versions are embedded; Hub/Server PRs dispatch the relevant image E2E against their own SHA; preflight runs in CI; PASS and SKIP are distinct |
| 3 | Authentik through Generic OIDC | Docker, Hub | Phase 2 traceable image | Pinned stable Authentik, exact redirect URI, Authorization Code, stable `sub`, application binding, claim changes, logout decision, secret rotation, outage, TLS and local-admin recovery pass; no custom identity protocol is introduced |
| 4 | Native Storage-Class Self-Service and MinIO Lifecycle | Hub, Server, Docker | Phase 2; Phase 1 storage/error semantics | Allowed class selection at creation/management uses native IDs; mapping never silently falls back; offline migration, complete enumeration, read-back, GC/FSCK, backup and rollback pass against pinned MinIO only |
| 5 | Tags and Audit Closure | Hub, Server, Docker | Phase 1 write lifecycle; Phase 2 evidence | Tag bind/inherit/move/delete/recover permissions and operation audit across Web/API/sync/WebDAV pass; retention/export boundary is explicit |
| 6 | Collaboration Contract and Local Clients | Server, Hub, local agent, Chrome extension, Docker | Phases 1-2; generation-fenced locks | OnlyOffice registration/JWT/idempotent save is complete; local descriptor/API matches clients; existing-file update, heartbeat, retry, stale generation and conflict recovery pass; signed client artifacts are tied to a compatible protocol version |
| 7 | Seafile AI Permission and Egress Closure | Hub, Server, Docker | Phases 1, 5; native metadata/search ready | Official Seafile AI remains the execution layer; retrieval is permission-trimmed; external LLM egress policy, secrets, failure isolation and audit pass; no parallel AI backend is created |
| 8 | MVP Qualification and Operational Release | Docker and all runtime owners | Phases 3-7 | One immutable tuple passes baseline plus every enabled-capability/failure matrix; optional images are digest-pinned; upgrade, backup, restore and rollback evidence matches published support claims |

**Ordering rationale:** Phase 1 removes active confidentiality and consistency hazards. Phase 2 makes every later result attributable to one build. Authentik and storage are then independently deliverable foundations; they can be developed in parallel, but neither should ship without Phase 2. Tags/audit depend on the write lifecycle. Collaboration depends on both lifecycle and lock fencing across five repositories. AI is last among runtime features because it consumes permissions, search, metadata, and audit. Release qualification follows all enabled capabilities.

**Explicit deferral:** External-data federation, OpenList/rclone adapters, virtual directories, write-through external content, and federation-backed AI libraries do not enter these phases. They require a separate threat model and initially read-only project after this MVP.

### Phase-to-Component Change Matrix

| Phase | Docker | Hub | Server | Local Agent | Chrome Extension |
|---|---|---|---|---|---|
| 1 | Shared semantics and combined E2E | Search post-filter orchestration | ACL/sync/fileop/lock authority fixes | — | — |
| 2 | Release lock, image fan-out, CI dispatch | Report exact SHA/contracts | Report exact SHA/contracts | Protocol compatibility metadata only | Protocol compatibility metadata only |
| 3 | Authentik profile fixture, secrets/config, E2E | Native generic OAuth/OIDC and recovery UI | Resolved identity only | — | — |
| 4 | MinIO-only profile and lifecycle E2E | Allowed storage-class UI/API | Mapping, routing, migration, GC/FSCK | — | — |
| 5 | Cross-protocol matrices | Tag/audit UI/API/query | Mutation facts and authoritative permissions | — | — |
| 6 | OnlyOffice and browser/agent E2E orchestration | Sessions, callbacks, idempotency | Update/lock generation authority | Trusted execution/write-back | Descriptor-path handoff only |
| 7 | Official service configuration and egress tests | Native Seafile AI orchestration | Permission/filter primitives | — | — |
| 8 | Immutable release and operational evidence | Version compatibility | Version compatibility | Signed release | Signed package/store release |

## Anti-Patterns to Avoid

### Hub-Only Authorization

**What:** Hide UI/actions or deny only in Seahub while sync, WebDAV, fileserver, or direct Server paths remain reachable.

**Why bad:** It creates protocol-specific bypasses.

**Instead:** Put the final rule in Server/fileserver and retain Hub checks only for usability.

### Error-as-Absence or Error-as-Unrestricted

**What:** Convert ACL RPC error to an empty restriction, storage transport error to object-not-found, or directory-provider failure to an empty snapshot.

**Why bad:** Availability failures become privilege expansion, data loss, or mass deprovisioning.

**Instead:** Carry typed active/inactive/error states across every authority boundary and fail closed when active.

### Compose Profile Equals Feature Completion

**What:** Treat a running Authentik, MinIO, OnlyOffice, metadata, search, or AI container as proof that the capability works.

**Why bad:** Topology does not prove application registration, authentication, lifecycle, authorization, recovery, or user workflow.

**Instead:** Require an active-provider assertion plus positive, negative, outage, restart, and rollback tests.

### Generic “S3-Compatible” Support Claim

**What:** Infer other provider compatibility from successful MinIO object PUT/GET.

**Why bad:** Addressing, signatures, pagination, multipart cleanup, error codes, consistency, and lifecycle semantics differ.

**Instead:** Publish MinIO-only qualification and add a full provider suite before naming another provider.

### Moving Refs or Rolling External Images

**What:** Build releases from `dev`, `latest`, or `testing` without resolving immutable identities.

**Why bad:** The shipped binaries and prior evidence cannot be reproduced.

**Instead:** Resolve commits/digests before build, embed the tuple, and make CI results tuple-addressed.

### Privileged Browser Extension

**What:** Put content transfer, credentials, application discovery, or editing logic in the extension, or expose a localhost HTTP listener.

**Why bad:** It broadens the web-to-desktop attack surface and complicates secret handling.

**Instead:** Keep the extension a minimal Native Messaging bridge and put trusted operations in the installed agent.

### Parallel Replacement Services

**What:** Add independent AI, metadata, identity, storage, or federation models before the native Seafile module is exhausted.

**Why bad:** Duplicate authorities drift and multiply upgrade/permission work.

**Instead:** Extend the native module with a gated seam; split federation into its already-deferred independent project.

## Scalability Considerations

These are architecture postures, not certified capacity claims.

| Concern | At 100 Users | At 10K Users | At 1M Users |
|---|---|---|---|
| Permission evaluation | Direct authoritative DB checks are acceptable | Revision-keyed immutable ACL snapshots with immediate invalidation; bulk search filter RPC; latency metrics | Reassess CE suitability and upstream cluster architecture; do not introduce an eventually consistent allow cache without a proof model |
| Search | Native engine plus per-result permission trim | Over-fetch bounded candidate batches; durable index cursors; authorized pagination semantics | Dedicated search tier and bulk policy service may be necessary, but Server remains source of truth |
| Background work | One `cf-worker` process | Durable cursors, per-task leases, backpressure, lag/error metrics | Queue/worker partitioning with idempotent ownership; optional-service failures remain isolated |
| Storage | Local or one MinIO-qualified class | Multiple native storage classes, offline journaled migration, versioned backup and restore drills | Distributed object storage and Seafile-supported cluster design; qualify the exact provider before claims |
| Audit | Indexed relational queries and bounded retention | Partition/archive/export by explicit policy | External SIEM/warehouse for long retention; CloudFile audit is not silently promoted to an immutable compliance ledger |
| Local clients | Direct Hub sessions | Rate-limited ticket issuance, protocol compatibility windows, signed auto-update channels | Regional download endpoints may be needed; tickets remain origin-bound and short lived |
| Release E2E | Sequential matrices acceptable | Build one image and fan out isolated capability jobs | Tiered deterministic suites plus scheduled scale/fault tests; never drop the negative security matrix |

## Research Flags for Later Phases

- **Phase 1 — HIGH priority:** Design the bulk effective-permission RPC and authorized pagination contract before implementing search filtering. This is a cross-language, confidentiality-sensitive seam.
- **Phase 3 — HIGH priority:** Inspect the pinned Seahub OAuth implementation for issuer/JWKS/ID-token validation and PKCE support. Authentik supports discovery and PKCE, but current project evidence only proves explicit endpoints, state, code exchange, and user-info mapping.
- **Phase 4 — HIGH priority:** Define migration journal durability, crash-resume behavior, checksum/read-back criteria, and restore drill scale before allowing destructive source cleanup.
- **Phase 6 — HIGH priority:** Version the Hub/agent/extension session contract and threat-model descriptor replacement, origin confusion, ticket replay, stale generations, and installer/update trust.
- **Phase 7 — HIGH priority:** Define permission trimming and data-egress policy at the exact Seafile AI retrieval and external-LLM call sites.
- **Federation — separate project:** Threat-model path containment, credentials, remote mutation, caching, history, availability, and per-adapter semantics before any CloudFile mount.

## Sources

### Official External Sources

- [Seafile 14 OAuth Authentication](https://manual.seafile.com/14.0/config/oauth/) — HIGH confidence: native OAuth client settings, exact redirect URL, provider identity, and stable external UID mapping.
- [Seafile 14 Docker Overview](https://manual.seafile.com/14.0/setup/overview/) — HIGH confidence: official core/optional service topology.
- [Seafile 14 Multiple Storage Backends](https://manual.seafile.com/14.0/setup/setup_with_multiple_storage_backends/) — HIGH confidence: library-granularity mapping, native storage classes, user/role/ID mapping policies, and migration model.
- [Seafile 14 Backend Data Migration](https://manual.seafile.com/14.0/setup/migrate_backends_data/) — HIGH confidence: offline migration sequencing and S3 signature requirements.
- [Authentik OAuth2/OIDC Provider](https://docs.goauthentik.io/add-secure-apps/providers/oauth2/) — HIGH confidence: Authorization Code, PKCE support, exact redirect validation, per-provider issuer, discovery/JWKS/end-session endpoints, and scope behavior.
- [Authentik 2026.5 Release Notes](https://docs.goauthentik.io/releases/2026.5/) — HIGH confidence for the selected release train; exact patch pin remains a project release decision.
- [Chrome Native Messaging](https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging) — HIGH confidence: native-host stdio boundary and non-wildcard extension origin allowlist.
- [Chrome Manifest V3](https://developer.chrome.com/docs/extensions/develop/migrate/what-is-mv3) — HIGH confidence: service-worker model and prohibition on remotely hosted extension code.
- [MinIO Objects and Versioning](https://docs.min.io/aistor/administration/objects-and-versioning/) — MEDIUM confidence for this CE validation context: official current object/version behavior, but production topology and failure behavior require tests against the exact pinned MinIO build.

### Repository Evidence

- `.planning/PROJECT.md` and `.planning/codebase/{ARCHITECTURE,CONCERNS,INTEGRATIONS,STACK,STRUCTURE,TESTING}.md` — HIGH confidence for current ownership, active requirements, known defects, and test signals as inspected on 2026-08-11.
- `docs/architecture.md`, `docs/features/sso-authentik.md`, `docs/features/storage-backends.md`, and `docs/features/file-collaboration.md` — HIGH confidence for current intended boundaries; completion claims remain subordinate to executable gates.

## Confidence Notes and Gaps

- **Current component boundaries: HIGH.** They are directly evidenced by the five repositories and existing build/runtime maps.
- **Native-first recommendation: HIGH.** Official Seafile 14 documentation confirms native OAuth and multiple-storage concepts, while repository inspection identifies the exact CE fork additions.
- **Authentik architecture: HIGH for provider configuration, MEDIUM for CloudFile compliance.** Authentik's official behavior is clear; the current Seahub client still needs exact issuer/JWKS/PKCE capability verification.
- **MinIO architecture: MEDIUM.** Current E2E validates important happy-path lifecycle behavior, but there is no scale, interruption, disaster-restore, or systematic fault-injection evidence.
- **Million-user posture: LOW as a product capacity claim.** The table gives decision boundaries only; this single-host CE reference has no evidence for that scale.
