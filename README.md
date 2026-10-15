# CloudFile Docker

[English](README.md) | [简体中文](README.zh-CN.md)

Source builds, images, Compose deployment, release manifests and shared technical contracts for CloudFile, based on Seafile CE 14. The build version described here is `14.0.0-cf.0`; [`release.yaml`](release.yaml) is the authority for component refs and versions.

This repository packages CloudFile Server and Hub for deployment. Product guidance and plans live in the [CloudFile product documentation](https://github.com/eaopen/cloudfile/blob/main/docs/en/README.md). Technical references linked here are currently maintained in Chinese unless indicated otherwise; feature support follows the selected release.

## Components

| Project | Responsibility | Documentation |
| --- | --- | --- |
| `cloudfile-server` | Seafile Server fork; permission enforcement, write lifecycle and storage | [Server](https://github.com/eaopen/cloudfile-server/blob/dev/README.md) |
| `cloudfile-hub` | Seahub fork; Web/API, extension registration and UI | [Hub](https://github.com/eaopen/cloudfile-hub/blob/dev/README.md) |
| `cloudfile-docker` | Builds, images, deployment, shared contracts and release manifests | [Technical index (Chinese)](docs/README.md) |
| `cloudfile-local-agent` | Native Messaging Host for local viewing and editing | [Agent](https://github.com/eaopen/cloudfile-local-agent/blob/dev/README.md) |
| `cloudfile-chrome-extension` | Restricted bridge between the browser and Agent | [Extension](https://github.com/eaopen/cloudfile-chrome-extension/blob/dev/README.md) |
| `seafile`, `seafobj` | Upstream dependencies, not CloudFile extension implementations | Their upstream README files |

## Scope

- Reuse Seafile CE libraries, synchronization, WebDAV, sharing, previews and the LDAP/SAML/OIDC, OnlyOffice, metadata and AI interfaces present in its source.
- CloudFile adds extension registration, directory ACLs, organization mapping, auditing, replaceable search, multiple storage classes, external sources, write lifecycle support and corresponding build checks.
- External services include MariaDB, Redis, Caddy, SeaSearch, Meilisearch, Metadata Server, seafile-ai, OnlyOffice, SeaDoc and storage. Operators manage their licenses, capacity, backups and availability.

CloudFile builds its own CE 14 packages and images from manifest-pinned sources to include its server extensions. See the [technical overview (Chinese)](docs/overview.md).

## Quick Deployment

```bash
git clone https://github.com/eaopen/cloudfile-docker.git
cd cloudfile-docker/deploy/compose
cp .env.example .env
```

Set the hostname, administrator password and database password in `.env`, then run:

```bash
docker compose config --quiet
docker compose up -d
docker compose logs -f cloudfile
```

New capability flags default to disabled; consult the selected release for actual defaults. See the [Compose guide (Chinese)](deploy/compose/README.md) for optional profiles, feature flags, TLS, persistent directories and backup scope.

## Build From Source

Requires Linux or Docker:

```bash
./build/cloudfile_14.0/build-in-docker.sh 14.0.0-cf.0
./image/cloudfile_14.0/docker-build.sh 14.0.0-cf.0
```

See the [build guide (Chinese)](build/README.md) for dependencies, ref overrides and output locations.

## Verification

```bash
./tools/run-checks.sh
./tools/verify-local.sh preflight
```

For the full baseline build and system regression:

```bash
./tools/verify-local.sh
```

Use `./tools/verify-local.sh cap <capability>` for capability checks. Supported names are defined in the script's `CAPABILITIES` table.

## Documentation

The following technical references are in Chinese:

- [Index](docs/README.md) and [overview](docs/overview.md): reading order, upstream strategy and repository scope.
- [Architecture](docs/architecture.md): components, control plane and data plane.
- [Deployment](docs/deployment.md) and [configuration](docs/configuration.md): deployment options, operational boundaries and environment variables.
- [Capability matrix](docs/feature-matrix.md): reuse, extensions, external services, limitations and verification status.
- [Historical document policy](docs/history/README.md).

Read deployment and configuration before installing, and check capability status against the selected release.

## License

This repository uses [Apache License 2.0](LICENSE.txt). Upstream source, official binary images and third-party components retain their own licenses.
