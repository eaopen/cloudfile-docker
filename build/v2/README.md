# Native V2 DEV Runtime

Prepare the pinned CE14 source with `tools/prepare-v2-source.py`, then use the
existing CE14 dependency images and cache directory:

```sh
CF_BASE_IMAGE=cloudfile-build-base:ce14-v2 \
CLOUDFILE_RUNTIME_BASE=cloudfile/runtime-base:14.0.8-local \
CF_CACHE_DIR=/path/to/existing/.cache \
  bash build/v2/build-image.sh /path/to/prepared-source cloudfile:v2-dev
```

Both images must match the target architecture. The script defaults to the
Docker daemon's native platform; `CF_PLATFORM` explicitly selects another one.
No toolchain, APT or Node installation occurs during ordinary builds. Bases are
pinned to their existing local image IDs; missing bases are not pulled silently.
`DEV_BASE` remains a compatibility alias for the toolchain image.

If `CF_CACHE_DIR` is unset, the script reuses the existing
`.v0.1-local/cloudfile-docker/cloudfile_14.0/.cache` beside the repository, then
falls back to `build/v2/.cache`. BuildKit cache mounts are seeded from the same
`ccache`, `gocache`, `gomodcache`, `npm` and `pip` directories. Go's module/compile
keys and wheel/compiler metadata retain their normal platform handling.

Dependency layers have separate inputs: pinned libsearpc/libevhtp sources,
`go.mod`/`go.sum`, npm manifests, and Python requirements. C/Go application source,
frontend source and runtime/bootstrap files are copied afterward. Python package
installation precedes application source copies, preserving the runtime
intermediate layer across ordinary code changes. Build targets
`native-dependencies`, `frontend-dependencies`, and `python-dependencies` can also
be exported using standard Docker targets.

The DEV frontend build reuses the native script, omits minification/source maps
and bundled ESLint, and allows a 16 GiB JavaScript heap. The build-only webpack
preload avoids minifier worker OOM without editing upstream source.
Native media imports remain available during compilation, Babel's cache persists
between builds, and async chunks use `/seafile/media/assets/frontend/`.

Run against a dedicated MariaDB and Redis on a private Docker network. Supply a
private, untracked environment file with `DB_HOST`, `DB_ROOT_PASSWORD`,
`DB_PASSWORD`, `REDIS_HOST`, `DJANGO_SECRET_KEY`, `JWT_PRIVATE_KEY`, `ADMIN_EMAIL`,
`ADMIN_PASSWORD`, and `PUBLIC_URL`. The database user and three native database
names belong exclusively to this fresh DEV instance.

```sh
docker run -d --name cloudfile-v2-dev --network "$DEV_NETWORK" \
  --env-file "$DEV_ENV_FILE" -p "$DEV_PORT:80" \
  -v "$FRESH_DEV_DATA:/shared" cloudfile:v2-dev
```

For a fresh volume, startup imports native SQL into new schemas and installs the
three approved V2 tables. It collects native assets and starts native RPC, Go
fileserver, Seahub and nginx.

Fresh installs use `/cfile/` for Web/API/login and `/cfhttp` for file URLs.
CloudFile's own ingress also accepts `/seafile/` and `/seafhttp/`. Both Web paths
use the single canonical SITE_ROOT, session and CSRF cookies. Compatibility API
requests are internally rewritten, preserving their method and body. Existing
volumes retain their configured SITE_ROOT and file-service path (old settings
without these values retain `/seafile/` and `/seafhttp`). This changes no IdP
callbacks automatically. Run `python3 -m unittest discover -s tests -p
'test_v2_web_paths.py'`; nginx-equipped environments also exercise the real proxy.

Fresh deployments can seed native `OAUTH_*`, `LOGIN_URL` and
`LOGIN_REDIRECT_URL` literals in `/shared/conf/seahub_settings.py`; startup retains
them on later boots. The optional OIDC login at `<SITE_ROOT>oidc/login/` uses the
same configured native OAuth callback and CE account. It additionally requires
`OAUTH_OIDC_ISSUER`, `OAUTH_OIDC_JWKS_URI`, `openid` scope and the stable UID mapped
to `login_id`. It supports RS256 and validates the ID Token before authentication.

This packages native file operations. CloudFile V2 directory ACL is a built-in,
always-on capability when the matched Hub/Server V2 sources are assembled:
there is no `v2_acl_enabled` option or public-rule publication feature switch.
Protected libraries still require the current user, native repository rights
and C/Go byte/final-commit checks; underlying SQL/subject failures deny.
Legacy unscoped operations on protected repositories remain restricted.
Native API success does not certify the Etech end-to-end cutover.

An existing CE14 volume with `seafile/seafile-data` is reused in place. Keep its
database environment, network, published port and `/shared` mount. Exclude the
old image's `PATH`, `PYTHONPATH` and `LD_LIBRARY_PATH` from the environment passed
to the replacement so the new image selects its own native binaries and modules.
The native JWT key is read from the existing `seafile/conf/.env`.

Existing databases, accounts, library IDs and file objects are neither imported
nor reset. Runtime configuration under `/run/cloudfile-conf` reuses native OAuth
settings and points all services at the same RPC socket. Original configuration
and Compose files stay intact. Existing extension records remain stored; this
does not imply that the removed legacy extension APIs or ACL enforcement run.

## Existing Meilisearch Search

V2 Search has no separate ENABLE or provider selector. When
`CF_MEILISEARCH_URL` is configured, the worker starts and Search uses that
external service. `CF_MEILISEARCH_API_KEY` holds its credential and
`CF_MEILISEARCH_INDEX` optionally overrides the default `cloudfile_files`
index. Without a configured endpoint, or while Meilisearch is unavailable,
only enhanced Search returns `SEARCH_UNAVAILABLE`; native file services continue.
Retired `CF_ENABLE_SEARCH` / `CF_PROVIDER_SEARCH` are ignored.
Meilisearch must already contain a `cloudfile_files` index using the existing
`repo_id/path/object_type/tags/dirs` document fields. No SQL tables are added.

The authenticated `GET /api/v2.1/cloudfile/search/` endpoint accepts `repo_id`,
`q`, `path`, `limit` and a signed five-minute `cursor`. Results use the existing
file-browser response contract, with current CE object and path checks before
publication. Native Tag tables supply returned tags. Keyword matching uses the
file/directory basename and Tags; ancestor path names only constrain the requested
scope and never make every descendant a keyword hit. Configured `cf_dir_acl`
subtrees are excluded until V2 directory-policy enforcement is integrated;
queries rooted inside them return 503. Virtual/encrypted libraries and
directory-only shares are not certified by this restoration. Exhausting the
configured Meilisearch candidate window returns 409 and requires a narrower query.

A separate search worker follows native commit diffs and Tag changes every
60 seconds. It confirms Meilisearch tasks before writing the disposable
`/shared/search-v2-checkpoint.json`. On the first start against an existing index,
set `CF_SEARCH_BOOTSTRAP_BEFORE` to a Unix timestamp preceding the V2 cutover;
the worker catches up from the latest native commit at or before that time.
Missing libraries use fixed-commit directory pages. The existing index is never
cleared. A failed batch retains its previous checkpoint for retry. Search
failures do not terminate native file services. This path restores the existing
file browser; it does not activate the separately designed resource-search POST API.

## Built-in capability defaults (2026-10-17)

A new V2 installation always installs the three core extension tables and the
separate `cf_edit_guard` Checkout table. C/Go native fences and Hub discover
Guard from the database schema; the historic `CF_V2_CHECKOUT_ENABLED`,
`CF_V2_AGENT_EDIT_ENABLED` and `[cloudfile] v2_edit_enabled` parameters
are not accepted as activation or bypass controls. A reused CE14 installation
without Guard retains optimistic editing and requires an approved, explicit
schema migration followed by restart before Checkout becomes available.

CloudFile directory ACL and native CE Tag are always-on capabilities. Optional
Search, Office and other external integrations depend on their actual
connections. Connection credentials, existing OIDC configuration, storage-root
overrides and measured cache TTL parameters are *not* feature flags. No live
volumes, original deployment config or production database are rewritten by
this source change.
