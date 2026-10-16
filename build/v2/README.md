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

This packages native file operations. It does not add OIDC/SSO routes or directory
ACL enforcement absent from the pinned source. Native API success does not
certify the Etech end-to-end cutover.

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
