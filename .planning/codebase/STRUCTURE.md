# Codebase Structure

**Analysis Date:** 2026-08-11

## Directory Layout

```text
openfile/
├── cloudfile-docker/                 # Cross-repo control plane and this repository
│   ├── .github/workflows/            # Baseline and per-capability CI gates
│   ├── base_scripts/                 # Container base-image/process supervision setup
│   ├── build/
│   │   ├── cloudfile_14.0/           # Active CloudFile source assembly and packaging
│   │   └── seafile_{11,12,13,14}.0/  # Retained upstream/versioned build scripts
│   ├── custom/                       # Retained custom Pro image definitions
│   ├── deploy/compose/               # Core and optional-profile deployment stack
│   ├── docs/
│   │   ├── features/                 # Current capability specifications
│   │   ├── upstream-patches/         # Allowed upstream modification inventories
│   │   └── history/                  # Non-authoritative historical material
│   ├── image/
│   │   ├── cloudfile_14.0/           # Active CloudFile CE 14 image
│   │   └── {seafile,pro_seafile}_*/  # Retained upstream/versioned image definitions
│   ├── patches/seafdav/              # Maintained patch for an unforked component
│   ├── scripts/scripts_14.0/          # Active container bootstrap/runtime scripts
│   ├── services/                     # nginx runtime configuration and runit entry
│   ├── templates/                    # Retained upstream runtime templates
│   ├── tests/e2e/                    # Cross-repository HTTP/system matrices
│   ├── tests/tools/                  # Tests for orchestration tooling
│   ├── tools/                        # Fast checks, preflight, and integrated verifier
│   ├── release.yaml                  # Build/release source of truth
│   └── BRANCHING.md                  # Shared repository branch/release policy
├── cloudfile-hub/                    # Seahub fork: UI/API/application extensions
│   ├── cloudfile_ext/                # CloudFile capability packages and registries
│   ├── frontend/src/cloudfile/       # CloudFile frontend integration
│   ├── seahub/                       # Upstream Seahub plus narrow CloudFile seams
│   └── docs/                         # Hub-local implementation documentation
├── cloudfile-server/                 # Seafile Server fork: final enforcement/storage
│   ├── common/                       # C extension registries and policy implementations
│   ├── fileserver/                   # Go upload/sync gateway and storage paths
│   ├── server/                       # C Server operations and RPC registration
│   ├── scripts/sql/                  # Native and CloudFile database DDL
│   └── tests/cf-*/                   # Server-side CloudFile contract tests
├── cloudfile-local-agent/            # Go Native Messaging host and desktop session runner
└── cloudfile-chrome-extension/       # Manifest V3 `.cloudfile` download handoff
```

## Directory Purposes

**`.github/workflows/`:**
- Purpose: Run the control-plane consistency gate, baseline image/E2E gate, and capability-specific acceptance matrices.
- Contains: `checks.yml`, `build-and-e2e.yml`, and workflows such as `acl-e2e.yml`, `search-e2e.yml`, `storage-e2e.yml`, and `fileop-e2e.yml`.
- Key files: `.github/workflows/checks.yml`, `.github/workflows/build-and-e2e.yml`
- Add a capability workflow only together with its local `tools/verify-local.sh` capability entry and `tests/e2e/<capability>_matrix.py`.

**`base_scripts/`:**
- Purpose: Prepare the Ubuntu image and install process supervision, cron, syslog-ng, log rotation, and utility helpers.
- Contains: Shell setup stages, runit definitions, and small helper binaries.
- Key files: `base_scripts/prepare.sh`, `base_scripts/system_services.sh`, `base_scripts/utilities.sh`, `base_scripts/bin/my_init`
- Treat this as shared image infrastructure; CloudFile application startup belongs in `scripts/scripts_14.0/`.

**`build/`:**
- Purpose: Build versioned Seafile distributions from component source trees.
- Contains: Retained upstream builders under `build/seafile_*.0/` and the active CloudFile builder under `build/cloudfile_14.0/`.
- Key files: `build/cloudfile_14.0/cloudfile-build.sh`, `build/cloudfile_14.0/cloudfile-build.py`, `build/cloudfile_14.0/build-in-docker.sh`, `build/cloudfile_14.0/read-manifest.py`
- Put CloudFile 14 source-resolution and packaging changes in `build/cloudfile_14.0/`; do not change retained upstream version directories to implement a CloudFile capability.

**`custom/`:**
- Purpose: Preserve upstream/custom Pro image definitions for older release lines.
- Contains: Versioned Pro Dockerfiles.
- Key files: `custom/pro_seafile_11.0/Dockerfile`
- Do not place active CloudFile CE 14 work here; use `image/cloudfile_14.0/`.

**`deploy/compose/`:**
- Purpose: Define the deployable core stack, optional service profiles, proxy routes, example configuration, and operator guidance.
- Contains: Compose topology, Caddy routing, `.env.example`, AI configuration example, and deployment README.
- Key files: `deploy/compose/docker-compose.yml`, `deploy/compose/Caddyfile`, `deploy/compose/.env.example`, `deploy/compose/README.md`
- Put topology and deploy-time wiring here. Put application semantics in the owning Hub/Server repository and document the cross-repo contract in `docs/`.

**`docs/`:**
- Purpose: Serve as the authoritative cross-repository product, architecture, deployment, configuration, capability, and branch documentation entry.
- Contains: Current documents at the root, capability chapters in `docs/features/`, machine-readable contracts, upstream modification lists, and historical material.
- Key files: `docs/README.md`, `docs/architecture.md`, `docs/feature-matrix.md`, `docs/EXTENSION-POINTS.md`, `docs/acl-cases.json`, `docs/fileop-cases.json`
- Add a new current capability chapter under `docs/features/<capability>.md`; add shared machine-readable semantics at `docs/<capability>-cases.json`; do not use `docs/history/` for active guidance.

**`image/`:**
- Purpose: Build runtime container images for versioned Seafile/Pro lines and active CloudFile CE 14.
- Contains: Versioned Dockerfiles and image-build wrappers.
- Key files: `image/cloudfile_14.0/Dockerfile`, `image/cloudfile_14.0/docker-build.sh`
- Put active dependency pins and CloudFile image assembly in `image/cloudfile_14.0/`. Keep dependency pins aligned with `image/pro_seafile_14.0/Dockerfile` while preserving the CE/Pro boundary.

**`patches/`:**
- Purpose: Carry small, explicit patches for manifest-pinned upstream components that do not justify another maintained fork.
- Contains: Component-named subdirectories with ordered patch files.
- Key files: `patches/seafdav/0001-enforce-dir-acl-on-read-paths.patch`
- Add a patch only when the component remains unforked, the patch is applied fatally by `build/cloudfile_14.0/cloudfile-build.sh`, and the security/maintenance rationale is documented.

**`scripts/`:**
- Purpose: Provide versioned scripts copied into runtime images.
- Contains: Upstream-compatible script sets from 7.1 through 14.0; `scripts/scripts_14.0/` is the active CloudFile runtime set.
- Key files: `scripts/scripts_14.0/bootstrap.py`, `scripts/scripts_14.0/start.py`, `scripts/scripts_14.0/enterpoint.sh`, `scripts/scripts_14.0/upgrade.py`
- Put restart-safe configuration generation and container lifecycle changes in `scripts/scripts_14.0/`. Preserve generated block markers and call `write_cloudfile_config()` on every start.

**`services/`:**
- Purpose: Configure and run nginx inside the application image.
- Contains: Main nginx config, Seafile site config, and the runit `run` script source.
- Key files: `services/nginx.conf`, `services/seafile.nginx.conf`, `services/nginx.sh`
- Keep internal image proxy behavior here; public TLS and multi-container routing belong in `deploy/compose/Caddyfile`.

**`templates/`:**
- Purpose: Retain upstream configuration templates used by older image/script lines.
- Contains: nginx and certificate-renewal templates.
- Key files: `templates/seafile.nginx.conf.template`, `templates/letsencrypt.cron.template`
- Do not use this directory for new CloudFile cross-repo specifications or active Compose templates.

**`tests/e2e/`:**
- Purpose: Verify assembled behavior through the deployed HTTP/API surface.
- Contains: Baseline smoke/extension checks and capability matrices for ACL, SSO, metadata, audit, storage, search, external sources, and file operations.
- Key files: `tests/e2e/smoke.py`, `tests/e2e/baseline.py`, `tests/e2e/acl_matrix.py`, `tests/e2e/fileop_matrix.py`
- Name new system tests `<capability>_matrix.py` and route them through both `tools/verify-local.sh` and a matching CI workflow.

**`tests/tools/`:**
- Purpose: Test orchestration scripts without building the product image.
- Contains: Shell-based tool behavior tests.
- Key files: `tests/tools/test-check-upstream-patches.sh`
- Put tests for a specific `tools/` script here; keep cross-repo product behavior in `tests/e2e/`.

**`tools/`:**
- Purpose: Enforce repository invariants and provide consistent local/CI verification entry points.
- Contains: Upstream-patch inspection, static preflight, bootstrap-generation tests, fast cross-repo checks, and integrated build/deploy/E2E orchestration.
- Key files: `tools/check-upstream-patches.sh`, `tools/preflight-checks.py`, `tools/test-bootstrap-settings.py`, `tools/run-checks.sh`, `tools/verify-local.sh`
- Add fast deterministic invariants to `tools/preflight-checks.py`; add cross-repo tool sequencing to `tools/run-checks.sh`; add image/Compose lifecycle behavior to `tools/verify-local.sh`.

**`../cloudfile-hub/cloudfile_ext/`:**
- Purpose: Own CloudFile's Hub-side application extension framework and capability packages.
- Contains: `apps.py`, `registry.py`, provider selection, hooks, URL assembly, worker command, and packages such as `acl/`, `sso/`, `audit/`, `search/`, `external_sources/`, and `file_actions/`.
- Key files: `../cloudfile-hub/cloudfile_ext/apps.py`, `../cloudfile-hub/cloudfile_ext/registry.py`, `../cloudfile-hub/cloudfile_ext/urls.py`, `../cloudfile-hub/cloudfile_ext/management/commands/cf_worker.py`
- Add a Hub capability as `../cloudfile-hub/cloudfile_ext/<capability>/` with a `register(registry)` entry; add only the minimum upstream Seahub seam required to dispatch into it.

**`../cloudfile-server/common/` and `../cloudfile-server/fileserver/`:**
- Purpose: Own Server-side extension seams, final policy, write lifecycle, and Go gateway/storage adaptations.
- Contains: `common/cf-*.c`, `common/cf-*.h`, `fileserver/cf_*.go`, and narrow modifications to native operation paths.
- Key files: `../cloudfile-server/common/cf-ext.c`, `../cloudfile-server/common/cf-fileop.c`, `../cloudfile-server/fileserver/cf_ext.go`, `../cloudfile-server/fileserver/cf_fileop.go`
- Add security policy in new `cf-<capability>.{c,h}` files, register it from `cf_ext_init()`, and reuse the existing upstream seams before modifying more native files.

**`../cloudfile-local-agent/`:**
- Purpose: Own the local trusted computing boundary for desktop file sessions.
- Contains: CLI/native-host entry point and `internal/appfinder/`, `internal/config/`, `internal/nativehost/`, `internal/runner/`, and `internal/session/`.
- Key files: `../cloudfile-local-agent/cmd/cloudfile-local-agent/main.go`, `../cloudfile-local-agent/internal/runner/runner.go`, `../cloudfile-local-agent/internal/session/session.go`
- Put OS-specific application discovery in `internal/appfinder/`; session protocol validation in `internal/session/`; filesystem/download/write-back behavior in `internal/runner/`.

**`../cloudfile-chrome-extension/`:**
- Purpose: Own the narrow Chrome download-to-Native-Messaging bridge.
- Contains: `manifest.json`, service worker, and popup resources.
- Key files: `../cloudfile-chrome-extension/manifest.json`, `../cloudfile-chrome-extension/background.js`, `../cloudfile-chrome-extension/popup.js`
- Keep server trust, content transfer, and program execution out of this repository; those belong to `../cloudfile-local-agent/`.

## Key File Locations

**Entry Points:**
- `build/cloudfile_14.0/build-in-docker.sh`: Start a reproducible Linux distribution build.
- `build/cloudfile_14.0/cloudfile-build.sh`: Resolve component revisions and orchestrate the complete package build.
- `image/cloudfile_14.0/docker-build.sh`: Build the deployable image from the packaged distribution.
- `scripts/scripts_14.0/enterpoint.sh`: Runtime container shell entry.
- `scripts/scripts_14.0/start.py`: Bootstrap, configure, start, and monitor Server/Hub.
- `tools/run-checks.sh`: Fast cross-repository validation entry.
- `tools/verify-local.sh`: Integrated local build/deploy/E2E entry.
- `../cloudfile-hub/cloudfile_ext/apps.py`: Hub extension-registration entry.
- `../cloudfile-server/server/seafile-session.c`: Server startup integration calling `cf_ext_init()`.
- `../cloudfile-local-agent/cmd/cloudfile-local-agent/main.go`: Native Agent entry.
- `../cloudfile-chrome-extension/background.js`: Chrome service-worker entry.

**Configuration:**
- `release.yaml`: Source refs, product/image identity, and contract versions.
- `deploy/compose/.env.example`: Versioned deployment configuration names and safe example defaults; never use a local `.env` as source code.
- `deploy/compose/docker-compose.yml`: Service topology, volumes, profiles, and runtime environment wiring.
- `deploy/compose/Caddyfile`: Public proxy/TLS routing.
- `scripts/scripts_14.0/bootstrap.py`: Translation from deployment inputs into Seahub, Server, seafevents, and database configuration.
- `image/cloudfile_14.0/Dockerfile`: Runtime OS and language dependency pins.
- `BRANCHING.md` and `docs/BRANCHES.md`: Shared three-repository branch and upstream-sync rules.

**Core Logic:**
- `build/cloudfile_14.0/cloudfile-build.py`: Native distribution packaging.
- `../cloudfile-hub/cloudfile_ext/registry.py`: Hub hook/provider model.
- `../cloudfile-hub/cloudfile_ext/providers.py`: Named provider selection.
- `../cloudfile-hub/cloudfile_ext/hooks.py`: Seahub-to-CloudFile dispatch helpers.
- `../cloudfile-server/common/cf-ext.c`: Server read-side permission registry.
- `../cloudfile-server/common/cf-fileop.c`: Server write-lifecycle registry.
- `../cloudfile-server/server/repo-op.c`: Native C write call sites.
- `../cloudfile-server/fileserver/cf_fileop.go`: Go-to-Server file-operation RPC gateway.
- `../cloudfile-local-agent/internal/runner/runner.go`: Local session execution and write-back.

**Testing:**
- `tools/preflight-checks.py`: Static cross-file and cross-repository consistency checks.
- `tools/test-bootstrap-settings.py`: Generated Seahub settings validation.
- `tests/e2e/smoke.py`: Native CE-compatible baseline behavior.
- `tests/e2e/baseline.py`: Extension framework installed but disabled.
- `tests/e2e/<capability>_matrix.py`: Capability acceptance matrices.
- `../cloudfile-hub/cloudfile_ext/**/tests/`: Hub unit tests.
- `../cloudfile-server/tests/cf-*/`: Server C policy/contract tests.

**Specifications and Status:**
- `docs/feature-matrix.md`: Evidence-based capability status and ownership.
- `docs/EXTENSION-POINTS.md`: Registered extension seam inventory.
- `docs/acl-semantics.md` and `docs/acl-cases.json`: Cross-layer ACL contract.
- `docs/fileop-lifecycle.md` and `docs/fileop-cases.json`: Cross-layer write lifecycle contract.
- `docs/upstream-patches/cloudfile-docker.txt`, `docs/upstream-patches/cloudfile-hub.txt`, `docs/upstream-patches/cloudfile-server.txt`: Fork modification inventories.

## Naming Conventions

**Files:**
- Use `cloudfile-*` for top-level CloudFile build artifacts and scripts: `build/cloudfile_14.0/cloudfile-build.sh`.
- Use `cf-*` for Server C extension units: `../cloudfile-server/common/cf-fileop.c`.
- Use `cf_*` for Python/Go modules, functions, database tables, and worker commands: `../cloudfile-hub/cloudfile_ext/management/commands/cf_worker.py`, `../cloudfile-server/fileserver/cf_fileop.go`.
- Use `<capability>_matrix.py` for assembled E2E tests: `tests/e2e/search_matrix.py`.
- Use `<capability>-e2e.yml` for capability workflows: `.github/workflows/search-e2e.yml`.
- Use numeric prefixes for ordered patches: `patches/seafdav/0001-enforce-dir-acl-on-read-paths.patch`.
- Use UPPERCASE names for repository governance/entry documents: `AGENTS.md`, `BRANCHING.md`, `docs/EXTENSION-POINTS.md`.

**Directories:**
- Use `<area>_<major>.0` for active versioned build/image/script sets: `build/cloudfile_14.0/`, `image/cloudfile_14.0/`, `scripts/scripts_14.0/`.
- Use lowercase snake_case for Python capability packages: `../cloudfile-hub/cloudfile_ext/external_sources/`.
- Use `cf-<capability>` for Server test suites: `../cloudfile-server/tests/cf-fileop/`.
- Use component names beneath `patches/`: `patches/seafdav/`.

## Where to Add New Code

**New Cross-Repository Capability:**
- Shared specification: `docs/features/<capability>.md`; use `docs/<capability>-cases.json` when Hub and Server share machine-readable semantics.
- Hub implementation: `../cloudfile-hub/cloudfile_ext/<capability>/`, registered by `../cloudfile-hub/cloudfile_ext/apps.py` through `<capability>.register(registry)`.
- Server final enforcement: `../cloudfile-server/common/cf-<capability>.{c,h}` and, only when needed, `../cloudfile-server/fileserver/cf_<capability>.go`.
- Schema: `../cloudfile-server/scripts/sql/mysql/cloudfile.sql` and matching SQLite DDL when Server tests/support require it; expose Hub access through unmanaged models and `../cloudfile-hub/cloudfile_ext/db_router.py`.
- Runtime configuration: `scripts/scripts_14.0/bootstrap.py` plus the versioned example configuration in `deploy/compose/.env.example`.
- Integrated tests: `tests/e2e/<capability>_matrix.py`, `tools/verify-local.sh`, and `.github/workflows/<capability>-e2e.yml`.
- Status/evidence: `docs/feature-matrix.md` and, when adding a seam, `docs/EXTENSION-POINTS.md`.

**New External Service Integration:**
- Compose service/profile: `deploy/compose/docker-compose.yml`.
- Public routing: `deploy/compose/Caddyfile` only when the service requires browser-visible routes.
- Hub adapter/provider: `../cloudfile-hub/cloudfile_ext/<capability>/`.
- Server adapter: `../cloudfile-server/` only when the external service is storage infrastructure or otherwise requires native enforcement.
- Operator documentation: `deploy/compose/README.md` and `docs/features/<capability>.md`.
- Keep network calls out of synchronous permission-final-decision paths.

**New Build Component or Source Pin:**
- Manifest key: `release.yaml`.
- Resolution/checkout: `build/cloudfile_14.0/cloudfile-build.sh` using `build/cloudfile_14.0/read-manifest.py`.
- Packaging: `build/cloudfile_14.0/cloudfile-build.py` only when the component contributes distribution files.
- Provenance: extend generated build information in `cloudfile-build.sh`.
- Validation: `tools/preflight-checks.py` and `tools/run-checks.sh`.

**New Runtime Bootstrap Behavior:**
- Implementation: `scripts/scripts_14.0/bootstrap.py`.
- Invocation: keep restart-sensitive behavior under `write_cloudfile_config()` from `scripts/scripts_14.0/start.py`; keep first-install-only behavior under `init_seafile_server()`.
- Test: `tools/test-bootstrap-settings.py` and targeted preflight checks.
- Preserve operator-owned content outside `CF_BEGIN`/`CF_END` blocks.

**New Image Dependency:**
- Runtime dependency: `image/cloudfile_14.0/Dockerfile`.
- Build-only dependency: `build/cloudfile_14.0/cloudfile-build.sh` or `build/cloudfile_14.0/build-in-docker.sh`.
- Do not install build-only tools into the runtime image unless the running application needs them.

**New Orchestration Utility:**
- Static invariant or helper: `tools/<name>.py` or `tools/<name>.sh`.
- Unit/behavior test: `tests/tools/test-<name>.sh` or a focused Python test near the tool.
- CI entry: route through `tools/run-checks.sh` so every repository invokes the same logic.

**New Local Desktop Behavior:**
- Browser-only handoff: `../cloudfile-chrome-extension/`.
- Native trust, session, filesystem, download, application, or write-back behavior: the corresponding package under `../cloudfile-local-agent/internal/`.
- Hub session/API behavior: `../cloudfile-hub/cloudfile_ext/file_actions/`.
- Cross-component contract and status: `docs/features/file-collaboration.md` and `docs/feature-matrix.md`.

## Special Directories

**`build/cloudfile_14.0/src/`:**
- Purpose: Cache/fetch workspace for manifest-selected source repositories.
- Generated: Yes, by `build/cloudfile_14.0/cloudfile-build.sh`.
- Committed: No; ignored by `build/*/src`.
- Modification rule: Change source in its owning repository, manifest ref, or maintained patch; do not edit the generated checkout as the implementation source.

**`build/cloudfile_14.0/seafile-server-<version>/`:**
- Purpose: Packaged distribution consumed by the image build.
- Generated: Yes, by `build/cloudfile_14.0/cloudfile-build.py`.
- Committed: No; ignored by `build/*/seafile-server-*`.
- Modification rule: Regenerate from source; never patch the package in place.

**`deploy/compose/data/`:**
- Purpose: Live Compose database, cache, Seafile, proxy, index, and optional-service state.
- Generated: Yes, by running the deployment.
- Committed: No; ignored because it contains runtime data.
- Modification rule: Treat as operator state with explicit backup/recovery procedures, not as source or a test fixture.

**`deploy/compose/.env`:**
- Purpose: Machine-local deployment configuration that may contain credentials.
- Generated: User-created from `deploy/compose/.env.example`.
- Committed: No; explicitly ignored.
- Modification rule: Add configuration names and safe defaults to `.env.example`; never document or copy local values.

**`.local-verify/`:**
- Purpose: Isolated staging area for `tools/verify-local.sh` Compose verification.
- Generated: Yes.
- Committed: No; explicitly ignored.
- Modification rule: Change its creation/cleanup through `tools/verify-local.sh`, not by relying on manually retained state.

**`docs/history/`:**
- Purpose: Preserve replaced decisions and obsolete procedures for context.
- Generated: No.
- Committed: Yes.
- Modification rule: Never cite it as current configuration, feature status, or operating procedure; link readers to the current replacement document.

**`image/{seafile,pro_seafile}_*/`, `build/seafile_*.0/`, `scripts/scripts_{7.1,8.0,9.0,10.0,11.0,12.0,13.0}/`:**
- Purpose: Retain upstream/versioned material and compatibility context.
- Generated: No for tracked source files; some image staging subdirectories are generated and ignored.
- Committed: Yes for the versioned definitions and scripts.
- Modification rule: Implement the active CloudFile CE 14 path in `image/cloudfile_14.0/`, `build/cloudfile_14.0/`, and `scripts/scripts_14.0/`; avoid broad edits to retained versions.

**`.planning/codebase/`:**
- Purpose: Store GSD codebase maps consumed by planning and execution commands.
- Generated: Yes, by codebase mapping.
- Committed: Determined by the orchestrating workflow.
- Modification rule: Keep file references current and use these maps as navigation aids; executable code and current repository documentation remain the evidence source.

---

*Structure analysis: 2026-08-11*
