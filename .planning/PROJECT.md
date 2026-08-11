# CloudFile CE Extension

## What This Is

CloudFile is a multi-repository extension of Seafile CE 14 for organizations that need production-oriented identity, permissions, storage, collaboration, audit, metadata, search, AI, and local-file workflows without replacing capabilities that Seafile already provides. `cloudfile-docker` is the release, deployment, specification, and cross-repository verification authority; runtime changes live in the Hub, Server, local-agent, and browser-extension repositories that own them.

## Core Value

Deliver a coherent, secure, independently verifiable CE extension MVP whose capabilities compose correctly across browser, API, sync, WebDAV, Server, storage, and optional-service boundaries.

## Requirements

### Validated

- ✓ Reproducible Seafile CE 14 source assembly, image construction, Compose deployment, and baseline smoke verification — existing
- ✓ Feature-gated Hub and Server extension registries preserve native CE behavior when disabled — existing
- ✓ Server-enforced directory ACL foundation and shared ACL/file-operation contracts exist across Python, C, and Go — existing
- ✓ Administrative per-repository multi-storage routing with local and S3-compatible backends exists; MinIO is the only declared S3 verification baseline — existing
- ✓ Audit event capture/query, metadata/tag definitions, search adapters, SSO adapters, locking, local actions, and AI integration have partial implementations with explicit maturity states — existing
- ✓ Local editing delivery is separated into `cloudfile-local-agent` and `cloudfile-chrome-extension` — existing

### Active

- [ ] Restore all currently red cross-repository acceptance gates and prevent ACL-protected data from leaking through search or sync failure paths
- [ ] Complete local-action and OnlyOffice registration/authentication contracts with end-to-end verification
- [ ] Integrate the latest stable Authentik through standard OAuth2/OIDC flows and recommended security practices, without a custom identity protocol
- [ ] Let CE users choose an allowed storage class when creating or managing a library, with safe lifecycle, migration, GC/FSCK, rollback, and MinIO-only S3 compatibility claims
- [ ] Complete directory/file tag binding, inheritance/move/recovery behavior, and permissions coverage
- [ ] Complete directory/file operation audit coverage across mutation paths and protocols, with defined retention and export boundaries
- [ ] Reuse Seafile AI with configurable external LLM providers, permission trimming, failure handling, and data-egress controls
- [ ] Pin one immutable cross-repository release tuple and make CI results traceable to it

### Out of Scope

- A parallel replacement for existing Seafile capabilities — extend or integrate the native module first
- Custom Authentik authentication protocols — use generic OAuth2/OIDC
- Production compatibility claims for S3 providers other than MinIO — add provider suites before expanding claims
- Bundling local native editing into the Docker/Hub repository — keep the agent and Chrome extension independently released
- External virtual-directory federation in this milestone — implement later as the independent CloudFile external-data federation project using OpenList/rclone adapters, initially read-only, for AI knowledge libraries and virtual mounts
- An independent AI backend — reuse Seafile AI and external LLM configuration

## Context

- The project spans `cloudfile-docker`, `cloudfile-hub`, `cloudfile-server`, `cloudfile-local-agent`, and `cloudfile-chrome-extension`; each repository remains authoritative for its own layer.
- Current integrated verification has two visible red paths: search isolation returns cross-user results, and batch delete/file-operation verification reaches no valid route or fact. Upstream patch registration is now warning-only and its replacement checks pass remotely.
- Code inspection found two small but blocking collaboration defects: the Hub frontend expects `session.file.name` although the issued session omits `file`, and the OnlyOffice capability defines `register()` but is not registered by Hub startup.
- Security-sensitive permission decisions must be enforced below Seahub so sync, WebDAV, fileserver, and direct Server paths cannot bypass them. Search results need backend-independent effective ACL filtering.
- Capability status remains conservative: implementation presence is not production readiness. A capability advances only after a reproducible integrated matrix passes.

## Constraints

- **Baseline**: Seafile CE 14 is the current reference baseline; upstream changes require explicit review and reproducible source pins.
- **Architecture**: Prefer existing Seafile modules and APIs; CloudFile code adds extension seams and support capabilities.
- **Security**: Permission checks fail closed when an enabled authority is unavailable or produces malformed state; disabled extensions preserve native CE behavior.
- **Identity**: Use the latest stable Authentik and standard OAuth2/OIDC best practices; no custom protocol.
- **Storage**: Support per-library storage selection and S3-compatible architecture, but verify and claim only MinIO in this milestone.
- **Delivery**: Complete an architecturally coherent MVP before broadening providers or adding secondary differentiators.
- **Operations**: Destructive storage migration/cleanup requires dry run, complete enumeration, verification, backup, and rollback evidence.
- **Documentation**: `cloudfile-docker` owns substantive product/release documentation; workspace-root `README.md` is only a local introduction and is not a product-document authority.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Restore failing acceptance and close security/contract blockers before feature expansion | A red or bypassable foundation invalidates later capability evidence | — Pending |
| Prefer native Seafile capability, then add a gated extension | Reduces fork surface and upgrade cost | ✓ Good |
| Standard OAuth2/OIDC for Authentik | Interoperable, supportable, and aligned with Authentik best practices | — Pending |
| MinIO is the only verified S3-compatible target | Prevents unsupported compatibility claims | — Pending |
| External-data federation is a separate later project | Isolates high-risk external filesystem containment and allows a general AI/library interface | — Pending |
| Local editing remains two independent client projects | Preserves trust boundaries and release independence | ✓ Good |
| Seafile AI remains the AI execution layer | Avoids duplicate permission and indexing architectures | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-08-11 after initialization*
