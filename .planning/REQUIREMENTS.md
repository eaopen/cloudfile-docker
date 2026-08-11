# Requirements: CloudFile CE Extension

**Defined:** 2026-08-11
**Core Value:** Deliver a coherent, secure, independently verifiable CE extension MVP whose capabilities compose correctly across browser, API, sync, WebDAV, Server, storage, and optional-service boundaries.

## v1 Requirements

### Security And Core Contracts

- [ ] **SEC-01**: Users never receive names, paths, snippets, totals, or cached results for entries hidden by the current CloudFile directory ACL, regardless of search backend.
- [ ] **SEC-02**: Sync and direct fileserver access fail closed when an enabled ACL authority is unavailable, malformed, or stale, while disabled ACL mode preserves native CE behavior.
- [ ] **FILEOP-01**: Batch delete and every supported write path emit one valid PREPARE followed by COMMITTED or ABORTED facts with stable operation identity.
- [ ] **LOCK-01**: Every save, callback, write-back, and lock release that can race is generation-fenced and rejects stale generations.
- [ ] **GATE-01**: Local and CI preflight cover the same declared capabilities and report required skips as SKIP or failure rather than PASS.

### Collaboration

- [ ] **LOCAL-01**: The Hub, browser action, Chrome extension, and local agent share a versioned descriptor/session schema that supplies the filename and all fields required before ticket claim.
- [ ] **LOCAL-02**: Local edit writes back to the existing file with heartbeat, conflict, expiry, retry-idempotency, and stale-generation behavior verified end to end.
- [ ] **OFFICE-01**: OnlyOffice is registered only when enabled and refuses startup/callbacks unless both sides have matching non-empty JWT configuration.
- [ ] **OFFICE-02**: OnlyOffice save, retry, conflict, lock, and generation-aware release behavior passes an integrated container matrix.

### Release Evidence

- [ ] **REL-01**: A canonical release lock resolves Docker, Hub, Server, upstream sources, maintained patches, schemas, contracts, base images, actions, and optional services to immutable identities.
- [ ] **REL-02**: CI builds one image for an immutable tuple and binds all matrix results, OCI labels, SBOM, provenance, and rollback identity to the resulting digest.

### Identity

- [ ] **OIDC-01**: Operators can deploy the latest qualified stable Authentik release and sign users in through Seahub's generic OAuth2/OIDC Authorization Code integration without a custom protocol.
- [ ] **OIDC-02**: The integration validates redirect, state, nonce/PKCE where applicable, issuer, audience, signature/JWKS refresh, and stable issuer-subject identity while limiting claims and privilege mapping.
- [ ] **OIDC-03**: Secret/key rotation, logout/disable behavior, IdP outage, group/claim changes, and local break-glass administrator recovery are reproducibly verified.

### Multi-Storage

- [ ] **STOR-01**: An authorized CE user can select an operator-allowed local or MinIO-backed storage class while creating or managing a library.
- [ ] **STOR-02**: Repository storage routing is stable and never silently falls back when a selected backend is unavailable or invalid.
- [ ] **STOR-03**: Offline migration journals, enumerates, copies, reads back, verifies, cuts over atomically, resumes safely, and retains source data until rollback evidence is accepted.
- [ ] **STOR-04**: Migration, backup/restore, rollback, GC, and FSCK pass for local and pinned MinIO fixtures; no other S3 provider is claimed supported.

### Tags And Audit

- [ ] **TAG-01**: Authorized users can bind native Seafile metadata tags to both files and directories without creating a parallel taxonomy authority.
- [ ] **TAG-02**: Tag identity, inheritance/override, rename, move, copy, delete, recovery, version, permission, retry, and reconciliation behavior is explicit and verified.
- [ ] **AUDIT-01**: Administrators can query attributable create, update, delete, move, copy, rename, recover, denied, and aborted file/directory operations across browser, API, sync, and WebDAV paths.
- [ ] **AUDIT-02**: Audit storage has bounded indexed queries, durable idempotent facts, retention/archive/export/SIEM rules, content-redaction rules, and an explicit non-compliance-ledger boundary.

### Seafile AI

- [ ] **AI-01**: Operators can use the official Seafile AI 14 integration with a qualified image digest and configure supported external LLM endpoints through its existing configuration model.
- [ ] **AI-02**: Current ACLs trim retrieval, prompt, response, and cache boundaries; outbound providers are allowlisted and receive only minimized, authorized data with no secrets/content in logs.
- [ ] **AI-03**: Disabled mode causes zero AI egress, and unavailable, slow, or malformed LLM responses remain bounded and never disrupt core file operations.

### MVP Qualification

- [ ] **QUAL-01**: One immutable release tuple passes combined positive, denial, outage, restart, revocation, upgrade, backup, restore, and rollback matrices for every enabled v1 capability.
- [ ] **QUAL-02**: Product documentation publishes only verified support boundaries, service/image identities, measured limits, disabled-native behavior, and tested recovery procedures.

## v2 Requirements

### External Data Federation

- **FED-01**: A separate CloudFile external-data federation project can expose read-only OpenList/rclone sources through a containment-safe, credential-isolated provider interface.
- **FED-02**: The federation interface can supply permission-trimmed material to AI knowledge libraries and virtual-directory mounts without making external services permission authorities.
- **FED-03**: Write support, caching, availability, reconciliation, and provider-specific credentials receive an independent threat model and milestone before implementation.

### Additional Providers And Scale

- **S3-01**: Each additional S3-compatible provider has its own signatures, pagination, consistency, lifecycle, failure, GC/FSCK, migration, and restore compatibility suite before support is claimed.
- **SCALE-01**: Published capacity envelopes cover ACL cardinality, audit volume, worker concurrency/backpressure, migration duration, restore scale, and AI/indexing lag.

## Out of Scope

| Feature | Reason |
|---------|--------|
| Replacing native Seafile modules | CloudFile extends native capabilities first to minimize fork and upgrade cost. |
| Custom Authentik protocol | Generic OAuth2/OIDC is interoperable and supportable. |
| Independent AI backend | It would duplicate Seafile AI indexing, permissions, and configuration. |
| S3 support claims beyond MinIO | Compatibility is provider-specific and unverified. |
| Bundling native clients into the server image | The local agent and Chrome extension have separate trust, signing, and release boundaries. |
| External virtual-directory federation in v1 | It needs a separate containment and credential threat model. |

## Traceability

Every v1 requirement is assigned to exactly one roadmap phase.

| Requirement | Phase | Status |
|-------------|-------|--------|
| SEC-01 | Phase 1 | Pending |
| SEC-02 | Phase 1 | Pending |
| FILEOP-01 | Phase 1 | Pending |
| LOCK-01 | Phase 1 | Pending |
| GATE-01 | Phase 1 | Pending |
| LOCAL-01 | Phase 1 | Pending |
| LOCAL-02 | Phase 1 | Pending |
| OFFICE-01 | Phase 1 | Pending |
| OFFICE-02 | Phase 1 | Pending |
| REL-01 | Phase 2 | Pending |
| REL-02 | Phase 2 | Pending |
| OIDC-01 | Phase 3 | Pending |
| OIDC-02 | Phase 3 | Pending |
| OIDC-03 | Phase 3 | Pending |
| STOR-01 | Phase 4 | Pending |
| STOR-02 | Phase 4 | Pending |
| STOR-03 | Phase 4 | Pending |
| STOR-04 | Phase 4 | Pending |
| TAG-01 | Phase 5 | Pending |
| TAG-02 | Phase 5 | Pending |
| AUDIT-01 | Phase 5 | Pending |
| AUDIT-02 | Phase 5 | Pending |
| AI-01 | Phase 6 | Pending |
| AI-02 | Phase 6 | Pending |
| AI-03 | Phase 6 | Pending |
| QUAL-01 | Phase 7 | Pending |
| QUAL-02 | Phase 7 | Pending |

**Coverage:**
- v1 requirements: 27 total
- Mapped to phases: 27
- Unmapped: 0

---
*Requirements defined: 2026-08-11*
*Last updated: 2026-08-11 after roadmap creation*
