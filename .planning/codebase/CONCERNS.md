# Codebase Concerns

**Analysis Date:** 2026-08-11

## Recommended Phase Ordering

| Order | Phase | Severity | Exit condition |
|---|---|---|---|
| 1 | Security containment and exact enforcement | Critical | Sync fails closed when ACL enforcement is active; every search backend filters effective CloudFile ACLs; every lock release is generation-fenced. |
| 2 | Acceptance-gate repair | High | `preflight-checks.py` passes, is invoked by CI, skipped integration tests are reported as skips, and Hub/Server changes trigger the relevant container E2E with exact refs. |
| 3 | Collaboration-flow correctness | High | Local Agent view/edit works end to end; write-back updates rather than creates; OnlyOffice is registered, configured, authenticated, and container-tested. |
| 4 | Release reproducibility and documentation truth | Medium | Release inputs use immutable commits, provenance fields are populated, patch inventories are current, and active documents no longer contradict code. |
| 5 | Capability-completeness work | Medium | Audit, metadata/tags, SSO, AI, storage portability, and browser/client matrices meet the limits stated in `docs/roadmap.md`. |

Do not widen feature enablement before phases 1–2. Most capabilities default off, so the safe interim posture is to keep affected combinations disabled while repairing enforcement and gates.

## Tech Debt

**Cross-repository acceptance is not triggered by the repositories whose code is under test (High):**
- Issue: Full container workflows live only in `cloudfile-docker/.github/workflows/`, and their normal `push`/`pull_request` events observe changes in the Docker repository. A merge in `cloudfile-hub/` or `cloudfile-server/` runs each repository's `cloudfile-checks.yml`, but those workflows call only `cloudfile-docker/tools/run-checks.sh`; they do not dispatch baseline or capability E2E.
- Files: `.github/workflows/build-and-e2e.yml`, `.github/workflows/acl-e2e.yml`, `.github/workflows/search-e2e.yml`, `.github/workflows/fileop-e2e.yml`, `.github/workflows/storage-e2e.yml`, `../cloudfile-hub/.github/workflows/cloudfile-checks.yml`, `../cloudfile-server/.github/workflows/cloudfile-checks.yml`
- Evidence: Both adjacent workflows end at `./cloudfile-docker/tools/run-checks.sh`. The container workflows check out Hub/Server separately and default to the moving `dev` refs from `release.yaml`.
- Impact: A permission, RPC, frontend, or storage regression can merge in Hub/Server without the E2E that proves the affected runtime path. A later Docker push may test a different combination of repository heads.
- Fix approach: Add a repository-dispatch/reusable-workflow orchestrator that receives exact Hub, Server, and Docker SHAs. Require baseline plus the affected capability matrix on cross-repository PRs before merge.

**Release inputs are branch refs rather than an immutable three-repository set (High):**
- Issue: `release.yaml` points both CloudFile forks at `dev`; `server_commit`, `hub_commit`, and `docker_commit` are empty. The upstream components are SHA-pinned, but the product forks are not.
- Files: `release.yaml`, `build/cloudfile_14.0/cloudfile-build.sh`, `.github/workflows/build-and-e2e.yml`
- Evidence: `forks.cloudfile_server.ref` and `forks.cloudfile_hub.ref` are `dev`; the build resolves `origin/<ref>` at execution time.
- Impact: Rebuilding the same product version can produce different binaries, and CI results cannot be attributed to a stable cross-repo source tuple unless build logs are retained.
- Fix approach: Generate a release lock containing all three immutable commits before build, validate non-empty provenance fields for release builds, embed the tuple in the image, and retain branch refs only as developer conveniences.

**The standard quick-check workflow does not execute its own static preflight (High):**
- Issue: `tools/preflight-checks.py` contains the workflow/reference and local-vs-CI gate consistency checks, but `.github/workflows/checks.yml` and both adjacent `cloudfile-checks.yml` workflows invoke only `tools/run-checks.sh`.
- Files: `tools/preflight-checks.py`, `tools/run-checks.sh`, `tools/verify-local.sh`, `.github/workflows/checks.yml`, `../cloudfile-hub/.github/workflows/cloudfile-checks.yml`, `../cloudfile-server/.github/workflows/cloudfile-checks.yml`
- Evidence: `tools/verify-local.sh preflight` is the only composed entry point that calls both scripts. A direct run of `python3 tools/preflight-checks.py ...` currently fails, while `run-checks.sh` does not expose that failure.
- Impact: CI can be green while local and CI capability gates have drifted.
- Fix approach: Make one canonical `preflight` command call both layers and use it from all three repositories. Add a small self-test that proves each preflight checker is invoked.

**Fork maintenance inventories are knowingly warning-only and currently stale (Medium):**
- Issue: The upstream-patch audit no longer blocks CI and currently reports unregistered modified upstream files plus one obsolete Hub inventory entry.
- Files: `tools/check-upstream-patches.sh`, `docs/upstream-patches/cloudfile-server.txt`, `docs/upstream-patches/cloudfile-hub.txt`, `docs/upstream-patches/cloudfile-docker.txt`, `BRANCHING.md`
- Evidence: The live audit reports unregistered `../cloudfile-server/README.testing.md`, `../cloudfile-server/tests/test_upload/readme.md`, `README.md`, and `build/README.md`; it reports `../cloudfile-hub/frontend/webpack-stats.pro.json` as no longer modified.
- Impact: The declared merge-conflict surface is inaccurate, weakening upstream-sync planning. Because the check exits successfully, drift can accumulate indefinitely.
- Fix approach: Classify documentation-only modifications separately, refresh all three inventories, and make unexplained source-code drift blocking while retaining warning severity for explicitly exempt documentation.

**Active documents contradict the current code and build (High):**
- Issue: `docs/EXTENSION-POINTS.md` still describes the C S3 lifecycle and CE file locks as missing, while `../cloudfile-server/common/cf-s3-client.c`, `../cloudfile-server/common/cf-lock.c`, and the storage/lock wiring exist. `docs/acl-semantics.md` says WebDAV read ACL is missing, while `patches/seafdav/0001-enforce-dir-acl-on-read-paths.patch` is applied by `build/cloudfile_14.0/cloudfile-build.sh` and asserted by `tests/e2e/acl_matrix.py`.
- Files: `docs/EXTENSION-POINTS.md`, `docs/acl-semantics.md`, `docs/feature-matrix.md`, `patches/seafdav/0001-enforce-dir-acl-on-read-paths.patch`, `build/cloudfile_14.0/cloudfile-build.sh`, `../cloudfile-server/common/cf-s3-client.c`, `../cloudfile-server/common/cf-lock.c`
- Impact: Planners may schedule already-delivered infrastructure, misclassify genuine current risks, or disable a security patch they believe does not exist.
- Fix approach: Reconcile active documents against `dev`, move superseded gap narratives to `docs/history/`, and add freshness checks for security patch application and capability-status claims rather than only `docs/FEATURES.md` timestamps.

**The extension and write-lifecycle seams have a wide manual call-site surface (Medium):**
- Issue: C operations in `server/repo-op.c` and Go operations in `fileserver/fileop.go`/`fileserver/sync_api.go` must construct the same operation vocabulary and payload shape manually.
- Files: `../cloudfile-server/server/repo-op.c`, `../cloudfile-server/fileserver/fileop.go`, `../cloudfile-server/fileserver/cf_fileop.go`, `../cloudfile-server/common/cf-fileop.h`, `docs/fileop-cases.json`
- Evidence: `tests/cf-fileop/run.sh` type-checks 50 C call sites and shared contract tests, but its own documentation states that it cannot prove the runtime variables carry the intended values.
- Impact: New upstream write paths or a semantically wrong variable can bypass locks/audit while compiling cleanly.
- Fix approach: Keep the shared vocabulary generated from one schema, add mutation tests for values as well as types, and require container E2E whenever upstream changes any write entry point.

## Known Bugs

**External-source capability gate exists in CI but not in local verification (High):**
- Symptoms: `python3 tools/preflight-checks.py /Users/bobo/workspace/openfile/cloudfile-docker /Users/bobo/workspace/openfile` exits 1 and reports local capabilities without `external_sources`, while `.github/workflows/external_sources-e2e.yml` exists.
- Files: `tools/verify-local.sh`, `tools/preflight-checks.py`, `.github/workflows/external_sources-e2e.yml`, `tests/e2e/external_sources_matrix.py`
- Trigger: Run the preflight checker on the current three-repository checkout.
- Workaround: Run `.github/workflows/external_sources-e2e.yml` manually or reproduce its steps; `./tools/verify-local.sh cap external_sources` is currently unavailable.
- Fix approach: Add `external_sources|CF_ENABLE_EXTERNAL_SOURCES|tests/e2e/external_sources_matrix.py` to `CAPABILITIES`, add any required environment/run hook, and make CI invoke the preflight.

**Local Agent manifest download dereferences response fields the API does not return (High):**
- Symptoms: Clicking “Download local session” raises on `session.file.name`; edit sessions are also displayed as view sessions because `session.mode` is absent.
- Files: `../cloudfile-hub/frontend/src/cloudfile/file-actions/index.js`, `../cloudfile-hub/cloudfile_ext/file_actions/service.py`, `../cloudfile-hub/cloudfile_ext/file_actions/apis.py`, `../cloudfile-hub/docs/CAPABILITIES.md`
- Trigger: Enable `CF_ENABLE_LOCAL_APP`, create either local-view or local-edit session, then download the `.cloudfile` manifest.
- Evidence: `_issue_agent_session()` returns `protocol`, `ticket`, `expires_in`, and `expires_at`; the React code reads `session.file.name` and `session.mode`.
- Workaround: None in the UI. The backend ticket can be consumed only by constructing the manifest outside the broken frontend flow.
- Fix approach: Define and version one response schema, return `mode` and a safe display filename or use the already-derived frontend `fileName`, and add a browser/API contract test.

**Local Agent write-back calls the create-file RPC for an existing file (Critical):**
- Symptoms: After an agent claims an edit session and uploads edited content, the endpoint can return success while creating a uniquely renamed sibling file instead of updating the original; it then releases the lock and closes the session.
- Files: `../cloudfile-hub/cloudfile_ext/file_actions/apis.py`, `../cloudfile-server/python/seaserv/api.py`, `../cloudfile-server/server/repo-op.c`
- Trigger: Exercise `AgentContentView.put()` for a normal edit session.
- Evidence: `AgentContentView.put()` calls `seafile_api.post_file(...)`; the server documents `post_file` as “Add a file”, emits `CF_OP_CREATE_FILE`, and `post_file_recursive()` generates a unique name when the requested name already exists. Updates use `seafile_api.put_file(...)` and an expected head/version contract.
- Workaround: None for the shipped agent write-back endpoint.
- Fix approach: Use the update RPC with the expected head/file version, retain the existing base-file fencing check, and add conflict/retry/container tests before re-enabling local edit.

**OnlyOffice protection code is not registered or deployment-wired (High):**
- Symptoms: `CF_ENABLE_ONLYOFFICE` can start the Document Server profile, but CloudFile's authenticated/idempotent callback route is never added by `CloudFileConfig.ready()`. The main application container also receives the feature flag but not the OnlyOffice JWT/configuration values required by the callback and CE editor.
- Files: `../cloudfile-hub/cloudfile_ext/apps.py`, `../cloudfile-hub/cloudfile_ext/office/__init__.py`, `../cloudfile-hub/cloudfile_ext/office/callbacks.py`, `deploy/compose/docker-compose.yml`, `scripts/scripts_14.0/bootstrap.py`
- Trigger: Enable `CF_ENABLE_ONLYOFFICE` and start the `office` profile.
- Evidence: `apps.py` imports/registers `base`, `acl`, `sso`, `audit`, `metadata`, `search`, `checkout`, `external_sources`, and `file_actions`, but not `office`. Bootstrap contains the switch name but no OnlyOffice settings block; Compose gives the JWT value to the Document Server only.
- Workaround: Use the upstream CE integration through manually maintained Seahub settings; CloudFile callback hardening and lock coordination remain inactive.
- Fix approach: Register `office`, generate/pass the editor URL, JWT secret/header, and callback URL into Seahub, validate required settings at startup, and add a complete save/retry/lock E2E workflow.

**A stale OnlyOffice callback can release a newer lock owned by the same user (Critical, latent until Office registration):**
- Symptoms: A delayed callback from an older editing generation can unlock a later session on the same path.
- Files: `../cloudfile-hub/cloudfile_ext/office/callbacks.py`, `../cloudfile-hub/cloudfile_ext/file_actions/service.py`, `../cloudfile-server/common/cf-lock.c`
- Trigger: The same user opens a new generation after an older session completes or expires, then the old callback is retried.
- Evidence: `onlyoffice_callback()` calls `release_checkout(repo_id, path, username)` without a generation. `cf_lock_release_json()` explicitly accepts a missing generation and then releases any active lock at that path owned by the caller.
- Workaround: Keep the CloudFile Office callback unregistered; do not claim fencing-safe OnlyOffice locking.
- Fix approach: Persist the generation in the OnlyOffice document/session key and require it for every normal release. Reserve generation-less release for a separately authorized administrative compatibility path.

## Security Considerations

**Go sync ACL lookup fails open on RPC errors and caches revocation-sensitive answers for five minutes (Critical):**
- Risk: A user can continue or initiate whole-library synchronization when `cf_find_restricted_path` is temporarily unavailable, even if directory ACL is enabled. A newly added restriction can remain invisible to the Go gate until the cache expires.
- Files: `../cloudfile-server/fileserver/cf_ext.go`, `../cloudfile-server/fileserver/sync_api.go`, `../cloudfile-server/common/cf-acl.c`, `docs/acl-semantics.md`
- Evidence: `cfFindRestrictedPath()` returns `""` on every RPC error and caches both empty and restricted answers for 300 seconds. `checkPermission()` treats empty as fully reachable and then caches repository permission. The write seam in `fileserver/cf_fileop.go` already has a safer active/inactive/unsupported state model, but the read/sync seam does not.
- Current mitigation: Seahub performs a friendly pre-check, C path checks fail closed, and the sync gate refuses a repo when it successfully receives a restricted path. These do not protect against an RPC outage or stale empty cache in the Go authority boundary.
- Recommendations: Add an active/inactive/unsupported probe for the restriction seam; fail closed on RPC/malformed replies once ACL is active; invalidate on ACL revision changes; do not cache “unrestricted” across rule updates. Add outage and immediate-revocation E2E cases.

**Search results are not filtered by CloudFile's `cf_dir_acl` rules (Critical):**
- Risk: When `CF_ENABLE_DIR_ACL` and `CF_ENABLE_SEARCH` are enabled together, a user can receive names, paths, or snippets from a CloudFile-`invisible` directory. The documented Meilisearch workaround does not provide a CloudFile ACL filter either.
- Files: `../cloudfile-hub/cloudfile_ext/search/__init__.py`, `../cloudfile-hub/cloudfile_ext/search/backends/meilisearch.py`, `../cloudfile-hub/seahub/api2/views.py`, `../cloudfile-hub/seahub/search/utils.py`, `../cloudfile-hub/cloudfile_ext/acl/models.py`, `docs/features/search.md`, `tests/e2e/search_matrix.py`
- Evidence: `Search.get()` filters results only with `get_invisible_repos_info_by_username()`, which reads upstream share-invisible tables through `SeafileDB`; it never reads `cf_dir_acl` or calls `check_folder_permission()` on each result path. `MeilisearchProvider` scopes by `repo_id` and requested `search_path`, not effective ACL. Native SeaSearch additionally bypasses even the upstream `is_invisible_path` result loop, as its module documentation notes.
- Current mitigation: The relevant switches default off. Selecting Meilisearch is not a sufficient mitigation for CloudFile ACL rules.
- Recommendations: Reject every ACL+search combination at startup until a backend-independent effective-permission filter exists. Filter each candidate path through the CloudFile ACL evaluator before returning it, correct pagination/total semantics after filtering, and add combined E2E asserting no name, path, or snippet leaks on SeaSearch and Meilisearch.

**OnlyOffice callback authentication is fail-open when its secret is absent (High, latent):**
- Risk: If the hardened route becomes registered without correct configuration, `_authenticated()` accepts every callback when `ONLYOFFICE_JWT_SECRET` is empty. A forged callback could reach the upstream save flow.
- Files: `../cloudfile-hub/cloudfile_ext/office/callbacks.py`, `../cloudfile-hub/cloudfile_ext/office/__init__.py`, `deploy/compose/docker-compose.yml`
- Current mitigation: The module is not currently registered, and the Document Server profile enables JWT on its side.
- Recommendations: When `CF_ENABLE_ONLYOFFICE=true`, require a non-empty secret on both services and fail startup on mismatch. Do not retain the unauthenticated compatibility mode in the CloudFile-hardened route.

**Permission correctness depends on runtime schema creation during every startup (High):**
- Risk: Missing `cf_*` tables can fail closed and lock users out; a schema-version mismatch can leave Hub, C, and Go interpreting different data shapes.
- Files: `scripts/scripts_14.0/bootstrap.py`, `scripts/scripts_14.0/start.py`, `../cloudfile-server/scripts/sql/mysql/cloudfile.sql`, `../cloudfile-hub/cloudfile_ext/db_router.py`, `release.yaml`
- Current mitigation: SQL uses idempotent creation and startup reruns schema application; `database_schema` and `extension_api` fields exist.
- Recommendations: Add explicit forward migrations and a startup compatibility handshake among Hub/Server/image versions. Refuse capability enablement with a targeted diagnostic before serving traffic; test CE-to-CloudFile conversion and rollback.

**External-source file delivery is a high-consequence containment boundary (Medium):**
- Risk: A path normalization, symlink, or authorization regression in Hub can read arbitrary mounted/container files because external data bypasses the Seafile object/token/fileserver path.
- Files: `../cloudfile-hub/cloudfile_ext/external_sources/apis.py`, `../cloudfile-hub/cloudfile_ext/external_sources/paths.py`, `../cloudfile-hub/cloudfile_ext/external_sources/providers.py`, `tests/e2e/external_sources_matrix.py`
- Current mitigation: The API normalizes relative paths, deliberately conflates nonexistent/unauthorized sources, uses provider containment checks, streams files, and has unit plus container test assets.
- Recommendations: Keep local mounts read-only, test symlink replacement races during open, use directory-fd/openat-style containment where supported, and run the missing local gate before every release.

## Performance Bottlenecks

**Authoritative C ACL checks load every rule for a repository on each decision (Medium):**
- Problem: `load_repo_rules()` queries all `cf_dir_acl` rows for every permission/filter/restricted-path decision, then builds the user's subject set.
- Files: `../cloudfile-server/common/cf-acl.c`, `../cloudfile-server/common/cf-acl-resolve.c`
- Cause: The implementation intentionally avoids caching to prevent delayed revocation, but the cost grows with repository rule count and hot-path request volume.
- Improvement path: Introduce revision-keyed immutable snapshots with immediate invalidation, index `repo_id` plus path/subject fields, and benchmark realistic rule/group cardinalities. Preserve fail-closed semantics on cache/database failure.

**Large-object/storage lifecycle validation lacks scale and fault-injection evidence (Medium):**
- Problem: Storage E2E proves a MinIO happy path, GC/FSCK, and offline migration, but not large repositories, pagination extremes, throttling, partial network failure, or multi-provider compatibility.
- Files: `tests/e2e/storage_matrix.py`, `.github/workflows/storage-e2e.yml`, `../cloudfile-server/tests/cf-s3/test-cf-s3.c`, `../cloudfile-server/common/cf-s3-client.c`, `docs/features/storage-backends.md`
- Cause: The quick S3 C test skips without an explicit endpoint, while the container matrix targets only MinIO.
- Improvement path: Add deterministic fault injection, pagination tests by default, resumable migration checkpoints, throughput/memory budgets, and separate compatibility jobs for each supported S3 provider before making broader claims.

**Container E2E repeatedly rebuilds the full distribution per capability (Medium):**
- Problem: Each capability workflow performs the complete C/Go/frontend distribution and image build, taking up to two hours and consuming enough disk to require runner cleanup.
- Files: `.github/workflows/*-e2e.yml`, `build/cloudfile_14.0/cloudfile-build.sh`, `image/cloudfile_14.0/docker-build.sh`
- Cause: Workflows are isolated and do not share an immutable base artifact/source tuple.
- Improvement path: Build once per exact three-repo tuple, attest/export the image, then fan out independent capability jobs against that image. Keep capability configuration isolated while avoiding repeated compilation.

## Fragile Areas

**Generated configuration can fail silently at the Seahub boundary (High):**
- Files: `scripts/scripts_14.0/bootstrap.py`, `scripts/scripts_14.0/start.py`, `tools/test-bootstrap-settings.py`, `../cloudfile-hub/cloudfile_ext/apps.py`
- Why fragile: Seahub imports `seahub_settings.py` as an ordinary module and can discard the whole CloudFile block after a `NameError`; configuration is assembled across Compose, generated Python, `seafile.conf`, and runtime registry initialization.
- Safe modification: Add new settings through `_settings_block_*` helpers, keep the generated block self-contained, rerun it every startup, and extend both the execution test and preflight switch-list check.
- Test coverage: Current generator tests are strong, but OnlyOffice demonstrates that a switch can exist without a complete settings block or runtime registration.

**Locking spans C transactions, Go write gates, Hub capabilities, callbacks, and clients (Critical):**
- Files: `../cloudfile-server/common/cf-lock.c`, `../cloudfile-server/common/cf-fileop.c`, `../cloudfile-server/fileserver/cf_fileop.go`, `../cloudfile-hub/cloudfile_ext/file_actions/service.py`, `../cloudfile-hub/cloudfile_ext/office/callbacks.py`
- Why fragile: Correctness depends on path normalization, owner identity, generation fencing, lease/hard expiry, every write call site, and delayed callback behavior agreeing across languages.
- Safe modification: Treat generation as mandatory for mutation/release, modify shared contracts before code, and verify C, Go, Hub, WebDAV, sync, OnlyOffice, and local-agent paths together.
- Test coverage: C/Go contract tests pass locally, but there is no complete lock/checkout/OnlyOffice/local-agent container matrix.

**S3/multiple-storage operations are operationally irreversible if sequencing is wrong (High):**
- Files: `../cloudfile-server/common/storage-backend-multi.c`, `../cloudfile-server/common/cf-s3-client.c`, `../cloudfile-server/server/gc/gc-core.c`, `../cloudfile-server/fsck.c`, `../cloudfile-hub/scripts/seaf-storage-migrate.sh`, `.github/workflows/storage-e2e.yml`
- Why fragile: Database routing and commit/fs/block objects must move as one logical unit. Source deletion, GC, or repair against a partial migration can make recovery impossible.
- Safe modification: Keep migration offline, retain source objects until independently verified backups exist, and require a dry run plus complete enumeration before destructive cleanup.
- Test coverage: MinIO migration is covered; production S3 variants, disaster restore, very large repositories, and interrupted resume are not.

**Unforked seafdav security behavior depends on a patch applying to one pinned upstream commit (High):**
- Files: `patches/seafdav/0001-enforce-dir-acl-on-read-paths.patch`, `build/cloudfile_14.0/cloudfile-build.sh`, `release.yaml`, `tests/e2e/acl_matrix.py`
- Why fragile: A pin bump can invalidate or semantically weaken the patch; clean application proves syntax, not that all new upstream read paths remain covered.
- Safe modification: Review the upstream diff before every pin bump, run the WebDAV PROPFIND/direct-read assertions, and maintain a call-path inventory.
- Test coverage: The current matrix checks listing and direct directory visibility, but should also assert direct file GET and range requests for invisible paths.

## Scaling Limits

**Directory ACL cardinality and group expansion:**
- Current capacity: No explicit supported maximum is encoded or tested.
- Files: `../cloudfile-server/common/cf-acl.c`, `../cloudfile-hub/cloudfile_ext/acl/`, `docs/acl-cases.json`
- Limit: Each authoritative C check loads all repository rules and expands user groups/departments; latency and database load rise with both dimensions.
- Scaling path: Establish rule/group budgets, add query/index telemetry, and use revisioned snapshots with immediate invalidation.

**External-source scans and Meilisearch indexing:**
- Current capacity: Batch sizes and intervals are configurable, but no repository-wide throughput/SLO is documented.
- Files: `../cloudfile-hub/cloudfile_ext/external_sources/scanner.py`, `../cloudfile-hub/cloudfile_ext/search/indexer.py`, `deploy/compose/docker-compose.yml`
- Limit: One worker profile owns periodic scans/index updates; large mounts or backfills can extend staleness and compete with other periodic tasks.
- Scaling path: Add durable cursors, per-source backpressure, queue depth/lag metrics, bounded retries, and horizontal-worker ownership semantics.

**Audit retention and query growth:**
- Current capacity: API pages are capped at 200, but no retention, archival, or production volume target is defined.
- Files: `../cloudfile-hub/cloudfile_ext/audit/views.py`, `../cloudfile-hub/cloudfile_ext/audit/service.py`, `docs/features/audit.md`
- Limit: `Activity` growth can degrade administrative filtering and backups; it is not an immutable compliance ledger.
- Scaling path: Define retention/archival, verify indexes against real query filters, and export to a dedicated SIEM when compliance retention is required.

## Dependencies at Risk

**Preview/testing/rolling external image tags (High for production):**
- Risk: The deployment defaults include a metadata-server testing tag and rolling `latest`-style tags for several optional services; rebuilding can change binaries without a repository change.
- Files: `deploy/compose/docker-compose.yml`, `docs/feature-matrix.md`, `docs/features/seafile-ai.md`, `docs/features/storage-backends.md`
- Impact: Unreviewed upgrades can change schemas, APIs, or security behavior; the metadata/tag and AI paths already lack full recovery/E2E evidence.
- Migration plan: Pin immutable digests in a release lock, qualify stable versions per capability, and add upgrade/rollback tests before production support.

**CE 14 is reconstructed from upstream commits without an official CE 14 release artifact (High):**
- Risk: CloudFile owns the integration of upstream Server, Hub, seafdav, seafevents, build scripts, and image pins.
- Files: `release.yaml`, `build/cloudfile_14.0/cloudfile-build.sh`, `image/cloudfile_14.0/Dockerfile`, `AGENTS.md`
- Impact: Security updates and compatibility changes require manual pin review, patch rebasing, and a full rebuild; there is no vendor-provided CE 14 image parity guarantee.
- Migration plan: Maintain an explicit upstream-update cadence and bill of materials, diff every pin, run all cross-repo gates, and evaluate migration to an official same-version CE artifact when available.

**Only MinIO is a verified S3 implementation (Medium):**
- Risk: “S3-compatible” behavior varies in path style, signatures, pagination, consistency, and error codes.
- Files: `docs/features/storage-backends.md`, `.github/workflows/storage-e2e.yml`, `../cloudfile-server/tests/cf-s3/test-cf-s3.c`
- Impact: Other providers may fail during enumeration, GC, FSCK, or migration despite basic object operations working.
- Migration plan: Keep MinIO as the declared support baseline and add provider-specific compatibility suites before expanding support claims.

## Missing Critical Features

**A production-safe combined ACL + search mode:**
- Problem: Search result filtering reads upstream share-invisible metadata rather than `cf_dir_acl`; neither native SeaSearch nor Meilisearch currently proves effective CloudFile ACL filtering, and configuration does not reject the combination.
- Files: `../cloudfile-hub/seahub/api2/views.py`, `../cloudfile-hub/seahub/search/utils.py`, `../cloudfile-hub/cloudfile_ext/search/backends/meilisearch.py`, `docs/features/search.md`
- Blocks: Safe simultaneous enablement of directory invisibility and default SeaSearch.

**A completed file collaboration path:**
- Problem: Local Agent frontend/write-back is broken, OnlyOffice is not wired, and lock release is not uniformly generation-fenced.
- Files: `../cloudfile-hub/frontend/src/cloudfile/file-actions/index.js`, `../cloudfile-hub/cloudfile_ext/file_actions/apis.py`, `../cloudfile-hub/cloudfile_ext/office/`, `../cloudfile-server/common/cf-lock.c`
- Blocks: Production claims for local edit, checkout, OnlyOffice lock coordination, and Pro-equivalent file locking.

**Immutable release provenance:**
- Problem: The current manifest does not identify one immutable Hub/Server/Docker combination.
- Files: `release.yaml`, `build/cloudfile_14.0/cloudfile-build.sh`
- Blocks: Reproducible rebuilds, auditable rollbacks, and confident correlation of E2E results with shipped images.

## Test Coverage Gaps

**Current locally reproduced acceptance failures (High):**
- What's not passing: `tools/preflight-checks.py` fails because `external_sources` exists in CI but not the local capability table. `tools/run-checks.sh` also exits 1 in this workstation because the active `python3` lacks `pytest`; this is an environment failure, not evidence of failing Hub tests.
- Files: `tools/preflight-checks.py`, `tools/verify-local.sh`, `tools/run-checks.sh`, `.github/workflows/external_sources-e2e.yml`
- Risk: Developers cannot use the advertised preflight as a reliable green gate; CI does not currently invoke the checker that catches the real drift.
- Priority: High.

**S3 C integration is reported as success when it actually skips (High):**
- What's not tested: `../cloudfile-server/tests/cf-s3/run.sh` prints `SKIP C S3 integration test: set CF_S3_TEST_ENDPOINT` and exits zero. `tools/run-checks.sh` therefore prints a success mark and later “all passed.”
- Files: `tools/run-checks.sh`, `../cloudfile-server/tests/cf-s3/run.sh`, `../cloudfile-server/README.testing.md`
- Risk: Reviewers can mistake an absent S3 endpoint for executed integration coverage.
- Priority: High; distinguish PASS/SKIP and require a real endpoint in storage CI.

**ACL outage/revocation and combined-search cases are absent (Critical):**
- What's not tested: Go restriction RPC outage while ACL is active, malformed RPC replies, immediate rule revocation before the 300-second cache expires, and searching an invisible path through native SeaSearch.
- Files: `../cloudfile-server/fileserver/cf_ext.go`, `tests/e2e/acl_matrix.py`, `tests/e2e/search_matrix.py`
- Risk: Confidential data can be synchronized or disclosed in search while individual capability suites remain green.
- Priority: Critical; add combined and failure-mode jobs in phase 1.

**Local Agent and OnlyOffice have no end-to-end gate (Critical):**
- What's not tested: Browser response contract, manifest download, ticket claim, content download, heartbeat, update/conflict, stale-generation rejection, OnlyOffice JWT, retry idempotency, and lock release.
- Files: `../cloudfile-hub/cloudfile_ext/file_actions/`, `../cloudfile-hub/frontend/src/cloudfile/file-actions/`, `../cloudfile-hub/cloudfile_ext/office/`, `.github/workflows/`
- Risk: The current contract and write-RPC bugs remain undetected by the passing unit/quick checks.
- Priority: Critical before either capability is enabled.

**Browser/UI coverage is weak for feature gates and administration (Medium):**
- What's not tested: File-action React flow, ACL administration, lock list/actions, external-source browsing, audit page interactions, and metadata/tag editing in a real browser.
- Files: `../cloudfile-hub/frontend/src/cloudfile/`, `../cloudfile-hub/docs/CAPABILITIES.md`
- Risk: API tests pass while shipped pages use wrong fields, routes, or feature state.
- Priority: Medium after the security and API contracts are fixed.

**Audit, metadata/tags, SSO, and AI matrices remain incomplete (Medium):**
- What's not tested: Audit move/delete/recover across WebDAV/sync; metadata/tag binding and move/recovery permissions; real Authentik/LDAP/AD providers; AI profile, permission trimming, external-LLM failure, data egress, and audit.
- Files: `docs/roadmap.md`, `docs/features/audit.md`, `docs/features/tags.md`, `docs/features/seafile-ai.md`, `tests/e2e/audit_matrix.py`, `tests/e2e/metadata_matrix.py`, `tests/e2e/sso_matrix.py`
- Risk: “Implemented” components can be mistaken for production-complete capabilities.
- Priority: Medium; keep the conservative states in `docs/feature-matrix.md` until each matrix is closed.

---

*Concerns audit: 2026-08-11*
