# Technology Stack

**Analysis Date:** 2026-08-11

## Languages

**Primary:**
- Bash - Repository orchestration, source checkout, container builds, image assembly, service startup, and local verification in `build/cloudfile_14.0/cloudfile-build.sh`, `build/cloudfile_14.0/build-in-docker.sh`, `image/cloudfile_14.0/docker-build.sh`, `scripts/scripts_14.0/enterpoint.sh`, and `tools/verify-local.sh`.
- Python 3 - Manifest parsing, release assembly, container bootstrap/config generation, upgrade/start logic, preflight checks, and E2E matrices in `build/cloudfile_14.0/read-manifest.py`, `build/cloudfile_14.0/cloudfile-build.py`, `scripts/scripts_14.0/bootstrap.py`, `scripts/scripts_14.0/start.py`, `tools/preflight-checks.py`, and `tests/e2e/*.py`.
- YAML - Release pins, Docker Compose orchestration, and GitHub Actions in `release.yaml`, `deploy/compose/docker-compose.yml`, and `.github/workflows/*.yml`.
- Dockerfile syntax - Runtime image definitions in `image/cloudfile_14.0/Dockerfile` and the retained upstream image variants under `image/`.

**Secondary / Adjacent Repositories:**
- C with Autotools - Core repository, filesystem, RPC, permission, and storage implementation in `../cloudfile-server/server/`, `../cloudfile-server/common/`, `../cloudfile-server/fileserver/`, `../cloudfile-server/configure.ac`, and `../cloudfile-server/Makefile.am`; `configure.ac` declares package version `6.0.1`, which is the upstream build-system version rather than the CloudFile product version.
- Go 1.22 - HTTP fileserver and S3-compatible object access in `../cloudfile-server/fileserver/go.mod`; the separate notification server retains Go 1.17 in `../cloudfile-server/notification-server/go.mod`.
- Python 3 / Django - Web/API layer, server bindings, migrations, and extensions in `../cloudfile-hub/manage.py`, `../cloudfile-hub/seahub/`, `../cloudfile-hub/cloudfile_ext/`, and `../cloudfile-hub/requirements.txt`.
- JavaScript / JSX / CSS - Seahub web client in `../cloudfile-hub/frontend/`; React is `18.3.1` and Webpack is `^5.105.0` in `../cloudfile-hub/frontend/package.json`.
- Go 1.24 - Standalone Native Messaging host in `../cloudfile-local-agent/go.mod` and `../cloudfile-local-agent/cmd/cloudfile-local-agent/main.go`.
- JavaScript / HTML / CSS - Dependency-free Chrome Manifest V3 extension version `0.3.0` in `../cloudfile-chrome-extension/manifest.json`, `../cloudfile-chrome-extension/background.js`, and `../cloudfile-chrome-extension/popup.js`.

## Runtime

**Environment:**
- Ubuntu 24.04 is both the final CloudFile image base and the reproducible build container in `image/cloudfile_14.0/Dockerfile` and `build/cloudfile_14.0/build-in-docker.sh`.
- CloudFile product version is `14.0.0-cf.0`, based on Seafile CE 14 source, and is declared in `release.yaml`; upstream does not publish a CE 14 branch, tag, or image, so the repository builds it from source.
- The main container runs `/sbin/my_init` and `/scripts/enterpoint.sh`, with nginx and cron/syslog services assembled from `base_scripts/`, `services/`, and `scripts/scripts_14.0/` as defined by `image/cloudfile_14.0/Dockerfile`.
- Node.js `20.20.2` is downloaded explicitly for the Seahub frontend build by `build/cloudfile_14.0/cloudfile-build.sh`; do not rely on Ubuntu 24.04's Node 18 package.
- Python 3.12 is the Ubuntu 24.04 image Python and the explicit CI check version in `.github/workflows/checks.yml`.

**Package Manager:**
- APT installs native build/runtime dependencies in `build/cloudfile_14.0/cloudfile-build.sh` and `image/cloudfile_14.0/Dockerfile`; system package versions follow Ubuntu 24.04 repositories unless a file states otherwise.
- pip installs the pinned Hub/runtime Python set in `image/cloudfile_14.0/Dockerfile` and the full build-only Hub requirements from `../cloudfile-hub/requirements.txt`.
- npm builds `../cloudfile-hub/frontend/` using `npm ci`; lockfile `../cloudfile-hub/frontend/package-lock.json` is present with lockfile version 3.
- Go modules lock server and local-agent dependencies in `../cloudfile-server/fileserver/go.mod`, `../cloudfile-server/notification-server/go.mod`, `../cloudfile-local-agent/go.mod`, and their `go.sum` files.
- No root-level language package manifest exists in `cloudfile-docker`; `release.yaml` is the cross-repository source/version manifest.

## Frameworks

**Core:**
- Docker Engine and Docker Compose v2 - Build and single-host deployment control in `build/cloudfile_14.0/build-in-docker.sh`, `image/cloudfile_14.0/docker-build.sh`, and `deploy/compose/docker-compose.yml`.
- Django `5.2.*` - Seahub web application and CloudFile extension runtime, pinned in `../cloudfile-hub/requirements.txt` and `image/cloudfile_14.0/Dockerfile`.
- Django REST Framework `3.16.*` - REST APIs in `../cloudfile-hub/requirements.txt` and `../cloudfile-hub/cloudfile_ext/`.
- React `18.3.1` - Seahub frontend in `../cloudfile-hub/frontend/package.json`.
- Seafile server native stack - C/GLib/libevent/libsearpc core plus Go HTTP fileserver in `../cloudfile-server/configure.ac` and `../cloudfile-server/fileserver/go.mod`.
- Native Messaging - Local desktop bridge contract `cloudfile-local/v2` in `../cloudfile-local-agent/README.md`, consumed by the Manifest V3 extension in `../cloudfile-chrome-extension/README.md`.

**Testing:**
- Python E2E matrix scripts exercise a live Compose deployment from `tests/e2e/*.py`; baseline and capability workflows are in `.github/workflows/*-e2e.yml`.
- pytest is used in the server CI/test layer through `../cloudfile-server/pytest.ini` and `../cloudfile-server/ci/requirements.txt`.
- Go's standard test runner covers `../cloudfile-local-agent/internal/**/*_test.go` and Go server packages.
- Jest `30.3.0` with React Testing Library is configured in `../cloudfile-hub/frontend/package.json`.
- Shell/static gates are composed by `tools/run-checks.sh`, `tools/preflight-checks.py`, `tools/test-bootstrap-settings.py`, and `tools/check-upstream-patches.sh`.

**Build/Dev:**
- GNU Autotools, Make, CMake, GCC/build-essential, Vala, Cargo, and Go are installed by `build/cloudfile_14.0/cloudfile-build.sh` to assemble libevhtp, libsearpc, seafobj, seafdav, seafevents, cloudfile-server, and cloudfile-hub.
- Webpack `^5.105.0`, Babel 7, PostCSS 8, and npm build the Seahub static bundle from `../cloudfile-hub/frontend/package.json`.
- GitHub Actions runs static checks and live Compose matrices on `ubuntu-24.04` in `.github/workflows/checks.yml` and `.github/workflows/*-e2e.yml`.

## Key Dependencies

**Critical:**
- `Django==5.2.*`, `djangorestframework==3.16.*`, and `gunicorn==25.0.*` provide the Hub request/runtime layer in `../cloudfile-hub/requirements.txt`.
- `mysqlclient==2.2.*`, `PyMySQL==1.1.*`, and `SQLAlchemy==2.0.*` provide Python database access in `image/cloudfile_14.0/Dockerfile`; the Go fileserver uses `github.com/go-sql-driver/mysql v1.5.0` in `../cloudfile-server/fileserver/go.mod`.
- `redis==7.1.*` is the Hub Python client in `../cloudfile-hub/requirements.txt`; Go uses `github.com/go-redis/redis/v8 v8.11.5` in `../cloudfile-server/fileserver/go.mod`.
- `github.com/minio/minio-go/v7 v7.0.84` implements S3-compatible access in `../cloudfile-server/fileserver/go.mod`; `boto3` supports the Python seafobj wrapper in `image/cloudfile_14.0/Dockerfile`.
- `libsearpc >= 1.0`, GLib `>= 2.16.0`, libevent `>= 2.0`, Jansson `>= 2.2.1`, libcurl `>= 7.75.0`, hiredis `>= 0.15.0`, OpenSSL, libjwt, and libargon2 are native server requirements in `../cloudfile-server/configure.ac`.
- `pyjwt==2.13.*`, `djangosaml2==1.11.*`, `pysaml2==7.5.*`, and `python-ldap==3.4.*` support JWT, SAML, and LDAP paths in `../cloudfile-hub/requirements.txt` and `image/cloudfile_14.0/Dockerfile`.

**Infrastructure:**
- MariaDB `11.4` is the authoritative relational store in `deploy/compose/docker-compose.yml`.
- Redis `7-alpine` supplies cache/coordination/metrics infrastructure in `deploy/compose/docker-compose.yml`.
- Caddy `2-alpine` is the public reverse proxy and TLS endpoint in `deploy/compose/docker-compose.yml`; nginx remains inside the CloudFile application image via `image/cloudfile_14.0/Dockerfile`.
- Optional service image pins are SeaDoc `2.0-latest`, SeaSearch `1.0-latest`, Meilisearch `v1.10`, Metadata Server `14.0.3-testing`, Seafile AI `14.0-latest`, and OnlyOffice Document Server `8.2` in `deploy/compose/docker-compose.yml`.
- MinIO server and client use unpinned `latest` tags only for the `s3` validation profile in `deploy/compose/docker-compose.yml`; they are not the declared production object-store target.
- The local agent has one direct third-party dependency, `github.com/fsnotify/fsnotify v1.9.0`, in `../cloudfile-local-agent/go.mod`; release output is a single native binary.

## Repository Boundaries

**cloudfile-docker:**
- Own build pins, image construction, runtime configuration translation, Compose profiles, E2E orchestration, cross-repository specifications, and release metadata in `release.yaml`, `build/cloudfile_14.0/`, `image/cloudfile_14.0/`, `scripts/scripts_14.0/`, `deploy/compose/`, `docs/`, and `tests/e2e/`.
- Do not place Hub API/UI logic or server permission/storage enforcement in this repository; those belong to `../cloudfile-hub/` and `../cloudfile-server/` respectively.

**cloudfile-hub / cloudfile-server:**
- `../cloudfile-hub/` owns browser-facing Web/API/UI, extension registration, provider selection, and scheduled worker implementations.
- `../cloudfile-server/` owns authoritative permission decisions, repository/block/file operations, write lifecycle hooks, and native storage routing.
- Cross-layer semantics must remain aligned with specifications and matrices in `docs/acl-semantics.md`, `docs/fileop-lifecycle.md`, `docs/acl-cases.json`, and `docs/fileop-cases.json`.

**Local Clients:**
- `../cloudfile-local-agent/` is a separate Go Native Messaging host that downloads/opens files and performs constrained write-back; it is not a Compose service.
- `../cloudfile-chrome-extension/` is a separate Manifest V3 handoff bridge with no package manager or backend runtime; it does not perform file editing or hold Seafile credentials.

## Configuration

**Environment:**
- Operators copy `deploy/compose/.env.example` to an uncommitted `deploy/compose/.env`; both `.env.example` and `.env.verify` exist, but environment-file contents are outside this analysis.
- `scripts/scripts_14.0/bootstrap.py` translates `CF_ENABLE_*` capability switches and service/database settings into delimited blocks in Seahub and seaf-server configuration.
- `scripts/scripts_14.0/start.py` calls `write_cloudfile_config()` on every start so environment changes apply to existing deployments, not only first bootstrap.
- Keep all `CF_ENABLE_*` defaults false; disabling them must preserve native CE behavior as specified in `AGENTS.md` and verified by `tests/e2e/smoke.py` plus `tests/e2e/baseline.py`.

**Build:**
- `release.yaml` is the authoritative product/image/ref/schema manifest; `build/cloudfile_14.0/read-manifest.py` reads it without PyYAML.
- `release.yaml` selects `eaopen/cloudfile-server` and `eaopen/cloudfile-hub` `dev` refs and pins upstream seafobj, seafdav, seafevents, libsearpc, and libevhtp by commit SHA.
- `CF_SERVER_REF`, `CF_HUB_REF`, related URL/ref overrides, `CF_NODE_VERSION`, and `CF_PLATFORM` are controlled build overrides in `build/cloudfile_14.0/cloudfile-build.sh` and `build/cloudfile_14.0/build-in-docker.sh`.
- `CF_PLATFORM` supports `linux/amd64` and `linux/arm64`; build locally through Docker when the host is not Linux.

## Platform Requirements

**Development:**
- Require Git, a running Docker daemon, Docker Compose v2, and enough disk/RAM for an Ubuntu 24.04 source build; `build/cloudfile_14.0/build-in-docker.sh` supplies the C/Go/Python/Node toolchains inside Docker.
- Use `./tools/run-checks.sh` for static gates and `./tools/verify-local.sh` for the reproducible local Compose build/E2E path.
- Build artifacts under `build/cloudfile_14.0/seafile-server-<version>/` are generated inputs to `image/cloudfile_14.0/docker-build.sh`.

**Production:**
- Deployment target is a Linux Docker host running the single-host stack in `deploy/compose/docker-compose.yml`; the core profile requires `cloudfile`, MariaDB, Redis, and Caddy.
- Persist database, repository/config/log, cache, proxy, and enabled optional-service state beneath `deploy/compose/data/` as documented in `deploy/compose/README.md`; production backup scope must include database and Seafile data at minimum.
- Pin optional images currently using `latest` or `testing` before production rollout, especially SeaSearch, SeaDoc, Metadata Server, Seafile AI, and any MinIO validation image referenced by `deploy/compose/docker-compose.yml`.
- The Compose topology is a single-host reference, not a Kubernetes or multi-node HA implementation; external production database, cache, S3-compatible storage, TLS/DNS, monitoring, and backup services remain operator responsibilities per `docs/deployment.md`.

---

*Stack analysis: 2026-08-11*
