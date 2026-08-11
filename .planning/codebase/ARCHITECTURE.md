# Architecture

**Analysis Date:** 2026-08-11

## Pattern Overview

**Overall:** Multi-repository layered fork with a manifest-driven build and deployment control plane.

`cloudfile-docker` is the cross-repository orchestration, release, deployment, verification, and specification repository. It does not serve application requests. Runtime behavior is split between the Seahub fork in `../cloudfile-hub/`, the Seafile Server fork in `../cloudfile-server/`, optional external services, and two independently delivered local-client repositories.

**Key Characteristics:**
- Treat `release.yaml` as the single build and release manifest. It selects the CloudFile fork URLs/refs, pins unforked upstream components by commit SHA, names the image, and versions the database and extension contracts.
- Keep cross-repository product semantics and executable contracts in `docs/`, especially `docs/acl-semantics.md`, `docs/acl-cases.json`, `docs/fileop-lifecycle.md`, and `docs/fileop-cases.json`.
- Put web/API orchestration in `../cloudfile-hub/cloudfile_ext/` and security-critical final enforcement in `../cloudfile-server/common/`, `../cloudfile-server/server/`, and `../cloudfile-server/fileserver/`.
- Gate capabilities at runtime. With all `CF_ENABLE_*` switches disabled, the Hub and Server extension registries remain pass-through and preserve native CE behavior.
- Build Seafile CE 14 from source because the selected upstream baseline has no consumable CE 14 branch, tag, or image. `build/cloudfile_14.0/` and `image/cloudfile_14.0/` own this reconstruction.
- Keep optional infrastructure outside request-time permission decisions. Compose profiles start services; feature switches and provider selection determine whether application code uses them.

## Repository Ownership

| Repository | Ownership | Authoritative locations | Must not own |
|---|---|---|---|
| `cloudfile-docker` | Cross-repo release manifest, source assembly, image construction, Compose deployment, shared specifications, feature status, and integrated gates | `release.yaml`, `build/cloudfile_14.0/`, `image/cloudfile_14.0/`, `deploy/compose/`, `docs/`, `tests/e2e/`, `tools/` | Seahub business logic or Server permission decisions |
| `../cloudfile-hub/` | Web UI, HTTP APIs, extension registration, provider selection, application policy, and periodic task definitions | `../cloudfile-hub/cloudfile_ext/`, `../cloudfile-hub/frontend/src/cloudfile/`, `../cloudfile-hub/seahub/` integration seams | Final enforcement that a sync, WebDAV, or direct Server caller can bypass |
| `../cloudfile-server/` | Permission final decision, repository/file operations, write lifecycle enforcement, object/block/storage routing, CloudFile DDL, and internal RPC | `../cloudfile-server/common/cf-*.{c,h}`, `../cloudfile-server/fileserver/cf_*.go`, `../cloudfile-server/server/`, `../cloudfile-server/scripts/sql/*/cloudfile.sql` | UI, workflow pages, external directory connectors, or search indexing jobs |
| `../cloudfile-local-agent/` | Trusted native host, session claim, isolated workspace, local application selection, download, heartbeat, and write-back | `../cloudfile-local-agent/cmd/cloudfile-local-agent/main.go`, `../cloudfile-local-agent/internal/` | Browser download observation or server-side authorization |
| `../cloudfile-chrome-extension/` | Minimal browser-to-Native-Messaging handoff for downloaded `.cloudfile` descriptors | `../cloudfile-chrome-extension/background.js`, `../cloudfile-chrome-extension/manifest.json` | File content handling, application discovery, CloudFile credentials, or write-back |
| `../seafile/`, `../seafobj/` and manifest-pinned upstream repositories | Upstream dependencies consumed by the build | Pins under `release.yaml` `upstream:` and source clones under generated `build/cloudfile_14.0/src/` | CloudFile extension implementation or product specifications |

## Layers

**Orchestration and Specification Layer:**
- Purpose: Define what is built, how repositories are combined, how the system is deployed, and how cross-layer behavior is verified.
- Location: `release.yaml`, `BRANCHING.md`, `docs/`, `tools/`, `.github/workflows/`
- Contains: Component refs, contract versions, branch rules, architecture and capability specifications, consistency checks, and CI gates.
- Depends on: Parallel checkouts at `../cloudfile-hub/` and `../cloudfile-server/`, Docker, Git, compilers, and the component sources named by `release.yaml`.
- Used by: Build scripts, image assembly, Compose deployment, CI, and all CloudFile repository maintainers.

**Source Assembly Layer:**
- Purpose: Resolve the manifest, fetch exact component revisions, apply the maintained WebDAV patch, build native components and Seahub assets, and package a Seafile distribution.
- Location: `build/cloudfile_14.0/`
- Contains: `cloudfile-build.sh`, the packaging driver `cloudfile-build.py`, `build-in-docker.sh`, and the dependency-free manifest reader `read-manifest.py`.
- Depends on: `release.yaml`, `patches/seafdav/`, CloudFile forks, upstream Git repositories, Linux build packages, Python, Go, Node.js, and npm.
- Used by: `image/cloudfile_14.0/docker-build.sh`, `.github/workflows/*-e2e.yml`, and `tools/verify-local.sh`.

**Image and Container Runtime Layer:**
- Purpose: Turn the packaged distribution and runtime scripts into the deployable CloudFile image, then initialize and supervise Seafile/Seahub.
- Location: `image/cloudfile_14.0/`, `base_scripts/`, `scripts/scripts_14.0/`, `services/`
- Contains: Ubuntu-based image definition, runit/base-image setup, nginx wiring, bootstrap/configuration generation, schema application, upgrade checks, and process startup.
- Depends on: The generated `build/cloudfile_14.0/seafile-server-<version>/` distribution.
- Used by: The `cloudfile` and `cf-worker` services declared by `deploy/compose/docker-compose.yml`.

**Deployment Layer:**
- Purpose: Compose the core CloudFile service with persistence, routing, database/cache, and optional service profiles.
- Location: `deploy/compose/`
- Contains: `docker-compose.yml`, `Caddyfile`, `.env.example`, an AI configuration example, and operator documentation.
- Depends on: The image named by `release.yaml` or an explicit image override and independently versioned third-party images.
- Used by: Operators, E2E workflows, and `tools/verify-local.sh`.

**Web and API Layer:**
- Purpose: Authenticate users, expose pages and REST APIs, select providers, register capability routes/hooks, and schedule background application work.
- Location: `../cloudfile-hub/cloudfile_ext/`, with minimal integration seams in `../cloudfile-hub/seahub/` and UI integration in `../cloudfile-hub/frontend/src/cloudfile/`.
- Contains: `CloudFileConfig`, the process-wide registry, capability packages, unmanaged models for `cf_*` tables, and the `cf_worker` Django command.
- Depends on: Seahub, Server RPC APIs, `seafile-db`, Redis, and configured optional services.
- Used by: Browsers, Seafile clients through Seahub-facing endpoints, local Agent session claims, and the `cf-worker` container.

**Enforcement and Storage Layer:**
- Purpose: Enforce permissions and locks below the Hub, mediate write lifecycle events, and own repository/object/block/storage operations.
- Location: `../cloudfile-server/common/`, `../cloudfile-server/server/`, `../cloudfile-server/fileserver/`, `../cloudfile-server/scripts/sql/`
- Contains: C extension registries, C and Go gateways, RPC methods, ACL/lock/file-operation providers, storage backends, and CloudFile schema files.
- Depends on: Seafile native models, MariaDB, local or S3-compatible storage, and Redis where configured.
- Used by: Seahub RPC calls, Go fileserver upload/sync paths, WebDAV through the patched `seafdav`, and native Seafile clients.

**External Services Layer:**
- Purpose: Provide identity, search, metadata, AI, office conversion, document editing, caching, database, and object storage services without merging them into the CloudFile application binaries.
- Location: Service declarations in `deploy/compose/docker-compose.yml`; application adapters in `../cloudfile-hub/cloudfile_ext/` and Server storage code in `../cloudfile-server/`.
- Contains: MariaDB, Redis, Caddy, SeaSearch, Meilisearch, Metadata Server, seafile-ai, OnlyOffice, SeaDoc, and development MinIO profiles.
- Depends on: Operator configuration and independent persistence/backup policies.
- Used by: Hub providers, Server storage routing, background tasks, and browser-facing proxy routes.

**Local Client Layer:**
- Purpose: Bridge a short-lived Hub-issued local-file session to trusted desktop software without exposing browser cookies or a localhost HTTP API.
- Location: `../cloudfile-chrome-extension/` and `../cloudfile-local-agent/`
- Contains: A Manifest V3 download observer, Native Messaging transport, origin allowlist, session claim client, isolated workspaces, application discovery, and write-back support.
- Depends on: Hub agent-session APIs and a user-installed Native Messaging host.
- Used by: Browser users choosing local view or local edit actions.

## Data Flow

**Manifest-Driven Build and Release:**

1. `build/cloudfile_14.0/cloudfile-build.sh` reads fork URLs/refs and upstream SHAs from `release.yaml` through `build/cloudfile_14.0/read-manifest.py`.
2. The script clones or updates sources under generated `build/cloudfile_14.0/src/`, checks out detached revisions, and applies `patches/seafdav/0001-enforce-dir-acl-on-read-paths.patch`.
3. `build_seahub_frontend()` builds `../cloudfile-hub/` frontend assets in the fetched `seahub` tree; `cloudfile-build.py` compiles and packages Server, Hub, WebDAV, events, and supporting libraries.
4. The build writes the resolved commit set to generated `build/cloudfile_14.0/seafile-server-<version>/cloudfile-build-info.txt`.
5. `image/cloudfile_14.0/docker-build.sh` stages the distribution with `base_scripts/`, `scripts/scripts_14.0/`, and `services/`, then builds the image tag derived from `release.yaml` plus the requested version.

**Container Bootstrap and Configuration:**

1. `image/cloudfile_14.0/Dockerfile` starts `/sbin/my_init -- /scripts/enterpoint.sh`; runit starts nginx from `services/nginx.sh`.
2. `scripts/scripts_14.0/enterpoint.sh` loads configured secret files, waits for nginx, and launches `scripts/scripts_14.0/start.py`.
3. `start.py` waits for MariaDB, runs `init_seafile_server()`, applies version upgrades, and calls `write_cloudfile_config()` on every start.
4. `scripts/scripts_14.0/bootstrap.py` rewrites only `CF_BEGIN`/`CF_END` generated blocks, updates Seahub and Server configuration, writes seafevents search configuration, and applies `../cloudfile-server/scripts/sql/mysql/cloudfile.sql` when it is present in the packaged distribution.
5. `start.py` launches `seafile.sh` and `seahub.sh`, then monitors the controller process.

**Interactive Request and Permission Decision:**

1. Caddy/nginx routes browser or API traffic to Seahub and file transfer traffic to the native services assembled in the same image.
2. `../cloudfile-hub/cloudfile_ext/apps.py` registers enabled capability packages during Django startup and seals `../cloudfile-hub/cloudfile_ext/registry.py`.
3. Hub request handlers compute native Seafile permissions, then chain enabled CloudFile permission checks through `registry.apply_permission_checks()`.
4. Operations requiring final enforcement cross the Seahub/Server RPC boundary or enter the Go fileserver directly.
5. `../cloudfile-server/common/cf-ext.c` chains registered Server providers through `cf_ext_check_permission()`, `cf_ext_filter_dirents()`, or `cf_ext_find_restricted_path()`. A denial cannot be widened by a later provider.
6. Server returns the narrowed result; read failures in security policy are expected to fail closed, while no registered provider preserves native CE behavior.

**Write Lifecycle:**

1. A write enters Seahub, `../cloudfile-server/server/repo-op.c`, or `../cloudfile-server/fileserver/fileop.go` depending on protocol.
2. Native write call sites construct the shared file-operation contract and invoke PREPARE before mutation.
3. Go paths call `cf_fileop_prepare` through `../cloudfile-server/fileserver/cf_fileop.go` and the Unix-pipe searpc client; C paths dispatch locally through the same provider abstraction.
4. A PREPARE provider may reject the operation. Successful writes emit COMMITTED; failed writes emit ABORTED.
5. Hub post-operation observers such as audit or indexing must not roll back a completed write; `registry.run_file_op_hooks()` logs and swallows post-hook exceptions.

**Background Capability Work:**

1. Enabled Hub capability packages register periodic tasks in `../cloudfile-hub/cloudfile_ext/registry.py`.
2. The optional `cf-worker` service runs `../cloudfile-hub/cloudfile_ext/management/commands/cf_worker.py` from the same application image.
3. The worker executes due tasks sequentially, catches task failures, logs them, and retries on a later tick.
4. Search indexing, organization synchronization, and external-source scanning therefore remain outside synchronous permission checks.

**Local View and Edit:**

1. Hub creates a short-lived `.cloudfile` descriptor containing an origin, expiry, and one-time claim ticket.
2. `../cloudfile-chrome-extension/background.js` observes the completed download and sends only its path to the Native Messaging host.
3. `../cloudfile-local-agent/cmd/cloudfile-local-agent/main.go` validates the message and starts an isolated session runner.
4. `../cloudfile-local-agent/internal/runner/runner.go` validates the local origin allowlist, claims the ticket through the Hub, downloads content into a private workspace, and opens a configured or discovered desktop application.
5. Edit sessions heartbeat and upload stable changes using the returned short-lived write-back capability; view sessions receive no write-back capability.

**State Management:**
- Native Seafile repository, commit, FS object, and block state remains owned by the Server and its configured storage.
- CloudFile relational state uses `cf_*` tables declared in `../cloudfile-server/scripts/sql/mysql/cloudfile.sql` and `../cloudfile-server/scripts/sql/sqlite/cloudfile.sql`; Hub models are `managed=False` and route to `seafile-db` through `../cloudfile-hub/cloudfile_ext/db_router.py`.
- Runtime configuration is derived from deployment inputs and rewritten idempotently by `scripts/scripts_14.0/bootstrap.py`; operators must not hand-edit generated CloudFile blocks.
- Compose persistence lives under ignored `deploy/compose/data/`; external object stores and mounted external sources remain outside CloudFile database transactions.
- Provider and hook registries are process-local startup state. Register during application/server initialization; do not mutate them after the Hub registry is sealed.

## Key Abstractions

**Release Manifest:**
- Purpose: Bind component source identity, product/image version, release commits, database schema version, and extension API version.
- Examples: `release.yaml`, `build/cloudfile_14.0/read-manifest.py`
- Pattern: Read dotted keys from the manifest; do not hard-code refs or SHAs in build scripts.

**Hub Extension Registry:**
- Purpose: Let capability packages contribute URL patterns, menu entries, permission checks, file-operation hooks, search indexers, external-source backends, periodic tasks, and named providers.
- Examples: `../cloudfile-hub/cloudfile_ext/apps.py`, `../cloudfile-hub/cloudfile_ext/registry.py`, `../cloudfile-hub/cloudfile_ext/providers.py`
- Pattern: Each capability implements `register(registry)`, checks its own switch, registers during `CloudFileConfig.ready()`, and leaves the registry immutable afterward.

**Server Extension Registries:**
- Purpose: Centralize security-sensitive read and write seams so capabilities do not repeatedly patch upstream call sites.
- Examples: `../cloudfile-server/common/cf-ext.c`, `../cloudfile-server/common/cf-ext.h`, `../cloudfile-server/common/cf-fileop.c`, `../cloudfile-server/common/cf-fileop.h`
- Pattern: Providers register once during Server startup; permission providers can only narrow; PREPARE can veto while COMMITTED/ABORTED report outcomes.

**Capability Switch:**
- Purpose: Ship integrated code without activating it and keep disabled behavior equivalent to CE.
- Examples: `scripts/scripts_14.0/bootstrap.py`, `../cloudfile-hub/cloudfile_ext/features.py`, `../cloudfile-server/common/cf-ext.c`
- Pattern: Add each product switch consistently to the deployment example, bootstrap mapping, Hub feature list, Server configuration where applicable, and both disabled/enabled verification paths.

**Named Provider:**
- Purpose: Select one interchangeable implementation of a job such as search or a directory source.
- Examples: `../cloudfile-hub/cloudfile_ext/providers.py`, `../cloudfile-hub/cloudfile_ext/search/`, `../cloudfile-hub/cloudfile_ext/sso/directory.py`
- Pattern: Register all available implementations by kind/name; select exactly one with `CF_PROVIDER_<KIND>`; reject configured names that are not registered.

**Compose Profile:**
- Purpose: Add optional infrastructure without making it part of the default core stack.
- Examples: `deploy/compose/docker-compose.yml`, `deploy/compose/README.md`
- Pattern: Use profiles for process topology and switches/providers for application behavior. Do not use a profile as evidence that a capability is enabled.

**Shared Executable Contract:**
- Purpose: Keep semantics aligned across Python Hub policy, C Server enforcement, and E2E behavior.
- Examples: `docs/acl-cases.json`, `docs/fileop-cases.json`, `tests/e2e/acl_matrix.py`, `tests/e2e/fileop_matrix.py`, `../cloudfile-server/tests/cf-acl/`, `../cloudfile-server/tests/cf-fileop/`
- Pattern: Change the specification and cases first, then update every implementation and gate that consumes them.

## Entry Points

**Cross-Repository Fast Verification:**
- Location: `tools/run-checks.sh`
- Triggers: Local invocation and `.github/workflows/checks.yml`.
- Responsibilities: Run upstream-patch checks, Hub extension tests, Server C/Go checks, Compose validation, syntax validation, config-generation tests, and manifest validation across sibling checkouts.

**Integrated Local Verification:**
- Location: `tools/verify-local.sh`
- Triggers: `preflight`, build/image stages, baseline E2E, or `cap <capability>`.
- Responsibilities: Stage an isolated Compose deployment, build the source/image, run baseline smoke checks, and dispatch capability matrices.

**Distribution Build:**
- Location: `build/cloudfile_14.0/build-in-docker.sh` and `build/cloudfile_14.0/cloudfile-build.sh`
- Triggers: Developer, release automation, or E2E workflows.
- Responsibilities: Provide the Linux build environment, resolve source refs, compile, package, and record exact commits.

**Image Build:**
- Location: `image/cloudfile_14.0/docker-build.sh`
- Triggers: A completed distribution build.
- Responsibilities: Validate the distribution, create an isolated build context, and build the versioned runtime image.

**Application Container:**
- Location: `image/cloudfile_14.0/Dockerfile` → `scripts/scripts_14.0/enterpoint.sh` → `scripts/scripts_14.0/start.py`
- Triggers: Compose starts the `cloudfile` service.
- Responsibilities: Initialize process supervision, load secret files, bootstrap/upgrade/configure state, start Server and Hub, and monitor them.

**Hub Extension Startup:**
- Location: `../cloudfile-hub/cloudfile_ext/apps.py`
- Triggers: Django app population through the generated Seahub settings.
- Responsibilities: Configure the CloudFile database alias, register enabled capabilities, and seal the registry.

**Hub Background Worker:**
- Location: `../cloudfile-hub/cloudfile_ext/management/commands/cf_worker.py`
- Triggers: The optional `cf-worker` Compose service.
- Responsibilities: Run registered periodic tasks with per-task fault isolation.

**Server Extension Startup:**
- Location: `../cloudfile-server/server/seafile-session.c` calling `cf_ext_init()` in `../cloudfile-server/common/cf-ext.c`
- Triggers: Seafile Server session initialization.
- Responsibilities: Read Server CloudFile configuration and register enabled ACL, file-operation test, and lock providers.

**Browser Local Session Receiver:**
- Location: `../cloudfile-chrome-extension/background.js`
- Triggers: Chrome reports a completed `.cloudfile` download.
- Responsibilities: Respect the local auto-open preference and hand the descriptor path to the native host.

**Native Local Agent:**
- Location: `../cloudfile-local-agent/cmd/cloudfile-local-agent/main.go`
- Triggers: Native Messaging, `--run-session`, configuration commands, or validation commands.
- Responsibilities: Validate local trust, claim a session, create the workspace, open the file, and perform bounded write-back.

## Error Handling

**Strategy:** Fail early for reproducibility or security violations, fail closed for authorization uncertainty, and isolate optional post-processing failures from core file operations.

**Patterns:**
- Build scripts use `set -e`, reject missing manifest keys, check out detached refs, remove stale distributions, and abort when a maintained patch no longer applies.
- `build/cloudfile_14.0/read-manifest.py` exits nonzero for absent keys so an empty ref cannot silently select an arbitrary HEAD.
- `scripts/scripts_14.0/bootstrap.py` performs idempotent generated-block replacement and treats schema absence as a warning only when the selected baseline has no CloudFile schema.
- Hub and Server permission chains stop on denial. Policy data failures must deny access; no rule and no registered provider remain distinct pass-through cases.
- Hub post-write hooks and background tasks log exceptions without undoing a completed file write or terminating the worker loop.
- Local session processing validates descriptor size/type/expiry, origin equality, file names, response modes, content URLs, download size, and write-back capability before acting.

## Cross-Cutting Concerns

**Logging:** Use each owning layer's existing logger: shell progress/failure output in `build/` and `tools/`, Python logging in `scripts/scripts_14.0/` and `../cloudfile-hub/cloudfile_ext/`, and `seaf_message()`/`seaf_warning()` or Go logrus in `../cloudfile-server/`. Compose and E2E failure handlers collect container and application logs.

**Validation:** Use `tools/preflight-checks.py` for cross-file invariants, `tools/run-checks.sh` for fast cross-repo checks, `tools/verify-local.sh` for assembled-system behavior, and the JSON contract/matrix pairs in `docs/` and `tests/e2e/` for shared semantics.

**Authentication:** Seahub owns interactive identity and token/session authentication. External identity providers integrate through Seahub configuration; Server receives the resolved user identity and remains the final authorization layer. The local Agent uses one-time session tickets and short-lived bearer capabilities rather than browser cookies.

---

*Architecture analysis: 2026-08-11*
