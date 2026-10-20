# Native V2 DEV Runtime

> Server/Hub/Docker `dev` is the only default development source. Source assembly
> resolves the local Server/Hub `dev` refs to exact SHAs before reading files;
> update the local `dev` refs first. The pinned `source-set.json` is retained
> only as an explicitly selected historical snapshot with `--source-set`.
> Cross-repository integration checks run on manual `workflow_dispatch`, not
> on every code or documentation change. Neither source check publishes an image.

Prepare the CE14 source plus reviewed current CloudFile `dev` overlays with
`python3 tools/prepare-v2-source.py --workspace . --output /path/to/prepared-source`
from a three-repository workspace. To reproduce a historical source snapshot,
supply `--source-set build/v2/source-set.json` explicitly instead.

Then use the existing dependency images and cache directory:

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

Existing CE14 nested (`seafile/seafile-data` + `seafile/conf`) and flat
(`seafile-data` + `conf`) volumes are reused in place. Flat V2 restarts also
follow the reuse path; they must not bootstrap another native database.
Ambiguous/partial data mounts or conflicting persisted database bindings stop
startup before schema installation. Native RPC reads each discovered physical
repository before HTTP is exposed; full integrity remains native `seaf-fsck`
and native release upgrade scripts remain authoritative for version changes.
See [native upgrade boundaries](../../docs/v2-native-upgrade-discovery-20261017.md). Keep its
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

## Etech P0 Integration

Etech's existing `cloudDirectorySync` PowerJob should run every 600 seconds
using the native admin channel to
`POST /api/v2.1/admin/cloudfile/directory/entities/sync/`.
CloudFile fetches the existing `/groups?view=entities` snapshot with its
short-lived machine JWT. The periodic task only reconciles CE Group entities
and `cf_sso_group_map`, **not** all users or native `GroupUser` membership.
The on-demand UID projector refreshes GroupUser after login or TTL expiry.
No v0.9 full-member directory worker may run in parallel.

The built-in Hub adapter consumes the existing EAP Directory base URL through
`CF_DIRECTORY_URL`, `CF_DIRECTORY_KEY_ID`, and `CF_DIRECTORY_SECRET`.
Use the same machine credential as EAP's `cloudfile.identity-directory.auth`;
never put deployment secrets into this repository. The issuer/audience defaults
are `cloudfile-sso` and `eap-directory`. `CF_DIRECTORY_GROUP_OWNER` identifies an
existing active native service administrator for flat Group creation. Native
Redis cache LOCATION supplies shared subject freshness. Seeded Directory
connection settings survive restarts and may be supplied through environment
variables; there is no new feature flag.

Identity pre-creation independently checks the Directory UID and active status;
first SSO login reuses the native UID account. Group members refresh only for the
current user at the bounded TTL. Missing/failed Directory or Redis fails closed.
No extra user/member tables or legacy authorization routes are added.

Native ordinary copy/move is synchronous while both library ACL fences are held;
protected or virtual scopes still reject transfers. The source-set pins must
select matching Hub fence writers and native transfer guards. Local native byte,
revocation and race tests are separate from real Etech DEV and SSO acceptance.

### 2026-10-17 Hub directory-page update

The Hub pin includes the native `seahub/api2/endpoints/dir.py` integration in
addition to `cloudfile_ext/v2`. Both must ship together: copying only the
extension leaves EAP `start`/`limit` requests on the unpaged CE handler.
The existing V2 ACL authority filters every child; no new discovery API,
schema migration, native binary rebuild, or data relocation is required.
For a runtime-layer DEV build, use the deployed immutable image digest as
base, replace these pinned Python files, update the source receipt, and run
the directory-page/ACL tests before publishing. Preserve database bindings
and all original storage mounts when replacing the DEV container.

### 2026-10-18 Hub performance source group

The Hub pin includes subject-readiness reuse, ACL-filtered search and bounded
native tag reads. Ship `seahub/api2/endpoints/repo_tags.py` with the V2 overlay
and URL/directory seams: otherwise CE still computes tag file counts by default
and the pinned performance fix is absent from the actual image. This source
group changes no Server pin, native binary, runtime dependency or schema.

### Browser-session Tag batch correction (2026-10-18)

The Hub pin includes the live DEV correction for JSON tag batches authenticated
by a native browser session. Cache the size-limited request body before native
CSRF validation consumes the JSON stream; keep both CSRF and authentication
checks. Token callers and the V2 batch schema are unchanged. The regression
reproduces RawPostDataException on the prior image; no schema, tag migration or
native binary rebuild is involved.


## 内部文件读取：复用 Seafile 原生票据（2026-10-19）

本候选版本固定 Server `89ae96652389024730ac9d3927ed3be908534ce9`
与 Hub `bfc7651f188b8a537a466e7ee0bc143bc6acb85e`。
Server 使用受保护 tag `cf-v2-download-20261019`，Hub 使用
`cf-v2-download-oauth-20261020` 固定上述提交：禁止移动和删除，
使临时候选分支清理后仍可获取源码。构建仍以 `source-set.json` 的完整 SHA 为准，
不把可变分支或 tag 名代替 SHA 锁定。
注意：干净 CE14 V2 源码必须从专用最小候选提交抽取；最新 fork dev
包含不在干净 CE14 依赖集合内的历史模块（如 SSO），不能直接以最新
dev SHA 作为 V2 build overlay。完整 fork dev 对应的开发整合 PR 分别是
Server #12 和 Hub #28，两者不应直接用于 clean-source-set 构建。
两个组件需要同步发布：Hub 对当前账号及目标文件使用 V2 Authority
做一次签发权限检查；Server 从该规范路径解析当前文件对象，签发
最多一小时的原生票据；C 和 Go Fileserver 只为此类受信任单文件
读票据跳过旧的无范围库级 ACL 守卫。票据消费只查原生对象/操作/过期，
无新表、无每次读取 Hub/ACL SQL、无主动撤权。改权限只影响后续签发，
已签发链接自然到期。

Etech 需要配合 `jcetech/etech-eap` PR #9 请求 `reuse=1`，
允许浏览器/预览工具重复 GET、HEAD、Range。它暂时保留原有 Redis
浏览器跳转票据，避免修改已使用的前端接口；ZIP 中转仍一次性。
HTTP/HTTPS 与 `/cfhttp`、`/seafhttp` 继续由部署代理决定。

兼容边界：原生无路径旧票据、虚拟库、历史版本、ZIP、块下载以及
上传/独占编辑不借此修复放宽权限。Hub 返回实际 native TTL；
Etech 按默认 3600 秒配置并保留 5 秒余量，如现场缩短 native TTL，
必须同步缩短 Etech 的中转有效期。

此处只是构建版本锁定，**不代表已在 DEV 部署或完成文件预览 E2E**。
上线需分别验证 C/Go 构建、授权/拒绝签发、重复读取及到期行为，
并逐仓排除与本修复无关的基线 CI 失败。


## CI test source boundaries

`tools/run-checks.sh` runs full-fork extension and current-contract tests in
separate interpreters from the V2 HTTP suite. `tools/check-hub-contracts.py --v2`
assembles the exact immutable `source-set.json` production files, prints both
pins, and runs current V2 regression tests against those modules. Full-fork
native tag/OAuth seams are not interchangeable with the reviewed clean overlay.
No production pin or feature behavior changes as part of this CI repair.

The fast HTTP fixture retains real Django/DRF permissions, session CSRF and JSON
parsing. Only native RPC/accounts/ORM boundaries are explicit test doubles;
unconfigured native calls raise errors. Passing these unit tests is not native
runtime or DEV browser acceptance. Database/Redis cases keep their declared
prerequisites; the existing native-and-schema/native-ce14-runtime jobs cover the
actual clean CE14 database and byte-transfer path.


The 2026-10-19 compatibility follow-up keeps root-relative native download
requests canonical before authorization and leaves commit-specific history
requests on their original path. The new Hub overlay contains only this native
FileView change on top of the previous reviewed overlay; no full-fork modules
are imported. Current dispatch regressions run against the newly selected pin.

### DEV 发布前的 OAuth 现场修补保留（2026-10-20）

DEV 的 OAuth Profile 唯一性冲突修补原先只存在于容器写层。为避免本次下载更新
覆盖已运行的登录修补，将其捕获到干净 Hub 提交 `bfc7651f188b8a537a466e7ee0bc143bc6acb85e`，
并由禁止更新/删除的 tag `cf-v2-download-oauth-20261020` 保留。
下载模块与上一版完全相同；既有 UID 绑定和登录主体刷新检查继续执行。
完整 fork dev 已有对应 Profile 冲突处理，无需替换其 OAuth 实现。
