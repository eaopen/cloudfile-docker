# Roadmap: CloudFile CE Extension

## Overview

CloudFile reaches an independently verifiable CE extension MVP by first closing the security and collaboration contracts that currently invalidate acceptance evidence, then making all later results attributable to an immutable release tuple. Generic Authentik OIDC, per-library local/MinIO storage, tags and audit, and permission-trimmed Seafile AI are qualified in dependency order before one combined release matrix establishes the final support boundary. Coarse granularity keeps each phase broad; phase planning must split work into independently verifiable plans around complete contracts or capability matrices.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions

- [ ] **Phase 1: Security and Collaboration Contract Closure** - Restore trustworthy security gates and complete the local-edit and OnlyOffice contracts.
- [ ] **Phase 2: Immutable Release Evidence** - Bind cross-repository inputs and all qualification evidence to one immutable image identity.
- [ ] **Phase 3: Generic Authentik OIDC** - Qualify standards-based Authentik sign-in, lifecycle, and recovery through Seahub.
- [ ] **Phase 4: Per-Library Storage and MinIO Lifecycle** - Let authorized users choose safe storage classes and prove migration and recovery behavior.
- [ ] **Phase 5: Tags and Audit Lifecycle** - Complete native metadata tagging and attributable mutation audit behavior across supported paths.
- [ ] **Phase 6: Permission-Trimmed Seafile AI** - Qualify official Seafile AI with controlled external-LLM egress and failure isolation.
- [ ] **Phase 7: MVP Qualification and Release** - Prove one complete release tuple and publish only its verified operational boundaries.

## Phase Details

### Phase 1: Security and Collaboration Contract Closure
**Goal**: Users can collaborate without ACL leakage, fail-open access, stale writes, or broken local/office handoffs, and operators receive truthful acceptance results.
**Depends on**: Nothing (first phase)
**Requirements**: SEC-01, SEC-02, FILEOP-01, LOCK-01, GATE-01, LOCAL-01, LOCAL-02, OFFICE-01, OFFICE-02
**Success Criteria** (what must be TRUE):
  1. A user searching with SeaSearch or Meilisearch receives no name, path, snippet, total, or cached result for content hidden by the user's current directory ACL.
  2. Sync and direct fileserver requests are denied when active ACL state is unavailable, malformed, or stale, while disabling the extension preserves native CE access behavior.
  3. Every supported write, including batch delete, produces one stable PREPARE-to-COMMITTED-or-ABORTED lifecycle, and every racing save or release rejects a stale generation.
  4. A user can launch a versioned local view/edit session, claim it through the browser/extension/agent handoff, update the existing file, and receive deterministic heartbeat, conflict, expiry, retry, and stale-generation outcomes.
  5. An operator can enable OnlyOffice only with matching non-empty JWT configuration and verify save/retry/conflict/release behavior, while the same declared local and CI preflight reports every required capability as PASS, SKIP, or failure truthfully.
**Plans**: 16 plans

Plans:
- [x] 01-01-PLAN.md — 建立动态真实 capability gate 与同 tuple disabled 双基线
- [ ] 01-02-PLAN.md — 锁定 ACL authority 与搜索泄漏 Wave 0 合同
- [ ] 01-03-PLAN.md — 实现 Hub ACL revision 与授权优先搜索
- [ ] 01-04-PLAN.md — 实现 Server/fileserver fail-closed ACL authority
- [ ] 01-05-PLAN.md — 接入 ACL/search integration gates
- [ ] 01-06-PLAN.md — 锁定 operation identity 与 fence Wave 0 合同
- [ ] 01-07-PLAN.md — 实现 C/Go/Python operation scope 与 generation fence
- [ ] 01-08-PLAN.md — 接入 fileop integration gate
- [ ] 01-09-PLAN.md — 锁定 local v2/status/writeback Wave 0 合同
- [ ] 01-10-PLAN.md — 实现 durable local Hub backend 与 status API
- [ ] 01-11-PLAN.md — 实现 local browser/Agent/extension clients
- [ ] 01-12-PLAN.md — 接入 local collaboration gate
- [ ] 01-13-PLAN.md — 锁定并实现 Office startup 配置与安全下载合同
- [ ] 01-14-PLAN.md — 实现 durable Office callback、safe download 与 status API
- [ ] 01-15-PLAN.md — 实现 Office authenticated status UI
- [ ] 01-16-PLAN.md — 接入真实 Document Server 与 Phase 1 最终 gate
**UI hint**: yes

### Phase 2: Immutable Release Evidence
**Goal**: Operators can identify and reproduce the exact source, service, and image tuple behind every qualification result and rollback.
**Depends on**: Phase 1
**Requirements**: REL-01, REL-02
**Success Criteria** (what must be TRUE):
  1. An operator can resolve Docker, Hub, Server, upstream sources, patches, schemas, contracts, base images, actions, and optional services from one canonical lock to immutable identities.
  2. CI builds one image for that locked tuple and every capability result identifies the same image digest rather than a rebuilt or moving input.
  3. The shipped digest exposes matching OCI labels, SBOM, provenance, result manifest, and rollback identity that can be verified independently.
**Plans**: TBD

### Phase 3: Generic Authentik OIDC
**Goal**: Users can sign in through a qualified Authentik deployment using Seahub's standard OAuth2/OIDC flow without creating a custom identity protocol or losing administrative recovery.
**Depends on**: Phase 2
**Requirements**: OIDC-01, OIDC-02, OIDC-03
**Success Criteria** (what must be TRUE):
  1. An operator can deploy the qualified stable Authentik release by immutable identity and users can sign in through Seahub's generic Authorization Code flow with an exact HTTPS redirect.
  2. Sign-in rejects invalid state, issuer, audience, signature, nonce, PKCE, or stale-key conditions and binds accounts to stable issuer-subject identity with limited claims and privileges.
  3. Operators can rotate secrets and keys, change claims or groups, disable access, handle logout or IdP outage, and still recover through a verified local break-glass administrator path.
**Plans**: TBD
**UI hint**: yes

### Phase 4: Per-Library Storage and MinIO Lifecycle
**Goal**: Authorized CE users can select an allowed storage class per library without silent fallback, unsafe migration, or unsupported S3 claims.
**Depends on**: Phase 3
**Requirements**: STOR-01, STOR-02, STOR-03, STOR-04
**Success Criteria** (what must be TRUE):
  1. An authorized user can choose an operator-allowed local or MinIO-backed class when creating or managing a library, and unauthorized or invalid choices are rejected.
  2. A library continues to route to its recorded backend across restarts and refuses access rather than silently falling back when that backend is unavailable or invalid.
  3. An operator can dry-run and resume an offline migration that journals complete commit, filesystem, and block enumeration, read-back verification, atomic cutover, and retained rollback data.
  4. Local and pinned MinIO fixtures pass migration, backup, restore, rollback, GC, and FSCK checks, while the product makes no support claim for another S3 provider.
**Plans**: TBD
**UI hint**: yes

### Phase 5: Tags and Audit Lifecycle
**Goal**: Users can apply native Seafile tags with defined lifecycle behavior, and administrators can inspect complete attributable mutation evidence across supported protocols.
**Depends on**: Phase 4
**Requirements**: TAG-01, TAG-02, AUDIT-01, AUDIT-02
**Success Criteria** (what must be TRUE):
  1. An authorized user can bind native Seafile metadata tags to files and directories without encountering a second taxonomy authority.
  2. Tag identity and inheritance or override remain predictable through rename, move, copy, delete, recovery, version, permission, retry, and reconciliation scenarios.
  3. An administrator can query attributable create, update, delete, move, copy, rename, recover, denied, and aborted operations originating from browser, API, sync, and WebDAV paths.
  4. Audit queries remain bounded and indexed, retries do not duplicate facts, and retention, archive, export/SIEM, redaction, and non-compliance-ledger boundaries are visible and testable.
**Plans**: TBD
**UI hint**: yes

### Phase 6: Permission-Trimmed Seafile AI
**Goal**: Operators can use the official Seafile AI integration with approved external LLMs without widening file access, leaking data, or disrupting core file operations.
**Depends on**: Phase 5
**Requirements**: AI-01, AI-02, AI-03
**Success Criteria** (what must be TRUE):
  1. An operator can deploy the qualified Seafile AI 14 image digest and configure a supported external LLM endpoint through the existing Seafile AI configuration model.
  2. A user receives AI results only from currently authorized material, and retrieval, prompts, responses, caches, outbound destinations, payloads, and logs enforce the declared ACL and egress policy.
  3. Disabled AI produces zero egress, while unavailable, slow, or malformed LLM responses terminate within defined bounds and leave core file operations usable.
**Plans**: TBD

### Phase 7: MVP Qualification and Release
**Goal**: Operators can deploy and recover one coherent CloudFile CE MVP whose published claims match reproducible evidence from the exact shipped tuple.
**Depends on**: Phase 6
**Requirements**: QUAL-01, QUAL-02
**Success Criteria** (what must be TRUE):
  1. One immutable tuple passes combined positive, denial, outage, restart, revocation, upgrade, backup, restore, and rollback matrices for every enabled v1 capability.
  2. An operator can verify the shipped service and image identities, evidence, disabled-native behavior, recovery procedures, and rollback target before deployment.
  3. Product documentation states only the providers, capabilities, limits, security behavior, and recovery procedures demonstrated by the release evidence.
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5 → 6 → 7

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Security and Collaboration Contract Closure | 0/TBD | Not started | - |
| 2. Immutable Release Evidence | 0/TBD | Not started | - |
| 3. Generic Authentik OIDC | 0/TBD | Not started | - |
| 4. Per-Library Storage and MinIO Lifecycle | 0/TBD | Not started | - |
| 5. Tags and Audit Lifecycle | 0/TBD | Not started | - |
| 6. Permission-Trimmed Seafile AI | 0/TBD | Not started | - |
| 7. MVP Qualification and Release | 0/TBD | Not started | - |
