# External Integrations

**Analysis Date:** 2026-08-11

## APIs & External Services

**Identity and Directory Services:**
- Authentik stable `2026.5.6` is the documented reference identity broker in `docs/features/sso-authentik.md`; CloudFile uses Seahub's generic OAuth2/OIDC Authorization Code flow rather than an Authentik-specific SDK.
  - Implementation: configuration generation in `scripts/scripts_14.0/bootstrap.py`, login/callback handling in `../cloudfile-hub/seahub/oauth/views.py`.
  - Auth: `CF_SSO_OAUTH_CLIENT_ID`, `CF_SSO_OAUTH_CLIENT_SECRET`, explicit authorization/token/user-info endpoints, provider identifier, scope, and claim mapping.
  - Status: generic OIDC wiring exists; Authentik-specific discovery, logout, group provider, and full E2E validation are not implemented.
- Direct LDAP, SAML/ADFS, Shibboleth, roles, and 2FA reuse Seafile CE paths, mapped from deployment settings by `scripts/scripts_14.0/bootstrap.py`.
  - SDK/Client: `python-ldap`, `djangosaml2`, `pysaml2`, and Seahub built-ins from `../cloudfile-hub/requirements.txt`.
  - Auth: named `CF_LDAP_*`, `CF_ADFS_*`, `CF_SHIBBOLETH_*`, role JSON, and 2FA settings; certificate/private-key material is mounted at runtime and must not be committed.
- CloudFile organization synchronization supports `static` and `external-service` directory providers in `../cloudfile-hub/cloudfile_ext/sso/` and `scripts/scripts_14.0/bootstrap.py`.
  - Auth: `CF_SERVICE_SSO_DIRECTORY_SECRET` for the external service contract.
  - Runtime: periodic synchronization requires the `cf-worker` service from the `worker` profile in `deploy/compose/docker-compose.yml`.

**Search:**
- SeaSearch is the default upstream search service, image `seafileltd/seasearch:1.0-latest`, in the `search`/`full` profiles of `deploy/compose/docker-compose.yml`.
  - Client/config: Seahub upstream search path plus generated settings from `scripts/scripts_14.0/bootstrap.py`.
  - Auth: `CF_SEASEARCH_TOKEN` and first-start service credentials.
  - Status: external official component; CloudFile does not own the search engine.
- Meilisearch `v1.10` is the alternative provider in `deploy/compose/docker-compose.yml`; CloudFile owns the provider/index worker and permission filtering in `../cloudfile-hub/cloudfile_ext/search/`.
  - Client/config: HTTP provider selected by `CF_PROVIDER_SEARCH=meilisearch`; incremental indexing runs in `cf-worker`.
  - Auth: `MEILI_MASTER_KEY` on the service and matching `CF_MEILISEARCH_API_KEY` on the client.
  - Status: live E2E coverage exists in `tests/e2e/search_matrix.py` and `.github/workflows/search-e2e.yml`; external-source indexing is only on this provider path.

**Metadata and Tags:**
- Seafile Metadata Server is wired as `cloudfile-metadata`, default image `seafileltd/seafile-md-server:14.0.3-testing`, in `deploy/compose/docker-compose.yml`.
  - Client/config: upstream Seahub/seafevents metadata chain, configured through `CF_METADATA_SERVER_URL` and capability switches in `scripts/scripts_14.0/bootstrap.py`.
  - Auth: deployment-defined service token/settings; no public anonymous interface is intended.
  - Status: Compose and E2E coverage exist in `tests/e2e/metadata_matrix.py` and `.github/workflows/metadata-e2e.yml`; the default testing image must be replaced by a validated pin for production.

**AI and Model APIs:**
- Seafile AI is an optional official service, default image `seafileltd/seafile-ai:14.0-latest`, in the `ai`/`full` profiles of `deploy/compose/docker-compose.yml`.
  - Client/config: Seahub's existing Seafile AI integration; model configuration starts from `deploy/compose/seafile_ai_config.example.yaml` and is mounted into the shared runtime configuration.
  - Auth: `CF_AI_SECRET_KEY` secures Hub-to-AI communication; model-provider API keys live only in runtime configuration.
  - Models: external OpenAI-compatible APIs or operator-hosted compatible services such as Ollama/LM Studio are supported by the upstream AI service, as documented in `docs/features/seafile-ai.md`.
  - Status: image/profile/config wiring exists, but there is no CloudFile AI E2E workflow; metadata and Redis are prerequisites and external-source AI ingestion is not implemented.

**Office, Preview, and Conversion:**
- OnlyOffice Document Server `8.2` is the optional office editor in `deploy/compose/docker-compose.yml`.
  - Client/config: Seahub's CE OnlyOffice integration plus CloudFile callback validation/lock coordination described in `docs/features/file-collaboration.md`.
  - Auth: `ONLYOFFICE_JWT_SECRET`; enable with `CF_ENABLE_ONLYOFFICE` and the `office` profile.
- SeaDoc `2.0-latest` is the optional conversion/export service in the `convert`/`full` profiles of `deploy/compose/docker-compose.yml`.
  - Auth: shared `JWT_PRIVATE_KEY` generated and persisted by the operator.
  - Status: service wiring exists; production must pin a validated image and preserve JWT material across restarts.
- Local preview tools such as Poppler and ExifTool are installed directly in `image/cloudfile_14.0/Dockerfile`; these are in-container executables, not remote APIs.

**Local Application Bridge:**
- `../cloudfile-chrome-extension/` listens only for completed `.cloudfile` session downloads and forwards paths over Chrome Native Messaging; permissions are `downloads`, `nativeMessaging`, and `storage` in `../cloudfile-chrome-extension/manifest.json`.
- `../cloudfile-local-agent/` claims short-lived, one-time Hub sessions, downloads content directly from CloudFile, opens a local application without a shell, and uses constrained write-back capabilities as documented in `../cloudfile-local-agent/README.md`.
  - Protocol: `cloudfile-local/v2`.
  - Auth: one-time ticket plus an explicit local origin allowlist; no browser cookies, long-lived Seafile token, OAuth client secret, or localhost HTTP listener.
  - Status: code and unit tests exist; signed cross-platform packages and complete browser-to-Hub E2E validation remain pending.

**External Content Sources:**
- Current external-source integration is a `local-path` provider: SMB/NFS is mounted by the host, then exposed read-only to the container under allowed roots configured by `CF_EXTERNAL_SOURCES_ROOTS` in `scripts/scripts_14.0/bootstrap.py`.
  - Implementation: registration, authorization, browsing, download, and scan code under `../cloudfile-hub/cloudfile_ext/external_sources/`.
  - Auth: CloudFile stores authorization metadata, but does not store SMB/NFS protocol credentials or execute CIFS/NFS mounts.
  - Status: E2E coverage exists in `tests/e2e/external_sources_matrix.py` and `.github/workflows/external_sources-e2e.yml`; native SMB provider, write-through, sync, and Seafile history are not implemented.
- OpenList/rclone federation is an architectural plan only in `docs/features/external-directory-mount.md`; no runtime adapter, credential service, Compose container, SDK, or E2E evidence exists.

## Data Storage

**Databases:**
- MariaDB `11.4` is the Compose database in `deploy/compose/docker-compose.yml`.
  - Connection: `SEAFILE_MYSQL_DB_HOST`, `SEAFILE_MYSQL_DB_PORT`, `SEAFILE_MYSQL_DB_USER`, `SEAFILE_MYSQL_DB_PASSWORD`, and per-database name settings consumed by `scripts/scripts_14.0/bootstrap.py`.
  - Clients: native mysqlclient/MariaDB client in `../cloudfile-server/`, `mysqlclient==2.2.*` and optional PyMySQL/SQLAlchemy in the Python image, and `go-sql-driver/mysql v1.5.0` in `../cloudfile-server/fileserver/go.mod`.
  - Schemas: ccnet, seafile, and seahub databases; CloudFile `cf_*` extension tables are created from `../cloudfile-server/scripts/sql/mysql/cloudfile.sql` in the seafile database, with schema version `1` in `release.yaml`.
- SQLite support remains present in upstream server/Hub tooling, including `../cloudfile-server/configure.ac` and `../cloudfile-hub/sql/sqlite3.sql`, but the supported Compose deployment uses MariaDB.

**File and Object Storage:**
- Local filesystem is the default repository/block/config/log storage beneath the mounted Seafile data volume configured by `deploy/compose/docker-compose.yml` and documented in `deploy/compose/README.md`.
- S3-compatible storage supports separate commit, filesystem-object, and block buckets using `S3_COMMIT_BUCKET`, `S3_FS_BUCKET`, `S3_BLOCK_BUCKET`, endpoint/region/signature settings, and runtime credentials mapped by `scripts/scripts_14.0/bootstrap.py`.
  - Clients: C/Go backends in `../cloudfile-server/common/` and `../cloudfile-server/fileserver/`, `minio-go v7.0.84`, and Python `boto3` from `image/cloudfile_14.0/Dockerfile`.
  - Multi-storage: storage classes and repository mappings use `CF_STORAGE_CLASSES_JSON` and server routing code such as `../cloudfile-server/common/storage-backend-multi.c`.
  - Validation: MinIO is the only verified S3-compatible target, exercised by `tests/e2e/storage_matrix.py` and `.github/workflows/storage-e2e.yml`; AWS S3, Ceph RGW, and other vendors are not in the current compatibility claim.
- MinIO `latest` plus `minio/mc:latest` are local test services in the `s3` profile of `deploy/compose/docker-compose.yml`, not the production storage recommendation.

**Caching and Coordination:**
- Redis `7-alpine` is the Compose cache/service bus in `deploy/compose/docker-compose.yml`.
  - Connection/auth: Redis host/password settings are passed to Hub, fileserver, workers, and optional AI/metadata services; file-based runtime secret loading is implemented by `scripts/scripts_14.0/enterpoint.sh`.
  - Clients: Python `redis==7.1.*` in `../cloudfile-hub/requirements.txt` and Go `go-redis/v8 v8.11.5` in `../cloudfile-server/fileserver/go.mod`.
  - Uses: cache, coordination, metrics publication, and dependencies of optional metadata/AI flows.

## Authentication & Identity

**Auth Provider:**
- Primary documented enterprise route: Authentik as an external broker, connected through generic Seahub OAuth2/OIDC in `docs/features/sso-authentik.md` and `scripts/scripts_14.0/bootstrap.py`.
- Compatible upstream routes: direct LDAP, SAML/ADFS, Shibboleth, local accounts, 2FA, and role permissions from Seahub, configured through `scripts/scripts_14.0/bootstrap.py`.
- API consumers use Seahub token/session authorization; cross-service calls use separate service secrets or JWTs appropriate to SeaSearch, metadata, AI, OnlyOffice, and SeaDoc.
- Keep a non-federated local administrator for identity-provider outage recovery as prescribed by `docs/features/sso-authentik.md`.

## Monitoring & Observability

**Error Tracking:**
- No Sentry, OpenTelemetry collector, hosted APM, or external error-tracking SDK is detected in `cloudfile-docker`, `../cloudfile-hub/`, or the documented Compose stack.

**Logs:**
- Container logs are accessed through `docker compose logs`; application logs live in the persisted Seafile log directory described by `deploy/compose/README.md`.
- Internal syslog-ng, logrotate, and cron setup comes from `base_scripts/services/syslog-ng/` and `scripts/scripts_14.0/logrotate-conf/`.
- GitHub Actions failure handlers collect Compose state and tail CloudFile/Seahub/seafevents logs in `.github/workflows/*-e2e.yml`.
- The Go fileserver publishes selected metrics through Redis in `../cloudfile-server/fileserver/metrics/metrics.go`; no dashboard or long-term metric store is provisioned by `deploy/compose/docker-compose.yml`.

**Health Checks:**
- Compose health/dependency readiness is defined in `deploy/compose/docker-compose.yml`, while `scripts/scripts_14.0/bootstrap.py` waits for MariaDB/nginx and `tools/verify-local.sh` waits for HTTP/API readiness.
- Capability matrices in `tests/e2e/*.py` are the operational integration checks; an optional service being present in Compose does not by itself prove the feature is complete.

## CI/CD & Deployment

**Hosting:**
- Supported reference hosting is a Linux Docker host running `deploy/compose/docker-compose.yml`; Caddy terminates public HTTP/TLS and proxies to the CloudFile container's nginx.
- Public DNS, certificates, production S3/SMB/NFS, external databases/caches, high availability, backup, and capacity planning are deployment responsibilities documented in `docs/deployment.md`.
- There is no Kubernetes, Helm, Terraform, managed-cloud deployment, or multi-node orchestration detected in this repository.

**CI Pipeline:**
- GitHub Actions static checks run from `.github/workflows/checks.yml` using `actions/checkout@v4`, `actions/setup-python@v5` with Python `3.12`, and `actions/setup-go@v5`.
- Baseline and capability-specific live integration jobs run on `ubuntu-24.04` in `.github/workflows/build-and-e2e.yml` and `.github/workflows/*-e2e.yml`.
- Release inputs are pinned in `release.yaml`; image construction is implemented by `build/cloudfile_14.0/` and `image/cloudfile_14.0/`. No automatic registry deployment or production rollout pipeline is detected in the current workflow set.

## Environment Configuration

**Required Core Env Vars:**
- Host/TLS/admin: `SEAFILE_SERVER_HOSTNAME`, `SEAFILE_SERVER_PROTOCOL`, `INIT_SEAFILE_ADMIN_EMAIL`, `INIT_SEAFILE_ADMIN_PASSWORD`, and Caddy TLS settings used by `deploy/compose/docker-compose.yml` and `scripts/scripts_14.0/bootstrap.py`.
- Database: `SEAFILE_MYSQL_DB_HOST`, `SEAFILE_MYSQL_DB_PORT`, `SEAFILE_MYSQL_DB_USER`, `SEAFILE_MYSQL_DB_PASSWORD`, and ccnet/seafile/seahub database names consumed by `scripts/scripts_14.0/bootstrap.py`.
- Feature toggles: every `CF_ENABLE_*` switch listed by `scripts/scripts_14.0/bootstrap.py`; all must default false.
- Optional integrations add only their scoped settings: `CF_SSO_*`, `CF_LDAP_*`, `CF_ADFS_*`, `CF_SEASEARCH_*`, `CF_MEILISEARCH_*`, `CF_METADATA_*`, `CF_AI_*`, `S3_*`, `ONLYOFFICE_JWT_SECRET`, `JWT_PRIVATE_KEY`, and external-source settings.

**Secrets Location:**
- Runtime values are supplied through an uncommitted `deploy/compose/.env` or mounted secret files consumed by `scripts/scripts_14.0/enterpoint.sh`; `.env` contents and runtime data must never be committed.
- TLS/SAML certificates and keys, AI model configuration/API keys, JWT keys, object-store credentials, and local-agent trust configuration remain in runtime data/config locations described by `deploy/compose/README.md`, `docs/features/seafile-ai.md`, `docs/features/sso-authentik.md`, and `../cloudfile-local-agent/README.md`.
- `.env.example` and `.env.verify` exist under `deploy/compose/` as configuration templates/verification inputs; this map records existence only and does not reproduce their contents.

## Webhooks & Callbacks

**Incoming:**
- OAuth2/OIDC callback: `/oauth/callback/` on Seahub, implemented by `../cloudfile-hub/seahub/oauth/views.py` and configured by `scripts/scripts_14.0/bootstrap.py`.
- OnlyOffice save callbacks enter Seahub and must pass JWT verification plus idempotent write/lock handling described in `docs/features/file-collaboration.md`.
- External SSO directory service callbacks/synchronization use the versioned CloudFile Hub service contract under `../cloudfile-hub/cloudfile_ext/sso/`, authenticated with `CF_SERVICE_SSO_DIRECTORY_SECRET`.
- Local-agent claim and write-back requests terminate at CloudFile Hub endpoints implemented by `../cloudfile-hub/cloudfile_ext/file_actions/apis.py` and `../cloudfile-hub/cloudfile_ext/file_actions/service.py`; tickets are short-lived and single-use.

**Outgoing:**
- Seahub redirects browsers to configured OAuth2/OIDC authorization endpoints and calls token/user-info endpoints as implemented in `../cloudfile-hub/seahub/oauth/views.py`.
- Hub and workers call SeaSearch or Meilisearch, Metadata Server, Seafile AI, OnlyOffice, SeaDoc, external directory services, and local-path sources according to providers configured in `scripts/scripts_14.0/bootstrap.py`.
- Seafile AI may call an operator-selected OpenAI-compatible model endpoint from runtime model configuration; CloudFile does not bundle a model provider or send data when AI is disabled.
- No generic outbound webhook platform, message queue service, email SaaS, billing provider, analytics platform, or telemetry export is detected in the current repository set.

---

*Integration audit: 2026-08-11*
