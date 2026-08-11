# Phase 1: Security and Collaboration Contract Closure - Research

**Researched:** 2026-08-11
**Domain:** 跨仓库 ACL 最终裁决、写操作事实、代际锁、本地编辑、OnlyOffice 与可审计门禁
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

### ACL Search And Sync Authority
- Apply one backend-independent effective CloudFile ACL evaluator to every search candidate before totals, snippets, serialization, caching, or return; SeaSearch and Meilisearch must obey identical authorization semantics.
- Treat inactive ACL as native CE pass-through, active valid state as allow/deny, and active unavailable or malformed authority state as denial.
- Do not cache an unrestricted answer across ACL changes; use revision-aware invalidation or reevaluate current ACL state at the final boundary.
- Verify positive, invisible, denied, outage, malformed, immediate-revocation, restart, pagination, total, snippet, and cache behavior for both search backends and direct sync/fileserver paths.

### Mutation Facts And Lock Fencing
- Use one stable operation identity for a logical batch or write and require exactly one PREPARE followed by one terminal COMMITTED or ABORTED fact.
- Require the current generation for every racing mutation, save, callback, write-back, and lock release; stale or absent generations cannot release or overwrite newer work.
- A post-operation observer failure may be retried or audited but cannot roll back a completed native write or fabricate a second terminal fact.
- Cover browser/API, fileserver/sync, WebDAV, batch delete, retry, partial failure, callback, and abort paths using the shared file-operation vocabulary.

### Versioned Local Edit Contract
- Introduce an explicit protocol version and a canonical session/descriptor schema; the pre-claim response includes the file name and fields the frontend needs before ticket claim.
- Keep the ticket one-time, short-lived, origin-bound, and free of browser cookies or long-lived CloudFile credentials; fail closed on unsupported protocol versions.
- Write-back updates the existing file and carries version/generation preconditions; it never creates an unrelated replacement when the target already exists.
- Verify descriptor download, Chrome Native Messaging handoff, claim, download, app launch, heartbeat, stable-write detection, retry idempotency, conflict, expiry, and stale-generation refusal while preserving independent client releases.

### OnlyOffice And Truthful Gates
- Register OnlyOffice during Hub startup only when enabled, through the existing feature registry pattern.
- Enabling OnlyOffice requires matching, non-empty JWT configuration on Hub and Document Server; missing or inconsistent configuration fails startup rather than accepting unauthenticated callbacks.
- Authenticate, deduplicate, and generation-fence asynchronous save callbacks and lock release; retrying a callback returns the prior outcome without applying the write twice.
- Add one integrated collaboration matrix and make local/CI preflight share the same declared capability table; required but unavailable dependencies are FAIL, intentional optional omissions are SKIP, and executed assertions alone are PASS.

### Claude's Discretion
- Internal helper names, file layout within the owning repository, and the smallest compatible wire representation are at the agent's discretion provided the shared contracts and existing repository conventions are preserved.
- Plans may reorder independent fixes within this phase to restore a red gate sooner, but each commit and plan must remain independently verifiable.

### Deferred Ideas (OUT OF SCOPE)
- Authentik OIDC qualification belongs to Phase 3.
- CE per-library storage selection and MinIO lifecycle belong to Phase 4.
- Tag and audit semantic expansion belongs to Phase 5.
- Seafile AI and external-LLM controls belong to Phase 6.
- OpenList/rclone external-data federation remains a separate post-MVP project.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SEC-01 | Users never receive names, paths, snippets, totals, or cached results for entries hidden by the current CloudFile directory ACL, regardless of search backend. | 统一候选裁决管线、ACL revision、SeaSearch/Meili 精确分页与负例矩阵。 [VERIFIED: `.planning/REQUIREMENTS.md`; `../cloudfile-hub/seahub/api2/views.py`; `../cloudfile-hub/cloudfile_ext/search/backends/meilisearch.py`] |
| SEC-02 | Sync and direct fileserver access fail closed when an enabled ACL authority is unavailable, malformed, or stale, while disabled ACL mode preserves native CE behavior. | 三态 authority RPC、revision 标记缓存、最终下载/同步边界复查。 [VERIFIED: `.planning/REQUIREMENTS.md`; `../cloudfile-server/fileserver/cf_ext.go`; `../cloudfile-server/fileserver/sync_api.go`; `../cloudfile-server/fileserver/fileop.go`] |
| FILEOP-01 | Batch delete and every supported write path emit one valid PREPARE followed by COMMITTED or ABORTED facts with stable operation identity. | 给共享 C/Go 契约加入 operation_id 和一次性终结器，并修正现有 batch-delete E2E 路径。 [VERIFIED: `.planning/REQUIREMENTS.md`; `../cloudfile-server/common/cf-fileop.h`; `../cloudfile-server/fileserver/cf_fileop.go`; `tests/e2e/fileop_matrix.py`] |
| LOCK-01 | Every save, callback, write-back, and lock release that can race is generation-fenced and rejects stale generations. | generation 下沉至 Server PREPARE，锁释放强制 generation，本地编辑与 Office 共用原子栅栏。 [VERIFIED: `.planning/REQUIREMENTS.md`; `../cloudfile-server/common/cf-lock.c`; `../cloudfile-hub/cloudfile_ext/file_actions/views.py`] |
| GATE-01 | Local and CI preflight cover the same declared capabilities and report required skips as SKIP or failure rather than PASS. | 单一机器可读 capability 清单和 PASS/SKIP/FAIL/NOT RUN 结果模型。 [VERIFIED: `.planning/REQUIREMENTS.md`; `tools/preflight-checks.py`; `tools/verify-local.sh`; `.github/workflows/checks.yml`] |
| LOCAL-01 | The Hub, browser action, Chrome extension, and local agent share a versioned descriptor/session schema that supplies the filename and all fields required before ticket claim. | 以 `cloudfile-local/v2` 为唯一协议，补齐 claim 前 file.name/mode，并用共享 schema/golden fixtures 锁定四端。 [VERIFIED: `.planning/REQUIREMENTS.md`; `../cloudfile-hub/cloudfile_ext/file_actions/service.py`; `../cloudfile-hub/frontend/src/cloudfile/file-actions/index.js`; `../cloudfile-local-agent/internal/session/session.go`] |
| LOCAL-02 | Local edit writes back to the existing file with heartbeat, conflict, expiry, retry-idempotency, and stale-generation behavior verified end to end. | 改用 update RPC、持久化幂等结果、同一 idempotency key 重试及 heartbeat 续期。 [VERIFIED: `.planning/REQUIREMENTS.md`; `../cloudfile-hub/cloudfile_ext/file_actions/views.py`; `../cloudfile-local-agent/internal/runner/runner.go`] |
| OFFICE-01 | OnlyOffice is registered only when enabled and refuses startup/callbacks unless both sides have matching non-empty JWT configuration. | startup registry 接线、同源 secret 配置、启动时失败及签名回调负例。 [VERIFIED: `.planning/REQUIREMENTS.md`; `../cloudfile-hub/cloudfile_ext/apps.py`; `../cloudfile-hub/cloudfile_ext/office/__init__.py`; `deploy/compose/docker-compose.yml`] |
| OFFICE-02 | OnlyOffice save, retry, conflict, lock, and generation-aware release behavior passes an integrated container matrix. | DB 原子去重、generation-fenced update/release、状态 2/4/6 与并发重试矩阵。 [VERIFIED: `.planning/REQUIREMENTS.md`; `../cloudfile-hub/cloudfile_ext/office/callbacks.py`; `../cloudfile-hub/seahub/onlyoffice/views.py`] |
</phase_requirements>

## Summary

本阶段不是为九项需求分别打补丁，而是补齐三条共享契约：读取侧的“当前 authority + revision + 最终裁决”、写入侧的“operation_id + 唯一终态 + generation”、协作侧的“版本化 session + 持久化幂等结果”。当前根因集中在边界信息丢失：搜索在后分页阶段才做原生 invisible-path 过滤，fileserver 用空字符串同时表示“无限制”和“authority 失败”，写操作对象没有稳定身份，Hub 的锁检查与原生写入之间存在 TOCTOU。 [VERIFIED: `../cloudfile-hub/seahub/api2/views.py`; `../cloudfile-server/fileserver/cf_ext.go`; `../cloudfile-server/common/cf-fileop.h`; `../cloudfile-hub/cloudfile_ext/file_actions/views.py`]

本地编辑和 OnlyOffice 已有可复用骨架，但分别缺少 claim 前文件名、update 语义、耐久幂等，以及 startup 注册、强制 JWT、回调原子去重。控制面当前也已真实报红：`python3 tools/preflight-checks.py . ..` 因本地能力表缺少 `external_sources` 而退出 1；应先用单一 capability manifest 修复这条门禁，再逐层扩展契约和矩阵。 [VERIFIED: 2026-08-11 local command `python3 tools/preflight-checks.py . ..`; `../cloudfile-hub/cloudfile_ext/file_actions/service.py`; `../cloudfile-hub/cloudfile_ext/office/callbacks.py`]

**Primary recommendation:** 按 GATE → ACL 读取权威 → FILEOP/LOCK 写入权威 → LOCAL → OFFICE 的顺序实施；每一步先更新共享契约/fixture，再改 Hub/Server/Agent 实现，最后用本地快测与能力 E2E 独立闭环。 [VERIFIED: `.planning/phases/01-security-and-collaboration-contract-closure/01-CONTEXT.md`; `AGENTS.md`; `.planning/codebase/TESTING.md`]

## Project Constraints (from CLAUDE.md / AGENTS.md)

- `CLAUDE.md` 将项目规则完全委托给 `AGENTS.md`；`release.yaml` 是构建来源与版本引用的唯一权威，禁止在其他脚本硬编码组件引用。 [VERIFIED: `CLAUDE.md`; `AGENTS.md`; `release.yaml`]
- 所有 `CF_ENABLE_*` 为 false 时必须保持原生 CE 行为；Compose profile 专属变量不能用 `${VAR:?}` 使未启用 profile 的解析失败。 [VERIFIED: `AGENTS.md`]
- 生成配置必须在每次启动时重写，并作为可执行 Python 测试；跨层语义必须按“共享 spec/cases → 两端实现 → 一致性测试”推进。 [VERIFIED: `AGENTS.md`; `scripts/scripts_14.0/bootstrap.py`; `tools/test-bootstrap-settings.py`]
- 最终安全裁决属于 Server；Server 新代码优先 `cf-*`/`cf_*` 扩展点。Hub 新代码放 `cloudfile_ext/` 与 `frontend/src/cloudfile/`，只有现有 seam 不足时才做最小上游修改，并同步分支/patch inventory。 [VERIFIED: `AGENTS.md`; `.planning/codebase/STRUCTURE.md`; `docs/upstream-patches/cloudfile-hub.txt`]
- 代码、注释、提交信息用英文；本仓库 Markdown 文档用中文；Shell 修改需 `set -e` 与 `bash -n`。 [VERIFIED: `AGENTS.md`]
- 禁止提交 `.env`、数据卷或 secret；Server 完整 C 构建只在 Linux CI/构建容器中保证，本机 macOS 仅运行纯 C/Go 近似测试。 [VERIFIED: `AGENTS.md`; 2026-08-11 `uname`/tool availability audit]
- UI 必须扩展现有 Seahub/CloudFile 组件与 Reactstrap，不引入新设计系统；新增文案走 gettext，冲突/过期/陈旧 generation/不支持协议使用持久 `role="alert"`，状态词固定为 PASS/SKIP/FAIL/NOT RUN。 [VERIFIED: `.planning/phases/01-security-and-collaboration-contract-closure/01-UI-SPEC.md`; `../cloudfile-hub/frontend/package.json`]

## Standard Stack

本阶段不增加第三方依赖；应优先扩展仓库已经锁定并构建的组件，以避免把安全契约变成包升级项目。 [VERIFIED: `release.yaml`; `image/cloudfile_14.0/Dockerfile`; `../cloudfile-hub/requirements.txt`; `../cloudfile-local-agent/go.mod`]

### Core

| Library / Runtime | Version | Purpose | Why Standard |
|---|---:|---|---|
| Django / DRF | 5.2.x / 3.16.x | Hub API、数据库事务、startup registry | 当前 Hub 已锁定并承载所有 CloudFile 扩展。 [VERIFIED: `../cloudfile-hub/requirements.txt`; `../cloudfile-hub/cloudfile_ext/apps.py`] |
| PyJWT | 2.13.x | OnlyOffice HS256 JWT 验签 | 当前 Hub 依赖；避免自写签名解析。 [VERIFIED: `../cloudfile-hub/requirements.txt`; `../cloudfile-hub/cloudfile_ext/office/callbacks.py`] |
| React / Reactstrap | 18.3.1 / 9.2.3 | 本地编辑与 Office 状态 UI | 当前 Seahub 前端既有栈，UI-SPEC 明确要求复用。 [VERIFIED: `../cloudfile-hub/frontend/package.json`; `01-UI-SPEC.md`] |
| C + GLib/Jansson/Searpc | 仓库构建锁定 | 最终 ACL、锁、fileop 生命周期与 RPC | 当前 Server 扩展点实现所用原生栈。 [VERIFIED: `../cloudfile-server/common/cf-ext.c`; `../cloudfile-server/common/cf-fileop.c`; `../cloudfile-server/common/cf-lock.c`] |
| Go standard library + fsnotify | Go module；fsnotify 1.9.0 | fileserver 与本地 agent 的会话、稳定写检测和重试 | 两个 Go 边界当前已有栈。 [VERIFIED: `../cloudfile-server/fileserver/go.mod`; `../cloudfile-local-agent/go.mod`; `../cloudfile-local-agent/internal/runner/runner.go`] |
| MariaDB / Redis | 11.4 / 7 镜像线 | 耐久状态 / 非权威加速缓存 | Compose 已提供；幂等与 revision 权威必须落 SQL，Redis 只能加速。 [VERIFIED: `deploy/compose/docker-compose.yml`; `../cloudfile-hub/cloudfile_ext/file_actions/schema.sql`] |
| OnlyOffice Document Server | 8.2 image line | 浏览器协同编辑 | 当前可选 profile 已定义。 [VERIFIED: `deploy/compose/docker-compose.yml`; `release.yaml`] |
| SeaSearch / Meilisearch | `1.0-latest` / `v1.10` 当前配置线 | 两种搜索后端 | SEC-01 明确要求同一授权语义覆盖两端。 [VERIFIED: `deploy/compose/docker-compose.yml`; `.github/workflows/search-e2e.yml`; `../cloudfile-hub/cloudfile_ext/search/backends/meilisearch.py`] |

### Supporting

| Component | Purpose | When to Use |
|---|---|---|
| `docs/acl-cases.json` / `docs/fileop-cases.json` | 跨语言语义 fixture | 先扩展案例，再驱动 Hub、C、Go 和 E2E。 [VERIFIED: `AGENTS.md`; `docs/acl-cases.json`; `docs/fileop-cases.json`] |
| Django 数据库事务与唯一约束 | callback/writeback 原子 claim 和 prior outcome | 所有可重放异步写，不用进程缓存作幂等权威。 [VERIFIED: `../cloudfile-hub/cloudfile_ext/file_actions/schema.sql`; `../cloudfile-hub/cloudfile_ext/office/callbacks.py`] |
| 现有 feature registry | 条件注册 OnlyOffice | `CF_ENABLE_ONLYOFFICE` 启用时在 registry seal 前注册。 [VERIFIED: `../cloudfile-hub/cloudfile_ext/apps.py`; `../cloudfile-hub/cloudfile_ext/office/__init__.py`] |

**Installation:** 无新增包；执行前只安装各仓库既有锁定依赖。 [VERIFIED: repository manifests above]

## Architecture Patterns

### Recommended Ownership

```text
cloudfile-docker/
├── config/capabilities.json              # 单一 gate 能力声明
├── docs/{acl,fileop,local-session}-*.json # 跨层协议与案例
├── tests/e2e/collaboration_matrix.py      # LOCAL + OFFICE 集成矩阵
└── tools/                                 # 同一 manifest 的本地/CI 消费者
cloudfile-hub/
├── cloudfile_ext/acl/                     # Hub 有效 ACL / revision 适配
├── cloudfile_ext/search/                  # 两后端共用候选裁决
├── cloudfile_ext/file_actions/            # v2 session、writeback 幂等
├── cloudfile_ext/office/                  # 条件注册、JWT、回调协调器
└── frontend/src/cloudfile/file-actions/   # 既有 UI 扩展
cloudfile-server/
├── common/cf-{acl,fileop,lock}.*          # 最终权威、op_id、generation
└── fileserver/cf_{ext,fileop}.go          # 三态 authority 与最终边界
cloudfile-local-agent/internal/{session,runner}/
└── version check、heartbeat deadline、同 key 重试
```

该所有权遵循现有跨仓库结构，不把最终安全规则放回 Docker 或 Chrome extension。 [VERIFIED: `.planning/codebase/STRUCTURE.md`; `AGENTS.md`]

### Pattern 1: Explicit Authority State + Revision

**What:** authority 调用必须返回 `inactive | active` 与单调 revision；`inactive` 才允许 CE pass-through，`active` 的传输失败、解析失败或过期 revision 一律拒绝。Hub 与 fileserver 的缓存键包含 revision，并在响应/传输最终边界复查当前 revision。 [VERIFIED: locked decision in `01-CONTEXT.md`; existing three-way fileop behavior in `../cloudfile-server/fileserver/cf_fileop.go`]

**Implementation seam:** 在 Server CloudFile RPC 增加结构化 authority-state/revision 方法；在 ACL 管理写事务中递增 `cf_acl_repo_revision`（建议新表，避免对既有表做不兼容 ALTER）；把 `cfFindRestrictedPath` 从含糊字符串改为显式状态结果。 [VERIFIED: `../cloudfile-server/fileserver/cf_ext.go`; `../cloudfile-hub/cloudfile_ext/acl/admin.py`; `../cloudfile-hub/cloudfile_ext/acl/schema.sql`]

### Pattern 2: Candidate Authorization Before Observable Search State

**What:** SeaSearch 与 Meili 都只提供原始候选；一个共同授权器在 snippet、序列化、总数、分页和缓存之前逐项调用有效 ACL evaluator。为得到精确授权总数和满页结果，适配器必须分批 over-fetch 直到填满授权页并计算准确终点，或使用经验证等价的后端过滤；当前实现没有可证明等价的 CloudFile ACL 索引过滤，因此优先 correctness-first 分批扫描。 [VERIFIED: `../cloudfile-hub/seahub/api2/views.py`; `../cloudfile-hub/seahub/search/utils.py`; `../cloudfile-hub/cloudfile_ext/search/backends/meilisearch.py`]

**Implementation seam:** 复用 `cloudfile_ext/acl/service.py::apply_dir_acl`，增加批量候选包装器；由于现有 `_cf_search_files` hook 只覆盖 `HAS_FILE_SEARCH` 而不统一覆盖 `HAS_FILE_SEASEARCH`，在 `seahub/api2/views.py::Search.get` 增加一个最小 CloudFile 候选授权 hook，并在两个分支的同一可观察边界调用。该上游 seam 必须登记 Hub patch inventory。 [VERIFIED: CodeGraph exploration of `Search.get`; `../cloudfile-hub/cloudfile_ext/acl/service.py`; `../cloudfile-hub/cloudfile_ext/hooks.py`; `docs/upstream-patches/cloudfile-hub.txt`]

### Pattern 3: Operation Context With Single Finalizer

**What:** 一个逻辑请求/批次只创建一次 operation context，携带 `operation_id`、repo/path、actor、generation 与 expected version；PREPARE 成功后由 scope finalizer 保证恰好一个 COMMITTED 或 ABORTED。observer/report 失败不改变已完成原生写，也不能再次终结。 [VERIFIED: locked decision in `01-CONTEXT.md`; current missing identity in `../cloudfile-server/common/cf-fileop.h`; early returns in `../cloudfile-server/fileserver/fileop.go`]

**Implementation seam:** 先扩展 `CfFileOp`、Go `cfFileOp`、JSON converter 和共享 fixture；C 宏不得再为 PREPARE/terminal 各造一个 compound literal，Go 写路径用 deferred terminal guard。客户端有 idempotency key 时映射稳定 operation_id；没有时在请求入口只生成一次。 [VERIFIED: `../cloudfile-server/common/cf-fileop.h`; `../cloudfile-server/common/cf-fileop.c`; `../cloudfile-server/fileserver/cf_fileop.go`; `../cloudfile-server/server/repo-op.c`]

### Pattern 4: Generation-Fenced Native Mutation

**What:** Hub 预检仅改善 UX；当目标受活跃 lease 保护时，native PREPARE 必须原子比较当前 generation/owner/source version。锁释放同样强制精确 generation；缺失或陈旧 generation 返回冲突，不能释放新 lease。 [VERIFIED: `AGENTS.md`; locked decision in `01-CONTEXT.md`; current owner-only allowance in `../cloudfile-server/common/cf-lock.c`]

**Implementation seam:** 在 fileop 契约增加 `lock_generation`，通过 CloudFile-specific update RPC 或兼容的可选 RPC 参数下沉到 `server/repo-op.c`；`cf_lock_release_json` 与 Hub `release_checkout()` 删除空 generation 默认。Acquire 时利用现有 `source_file_id`/`source_commit_id` 列保存基线。 [VERIFIED: `../cloudfile-server/common/cf-lock.c`; `../cloudfile-server/common/cf-lock.h`; `../cloudfile-hub/cloudfile_ext/file_actions/service.py`]

### Pattern 5: Durable Idempotency State Machine

**What:** local writeback 和 OnlyOffice callback 都使用 SQL 权威状态 `processing → committed | conflict | failed`，唯一键原子 claim；重试返回既有 outcome，缓存只作加速。原生写成功后先持久化结果，再按精确 generation 释放。 [VERIFIED: current cache-only dedupe in `../cloudfile-hub/cloudfile_ext/office/callbacks.py`; current session schema in `../cloudfile-hub/cloudfile_ext/file_actions/schema.sql`]

**Implementation seam:** 用新表而非给既有 `cf_edit_session` 强制 ALTER，可利用每次 startup 重跑 `CREATE TABLE IF NOT EXISTS` 的既有 schema bootstrap；记录 idempotency/callback key、operation_id、generation、expected file/commit、terminal outcome 和 result commit/file id。 [VERIFIED: `../cloudfile-hub/cloudfile_ext/file_actions/schema.py`; `../cloudfile-hub/cloudfile_ext/file_actions/schema.sql`]

### Anti-Patterns to Avoid

- **在搜索返回后过滤:** 会泄漏原始 total/has_more，并造成短页；当前两个分支正有此问题。 [VERIFIED: `../cloudfile-hub/seahub/api2/views.py`]
- **用空字符串编码多个 ACL 状态:** `cfFindRestrictedPath` 的 RPC 错误与“无受限路径”都返回空串，调用方因而 fail-open。 [VERIFIED: `../cloudfile-server/fileserver/cf_ext.go`; `../cloudfile-server/fileserver/sync_api.go`]
- **先在 Hub 检查 generation 再调用无栅栏写 API:** 检查和 commit 之间可换代。 [VERIFIED: `../cloudfile-hub/cloudfile_ext/file_actions/views.py`]
- **以缓存布尔值作 callback 去重权威:** 多进程并发或重启可重复写。 [VERIFIED: `../cloudfile-hub/cloudfile_ext/office/callbacks.py`]
- **writeback 使用 create/add API:** `post_file` 会偏离“更新现有文件”的合同并可能生成无关替代文件。 [VERIFIED: `../cloudfile-hub/cloudfile_ext/file_actions/views.py`; Seahub Seafile API call semantics in local source]
- **让 gate 从执行计划推断 PASS:** 未运行、依赖缺失和断言成功必须分开建模。 [VERIFIED: `tools/run-checks.sh`; `tools/verify-local.sh`; `01-UI-SPEC.md`]

## Exact Implementation Seams And Root Causes

### SEC-01 — Search Disclosure

1. `Search.get` 当前读取的是原生 `SharedRepo` invisible paths，不是 CloudFile `cf_dir_acl`；并且在 backend 已经分页、计算 total、生成命中对象后才过滤。返回值仍使用 backend 原始 total。 [VERIFIED: `../cloudfile-hub/seahub/api2/views.py`; `../cloudfile-hub/seahub/models.py`]
2. Meili provider 仅按 repo/path/metadata 构造过滤并返回 `estimatedTotalHits`，没有 CloudFile ACL；SeaSearch 分支同样只接受事后原生 invisible-path 过滤。 [VERIFIED: `../cloudfile-hub/cloudfile_ext/search/backends/meilisearch.py`; `../cloudfile-hub/seahub/api2/views.py`]
3. 复用 `apply_dir_acl`，增加 revision-aware 批量候选裁决；两后端通过同一 hook，未授权候选在任何 snippet/serialization/cache 前丢弃，授权页和 total 从授权流重新计算。 [VERIFIED: `../cloudfile-hub/cloudfile_ext/acl/service.py`; locked decision]
4. 当前 ACL service 的规则/subject cache TTL 为 30 秒，admin invalidation 只清当前进程 repo cache；必须增加跨进程 revision，或在最终边界完全绕过缓存重评。为性能与即时撤销兼顾，推荐 SQL 单调 revision。 [VERIFIED: `../cloudfile-hub/cloudfile_ext/acl/service.py`; `../cloudfile-hub/cloudfile_ext/acl/admin.py`]

### SEC-02 — Sync / Direct Fileserver Fail-Closed

1. `cfFindRestrictedPath` 在 RPC error、返回类型异常时返回 `""`，`sync_api.go::checkPermission` 把 `""` 解释为无限制并缓存权限 300 秒。 [VERIFIED: `../cloudfile-server/fileserver/cf_ext.go`; `../cloudfile-server/fileserver/sync_api.go`]
2. 改成显式 `unsupported/inactive/active-valid/active-error` 结果；stock CE 不支持 RPC 与 inactive 才 pass-through，active-error/malformed/stale 必须 deny，缓存 verdict 必须带 revision 且最终复查。 [VERIFIED: analogous fileop extension-state handling in `../cloudfile-server/fileserver/cf_fileop.go`; locked decision]
3. direct web access 的 `parseWebaccessInfo` 目前只取 repo/object/op/user，没有 path 或 ACL revision；已签发链接在撤权后无法对当前 path 做最终复查。扩展 access token/RPC 返回 normalized path 与 issue revision，并在 content/block/zip 发送前复查当前 authority。 [VERIFIED: `../cloudfile-server/fileserver/fileop.go`; CodeGraph exploration of fileserver access paths]

### FILEOP-01 — Missing Stable Fact Identity

1. `CfFileOp`、Go `cfFileOp` 及 JSON conversion 均没有 operation_id；C PREPARE/terminal 宏各自创建新结构体，无法证明一对一。 [VERIFIED: `../cloudfile-server/common/cf-fileop.h`; `../cloudfile-server/common/cf-fileop.c`; `../cloudfile-server/fileserver/cf_fileop.go`]
2. `tests/e2e/fileop_matrix.py` journal 只有 7 个字段且主要计数 COMMITTED，没有按 operation_id 断言 `PREPARE → exactly one terminal`。 [VERIFIED: `tests/e2e/fileop_matrix.py`]
3. 当前 batch-delete 红点还有独立测试错误：实际 URL 是 `/api/v2.1/repos/batch-delete-item/` 且 JSON body 含 `repo_id`/`file_names`，matrix 调用了带 repo UUID 的不存在路径，产生 404。先修 matrix，再判断实现事实。 [VERIFIED: `../cloudfile-hub/seahub/urls.py`; `../cloudfile-hub/seahub/api2/endpoints/repos_batch.py`; `tests/e2e/fileop_matrix.py`]

### LOCK-01 — Precheck / Commit TOCTOU

1. C `check_path` 对当前 owner 放行但不比较 generation；同一 owner 的旧会话可越过新 lease。 [VERIFIED: `../cloudfile-server/common/cf-lock.c`]
2. Hub `AgentContentView.put` 检查 generation/base_file_id 后调用 native 写 API，原子写本身没有 generation；release JSON 允许缺失 generation 时按 owner 释放当前锁。 [VERIFIED: `../cloudfile-hub/cloudfile_ext/file_actions/views.py`; `../cloudfile-server/common/cf-lock.c`]
3. 把 generation/source version 纳入原生 PREPARE，并只允许精确代际 release；正常“无活跃 lease”的写保持 CE 行为，有活跃 lease 的竞态写必须携带 generation。 [VERIFIED: locked decision; `AGENTS.md`]

### LOCAL-01 — Split Schema Before Claim

1. Hub pre-claim 只返回 protocol/ticket/expiry；React 立即访问 `session.mode` 和 `session.file.name`，因此下载描述符缺文件名且 edit mode 显示不实。 [VERIFIED: `../cloudfile-hub/cloudfile_ext/file_actions/service.py`; `../cloudfile-hub/frontend/src/cloudfile/file-actions/index.js`]
2. Agent 已定义 `cloudfile-local/v2` descriptor 与 claimed-session 结构；Hub 另有未使用 v1 helper，形成竞争 schema。以 agent v2 为唯一 canonical contract，pre-claim 增加 `mode` 与 `file:{name}`，descriptor 仍只携短期 ticket/server/protocol/expiry。 [VERIFIED: `../cloudfile-local-agent/internal/session/session.go`; `../cloudfile-hub/cloudfile_ext/file_actions/service.py`]
3. claim body 增加 protocol 并严格匹配；Agent 也继续在 descriptor 层拒绝不支持版本，以允许 Hub、extension、agent 独立发布且 fail closed。 [VERIFIED: current Agent protocol check in `../cloudfile-local-agent/internal/session/session.go`; locked decision]

### LOCAL-02 — Create Semantics And Non-Durable Retry

1. Hub writeback 调用 `seafile_api.post_file` 而非更新现有文件的 API；session 表没有 idempotency key、terminal outcome 或 result identifiers。 [VERIFIED: `../cloudfile-hub/cloudfile_ext/file_actions/views.py`; `../cloudfile-hub/cloudfile_ext/file_actions/schema.sql`]
2. Agent 监视稳定 3 秒、heartbeat 每 5 分钟、上传一次即退出；上传失败没有带同一 key 的 bounded retry，heartbeat 也没有更新本地 expiry deadline。 [VERIFIED: `../cloudfile-local-agent/internal/runner/runner.go`]
3. 使用 generation/expected file/commit 的 update RPC；每次保存生成一次 idempotency key，重试不换 key；Hub durable outcome 使“commit 已完成但响应丢失”的重试返回原结果而不是再写。heartbeat 返回新 expiry/lease_until 并重置 runner deadline。 [VERIFIED: locked decision; existing lease renewal API in `../cloudfile-hub/cloudfile_ext/file_actions/views.py`]

### OFFICE-01 — Capability Exists But Is Not Registered Or Enforced

1. `cloudfile_ext.office.register()` 已存在，但 `cloudfile_ext/apps.py` 没有导入/调用；wrapper 在 JWT secret 为空时直接认证成功。 [VERIFIED: `../cloudfile-hub/cloudfile_ext/office/__init__.py`; `../cloudfile-hub/cloudfile_ext/apps.py`; `../cloudfile-hub/cloudfile_ext/office/callbacks.py`]
2. Compose 只把 `ONLYOFFICE_JWT_SECRET` 传给 Document Server 的 `JWT_SECRET`，未传 Hub/worker；bootstrap 也不生成 Hub OnlyOffice settings。 [VERIFIED: `deploy/compose/docker-compose.yml`; `scripts/scripts_14.0/bootstrap.py`]
3. 启用时由一个 canonical env 值同时生成 Document Server 与 Hub 配置；bootstrap 在 enabled 且 secret/API URL 缺失时失败。Compose render 测试证明同源配置，真实签名 callback smoke 证明运行时配对；不要声称从 Document Server 读取不可见 secret 后做明文比较。 [VERIFIED: current Compose/settings wiring; locked decision]
4. OnlyOffice 官方说明 integrator 与 Docs 使用共享 secret 对请求签名，Document Server 的 callback 可在 body 或配置 header 中携带 JWT。 [CITED: https://api.onlyoffice.com/docs/docs-api/additional-api/signature/; https://api.onlyoffice.com/docs/docs-api/additional-api/signature/request/]

### OFFICE-02 — Cache Dedupe And Unfenced Delegation

1. 当前 wrapper 用 24h Django cache boolean 去重，非耐久且并发不原子；key 仅在上游响应后写入。 [VERIFIED: `../cloudfile-hub/cloudfile_ext/office/callbacks.py`]
2. 上游 OnlyOffice callback 下载内容后执行 update，但 update 响应非 200 时仅记录日志并继续返回成功；wrapper 的 doc info 没有 generation/base file id，并以缺失 generation 释放。 [VERIFIED: `../cloudfile-hub/seahub/onlyoffice/views.py`; `../cloudfile-hub/cloudfile_ext/office/callbacks.py`]
3. 在编辑会话创建时 acquire `kind=onlyoffice` lease，并用 `doc_key` 持久化 generation、base file/commit、operation_id；callback 先验 JWT，再原子 claim dedupe key，执行 generation-fenced update，持久化结果后精确 release。状态 4 无修改关闭也只能释放自己的 generation。 [VERIFIED: existing `onlyoffice` lock kind support in `../cloudfile-hub/cloudfile_ext/file_actions/service.py`; locked decision]
4. 官方 callback 状态 2/4/6 分别覆盖 ready-for-save、closed-without-changes、force-save，存储服务只有接受结果时才返回 `{"error":0}`。 [CITED: https://api.onlyoffice.com/docs/docs-api/usage-api/callback-handler/]

### GATE-01 — Two Capability Lists And False-Pass Vocabulary

1. `verify-local.sh` 的 CAPABILITIES 缺 `external_sources`，而 CI workflow 集合包含它；当前 preflight 因 local 7 vs CI 8 退出 1。 [VERIFIED: `tools/verify-local.sh`; `.github/workflows/external-sources-e2e.yml`; 2026-08-11 local command]
2. `.github/workflows/checks.yml` 只运行 `tools/run-checks.sh`，没有直接保证 preflight parity；`run-checks.sh` 即使有 skipped 项仍输出全部通过，S3 子检查在依赖缺失时可 exit 0。 [VERIFIED: `.github/workflows/checks.yml`; `tools/run-checks.sh`; `tools/verify-local.sh`]
3. 新增单一 JSON capability manifest，字段至少含 id、feature switches、matrix、workflow、local/CI requiredness、dependencies/profiles；本地与 CI 都解析同一清单，静态 preflight 验证 workflow/entry parity。每项输出结构化 PASS/SKIP/FAIL/NOT RUN + reason/evidence；只有实际执行且断言成功才 PASS。 [VERIFIED: locked decision; `01-UI-SPEC.md`]

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---|---|---|---|
| 两搜索后端 ACL | 每 backend 一套过滤规则 | 现有 `acl.service` + 一个共同候选管线 | 避免权限语义、total 和 cache 漂移。 [VERIFIED: `../cloudfile-hub/cloudfile_ext/acl/service.py`] |
| JWT | 自定义 HMAC/claim parser | PyJWT + OnlyOffice 官方 header/body 契约 | 现有依赖已经提供算法和校验边界。 [VERIFIED: `../cloudfile-hub/requirements.txt`; CITED official signature docs] |
| 锁权威 | Hub-only mutex/预检 | Server `cf-lock` + generation in PREPARE | Hub 检查不能封闭 commit 前竞态。 [VERIFIED: `AGENTS.md`; `../cloudfile-server/common/cf-lock.c`] |
| callback/writeback 幂等 | cache flag 或进程内 map | SQL unique claim + durable outcome | 重启、多 worker 与丢响应重试要求持久化。 [VERIFIED: current gaps in callbacks/session schema] |
| gate 列表 | Shell/YAML 各维护一份 | canonical capability manifest | 当前重复声明已经产生真实 parity 红门。 [VERIFIED: preflight command result] |
| writeback 替换策略 | create 后找“最像”的文件 | native update existing file RPC | 合同要求同一 file identity 与 version precondition。 [VERIFIED: locked decision] |

**Key insight:** 本阶段最危险的“自制方案”不是新算法，而是复制边界状态；authority、operation、generation、idempotency 和 capability 都必须各有一个权威表示，其他层只做适配。 [VERIFIED: consolidated code inspection]

## Runtime State Inventory

本阶段包含协议与数据库 schema 迁移，因此必须同时计划 source edit 与已运行状态迁移。 [VERIFIED: proposed durable revision/idempotency/office session tables; current startup schema mechanism]

| Category | Items Found | Action Required |
|---|---|---|
| Stored data | 既有 `cf_edit_session`、`cf_lock_lease`、`cf_dir_acl`、OnlyOffice doc key 与非耐久 cache 已在运行数据库中；当前表缺 revision/idempotency/office generation。 [VERIFIED: `../cloudfile-hub/cloudfile_ext/file_actions/schema.sql`; `../cloudfile-server/scripts/sql/mysql/cloudfile.sql`; `../cloudfile-hub/seahub/onlyoffice/models.py`] | 新建 revision、writeback outcome、office session/callback outcome 表；startup `CREATE TABLE IF NOT EXISTS` 迁移。旧未完成 session 应按协议规则过期/拒绝，不能默默写入。 [VERIFIED: current schema bootstrap in `file_actions/schema.py`] |
| Live service config | 运行时 `seahub_settings.py` 每次启动生成；OnlyOffice secret 当前仅注入 Document Server，Document Server 还使用持久 volume。 [VERIFIED: `scripts/scripts_14.0/bootstrap.py`; `deploy/compose/docker-compose.yml`] | Hub/worker/Docs 从同一 env 注入；重启使生成配置生效，集成测试必须覆盖 restart 后 JWT 与去重状态。 [VERIFIED: project startup convention] |
| OS-registered state | Chrome Native Messaging host 注册与 extension 安装独立于服务端；现有 agent 协议常量为 `cloudfile-local/v2`。 [VERIFIED: `../cloudfile-local-agent/internal/session/session.go`; `../cloudfile-chrome-extension/manifest.json`] | 保持 v2 兼容的附加字段可免重注册；任何 breaking version 必须保留明确 unsupported failure 并协调独立客户端发布。 [VERIFIED: locked independent release constraint] |
| Secrets/env vars | `ONLYOFFICE_JWT_SECRET` 已存在但仅接到 Docs；没有发现需要重命名的 secret。 [VERIFIED: `deploy/compose/docker-compose.yml`; `deploy/compose/.env.example`] | 不改 secret 名；扩展传递范围并确保日志/错误不泄漏值。无数据值迁移，但部署必须重启。 [VERIFIED: current env name] |
| Build artifacts / installed packages | Hub/Server 在 CloudFile image 中构建，agent 与 Chrome extension 独立发布；旧二进制不会从 source edit 自动更新。 [VERIFIED: `release.yaml`; `.planning/codebase/STRUCTURE.md`] | 重建 image；分别构建/测试 agent 与 extension。旧 agent 对未知协议 fail closed。 [VERIFIED: Agent protocol validation] |

## Common Pitfalls

### Pitfall 1: Exact Total With Post-Filter Pagination

**What goes wrong:** 第 1 页短缺、`has_more`/total 泄漏隐藏条目，后页重复或遗漏。 **Why:** backend 已分页才做 ACL。 **Avoid:** 授权流自身分页并计算授权 total；测试第一页、跨页和全隐藏页。 **Warning sign:** result 长度变化但 total 不变。 [VERIFIED: `../cloudfile-hub/seahub/api2/views.py`]

### Pitfall 2: Revision Is Added But Not Checked At Final Boundary

**What goes wrong:** 链接、sync permission 或搜索缓存仍在 TTL 内放行。 **Why:** revision 只参与写入/初次 lookup。 **Avoid:** 内容发送、sync op 和 search response 前读当前 revision；不确定即 deny。 **Warning sign:** revoke 后旧 link 仍能下载。 [VERIFIED: current 300s fileserver cache and 30s Hub cache]

### Pitfall 3: Exactly-One Terminal Lost On Early Return

**What goes wrong:** PREPARE 无终态，或 observer retry 生成第二终态。 **Why:** 每个 error branch 手工 report。 **Avoid:** scope finalizer + terminal CAS/guard；fixture 按 operation_id 检查。 **Warning sign:** journal 只能统计状态数量而不能配对。 [VERIFIED: current C macros/Go branches and `tests/e2e/fileop_matrix.py`]

### Pitfall 4: Generation Checked Only On Release

**What goes wrong:** 陈旧 save 已覆盖新 lease 的内容，尽管最后 release 被拒。 **Why:** generation 没进入 native mutation PREPARE。 **Avoid:** update 与 release 都比较相同 generation/source version。 **Warning sign:** 同一 owner 的旧 session 可写。 [VERIFIED: `../cloudfile-server/common/cf-lock.c`; Hub writeback flow]

### Pitfall 5: Idempotency Key Changes On Retry

**What goes wrong:** 响应丢失后重试再次写入。 **Why:** key 在每个 HTTP attempt 生成。 **Avoid:** Agent/session 在一次逻辑 save 开始时生成并复用；Hub 返回 prior outcome。 **Warning sign:** retry 测试只能断言最终内容，未断言 operation count。 [VERIFIED: current Agent single-attempt behavior; locked requirement]

### Pitfall 6: OnlyOffice “Authenticated” When Secret Empty

**What goes wrong:** feature 看似启用但 callback 无认证。 **Why:** 空 secret 被当作兼容模式。 **Avoid:** enabled startup 必须检查非空，callback 永不把空 secret 当成功。 **Warning sign:** 无 Authorization/header token 的 callback 返回 error 0。 [VERIFIED: `../cloudfile-hub/cloudfile_ext/office/callbacks.py`]

### Pitfall 7: Required Dependency Reported As Skip/Pass

**What goes wrong:** CI 绿色但能力未执行。 **Why:** shell exit 0 和人类文案混同语义。 **Avoid:** manifest 声明 requiredness；runner 记录证据状态，聚合器按结构化状态决定 exit code。 **Warning sign:** 输出“全部通过”同时列出 skipped。 [VERIFIED: `tools/run-checks.sh`; locked decision]

## Code Examples

以下是规划需要锁定的最小 wire shape；字段名可按实现惯例微调，但语义不可拆散。 [ASSUMED]

### Authority Result

```json
{
  "state": "active",
  "revision": 42,
  "restricted_path": "/private"
}
```

active 状态的 RPC/parse/revision 失败必须转换为 denial；`inactive` 才调用原生 CE 权限路径。 [VERIFIED: locked decision]

### File Operation Fact

```json
{
  "operation_id": "01J...",
  "phase": "PREPARE",
  "repo_id": "...",
  "path": "/report.docx",
  "lock_generation": "7",
  "expected_file_id": "...",
  "expected_commit_id": "..."
}
```

同一 operation_id 后续只能出现一个 `COMMITTED` 或 `ABORTED`。 [VERIFIED: locked decision]

### Local Pre-Claim Descriptor Response

```json
{
  "protocol": "cloudfile-local/v2",
  "mode": "edit",
  "ticket": "one-time-secret",
  "expires_at": "2026-08-11T12:00:00Z",
  "expires_in": 60,
  "file": {"name": "report.docx"}
}
```

浏览器下载的 descriptor 只保留 protocol/server/ticket/expires_at；content URL 与 writeback capability 只在 one-time claim 后返回。 [VERIFIED: current Agent schema and locked decision]

### Gate Result

```json
{
  "capability": "office",
  "status": "FAIL",
  "reason": "required dependency unavailable",
  "evidence_id": null
}
```

状态词必须精确为 PASS/SKIP/FAIL/NOT RUN，运行时 Enabled 是独立维度。 [VERIFIED: `01-UI-SPEC.md`]

## State Of The Art In This Codebase

| Old / Current Broken Approach | Required Current Approach | Change Driver | Impact |
|---|---|---|---|
| backend search 后过滤 native invisible paths | backend-independent effective ACL before observability | SEC-01 / locked decision | 消除 names/snippets/totals/cache 泄漏。 [VERIFIED: requirements/context] |
| 空字符串表示 unlimited 或 authority error | explicit state + revision | SEC-02 | active authority fail closed、inactive CE pass-through。 [VERIFIED: current code/context] |
| 无 operation identity 的独立 facts | stable operation_id + one finalizer | FILEOP-01 | 可验证 PREPARE 与唯一终态。 [VERIFIED: requirements/context] |
| owner-only lock check | generation + expected version in native PREPARE | LOCK-01 | 封闭 TOCTOU 与同 owner 旧会话。 [VERIFIED: current code/context] |
| cache-only callback dedupe | durable atomic outcome | LOCAL-02/OFFICE-02 | restart/并发/丢响应可安全重试。 [VERIFIED: requirements/context] |
| shell/YAML 双能力表 | canonical manifest + structured evidence | GATE-01 | 本地/CI 同义且不能假绿。 [VERIFIED: preflight failure/context] |

**Deprecated/outdated:** Hub 中未使用的 local v1 helper 应删除或明确隔离；空 JWT 兼容模式必须移除；不带 generation 的普通 release API 对协作 lease 必须拒绝。 [VERIFIED: `../cloudfile-hub/cloudfile_ext/file_actions/service.py`; `../cloudfile-hub/cloudfile_ext/office/callbacks.py`; `../cloudfile-server/common/cf-lock.c`]

## Validation Architecture

### Test Framework And Environment

| Repository / Layer | Framework | Config / Existing Tests | Fast Command | Local Availability |
|---|---|---|---|---|
| Docker control plane | Python scripts + shell | `tools/preflight-checks.py`, `tools/test-bootstrap-settings.py`, `tests/tools/` | `python3 tools/test-bootstrap-settings.py && python3 tools/preflight-checks.py . .. && for f in tools/*.sh; do bash -n "$f"; done` | 可本地运行；当前 preflight 因 capability drift 预期失败。 [VERIFIED: 2026-08-11 commands] |
| Hub backend | pytest | `cloudfile_ext/**/tests/` | `python3 -m pytest cloudfile_ext/acl cloudfile_ext/search cloudfile_ext/file_actions cloudfile_ext/office -q` | 本机 Python 3.9.6，但 pytest/PyJWT 未安装；需 Hub venv 或容器。 [VERIFIED: 2026-08-11 environment audit; Hub requirements] |
| Hub frontend | Jest + jsdom | `frontend/scripts/test.js` | `npm test -- --runInBand` from `../cloudfile-hub/frontend` | Node/npm 可用；需先安装锁定 node_modules。 [VERIFIED: `../cloudfile-hub/frontend/package.json`; 2026-08-11 environment audit] |
| Server C contract | shell-compiled C harness | `tests/cf-acl/run.sh`, `tests/cf-fileop/run.sh` | `./tests/cf-acl/run.sh && ./tests/cf-fileop/run.sh` | 本机已通过 62 ACL、159 fileop、50 call-site type checks；完整 Server build 仅 Linux。 [VERIFIED: 2026-08-11 local run; `AGENTS.md`] |
| Server Go | `go test` | `fileserver/*_test.go` | `cd fileserver && go test -count=1 -run 'Cf[A-Z]' .` | 本机 Go 1.24.4 已通过。 [VERIFIED: 2026-08-11 local run] |
| Local agent | `go test` | sparse existing package tests | `go test ./...` | 本机已通过；session/runner 当前无对应测试。 [VERIFIED: 2026-08-11 local run; `rg --files ../cloudfile-local-agent -g '*_test.go'`] |
| Integrated E2E | Compose + Python matrices | `tests/e2e/*_matrix.py`, `tools/verify-local.sh` | `./tools/verify-local.sh cap <capability>` | Docker CLI/Compose 可用；需 daemon、镜像和 profile 依赖。 [VERIFIED: 2026-08-11 version audit; existing verifier] |

### Fast And Slow Gates

- **每次 task commit（<30s 目标）:** 只跑所改仓库的 focused unit/contract command，再跑 `python3 tools/preflight-checks.py . ..`；涉及 shell 时补 `bash -n`。 [VERIFIED: `.planning/codebase/TESTING.md`; project conventions]
- **每个 plan 完成:** 跑该 plan 横跨的 Hub/C/Go/Agent focused tests和共享 fixture parity；不可在本机运行的 Hub pytest 进入 Hub 容器执行。 [VERIFIED: current environment limitations]
- **每个 wave merge:** `tools/run-checks.sh` 加四仓库单测；完整 C build 使用 Linux build container/CI。 [VERIFIED: `AGENTS.md`; `.github/workflows/checks.yml`]
- **Phase gate（慢）:** `./tools/verify-local.sh cap acl`, `cap search`, `cap fileop`, 新的 `cap collaboration`，随后 baseline；CI 对应 capability workflows 全绿。 [VERIFIED: existing verifier/workflows; locked integrated matrix]

### Suggested Plan → Verification Map

| Plan | Requirements | Fast verification | Slow / integrated verification | Required negative/failure cases |
|---|---|---|---|---|
| 01 Truthful Gate Contract | GATE-01 | capability manifest parser/self-tests；preflight parity；shell syntax | local `verify-local` dry/preflight 与 `checks.yml` 使用同 manifest | required dependency→FAIL；intentional optional→SKIP；未执行→NOT RUN；断言失败→FAIL；无 evidence 不得 PASS。 [VERIFIED: requirement/context/UI-SPEC] |
| 02 Effective ACL Authority | SEC-01, SEC-02 | Hub ACL/search tests；C ACL fixture；Go fileserver tests | 两 search backend + sync/direct link matrix，含 restart/revoke/cache | invisible name/path/snippet/total；outage/malformed/stale deny；inactive pass；旧 link 即时撤权；pagination 精确。 [VERIFIED: requirement/context] |
| 03 Operation Identity And Generation Fence | FILEOP-01, LOCK-01 | C/Go shared cases；按 op_id journal assertion；lock generation tests | browser/API、fileserver、WebDAV、batch delete、observer failure matrix | duplicate/missing terminal；partial abort；same-owner stale/absent generation；post-commit observer failure不回滚/不二次终结。 [VERIFIED: requirement/context] |
| 04 Versioned Local Edit | LOCAL-01, LOCAL-02 | Hub schema/API tests；frontend descriptor test；Agent session/runner tests | collaboration matrix local path，必要时真实 Chrome handoff 作为环境可用 gate | unsupported version；double/expired claim；origin mismatch；lost response same-key retry；conflict；stale generation；不得创建 sibling；heartbeat renew。 [VERIFIED: requirement/context/UI-SPEC] |
| 05 Authenticated OnlyOffice | OFFICE-01, OFFICE-02 | bootstrap executable-settings tests；registry/JWT/callback transaction tests | Compose Document Server collaboration matrix，含 restart | enabled missing/mismatch secret startup fail；missing/invalid JWT；status 2/4/6；duplicate/concurrent retry；stale callback不写/不释放；download/update failure不返回假成功。 [VERIFIED: requirement/context; CITED callback docs] |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|---|---|---|---|---|
| SEC-01 | 两 backend 无任何隐藏搜索可观察信息 | unit + E2E | `./tools/verify-local.sh cap search` | ✅ 扩展现有 `search_matrix.py`。 [VERIFIED: repository files] |
| SEC-02 | active failure/stale deny、inactive pass | C/Go + E2E | `./tools/verify-local.sh cap acl` | ✅ 扩展现有 ACL matrix / Server tests。 [VERIFIED: repository files] |
| FILEOP-01 | stable id、一次 PREPARE/终态 | C/Go + E2E | `./tools/verify-local.sh cap fileop` | ✅ 扩展现有 fixture/matrix。 [VERIFIED: repository files] |
| LOCK-01 | mutation/release generation fence | C/Go + E2E | `./tools/verify-local.sh cap fileop` | ⚠️ Wave 0 增加 generation cases。 [VERIFIED: current tests lack full path] |
| GATE-01 | canonical parity/status truth | unit/static | `python3 tools/preflight-checks.py . ..` | ⚠️ Wave 0 增加 manifest/status self-tests。 [VERIFIED: current red run] |
| LOCAL-01 | 四端 v2 schema | Python/Jest/Go contract | `go test ./...` + focused Hub/Jest | ⚠️ Wave 0 增加 shared fixture consumers。 [VERIFIED: current test inventory] |
| LOCAL-02 | existing-file update/idempotency/conflict | unit + E2E | `./tools/verify-local.sh cap collaboration` | ❌ Wave 0 新建 collaboration matrix。 [VERIFIED: no current workflow/matrix] |
| OFFICE-01 | conditional registration + mandatory matching JWT | settings/unit + E2E | `python3 tools/test-bootstrap-settings.py` + collaboration cap | ⚠️ bootstrap test exists，Office cases缺失。 [VERIFIED: current tests] |
| OFFICE-02 | callback save/retry/conflict/release | transaction + E2E | `./tools/verify-local.sh cap collaboration` | ❌ Wave 0 新建 Office matrix/callback tests。 [VERIFIED: current tests] |

### Wave 0 Gaps

- [ ] `config/capabilities.json`（名称可按仓库惯例调整）及 `tests/tools/test-capability-status.*`，先恢复 GATE-01。 [VERIFIED: current duplicate lists]
- [ ] 扩展 `docs/acl-cases.json`、`docs/fileop-cases.json`，新增 local session schema/golden fixture；C/Go/Python 都消费或校验同一案例。 [VERIFIED: existing shared-case pattern]
- [ ] Hub search ACL、file_actions idempotency、office callback transaction/registry/JWT focused tests。 [VERIFIED: current gaps]
- [ ] Server authority-state/revision、operation pairing、generation fence 的 C/Go tests。 [VERIFIED: current gaps]
- [ ] Agent `internal/session` 与 `internal/runner` tests；Chrome extension 最小 JS handoff contract test。 [VERIFIED: current gaps]
- [ ] `tests/e2e/collaboration_matrix.py`、`.github/workflows/collaboration-e2e.yml` 和对应 `verify-local` manifest entry。 [VERIFIED: absent in current tree]

### Checks That Can Run Locally

Python bootstrap/preflight、Shell syntax、Server C harness、Server Go tests、Agent Go tests可直接本地运行；Hub pytest 需先建立仓库 venv/容器，前端 Jest 需 node_modules；完整 Server C build 和最终 Compose/OnlyOffice/双搜索后端矩阵应在 Linux build container 或 CI 运行。 [VERIFIED: 2026-08-11 environment audit; `AGENTS.md`]

## Security Domain

### Applicable ASVS Categories

本研究按最新稳定版 ASVS v5.0.0（2025-05 发布）使用新章节编号；v4 的 V2/V3/V4/V5/V6 编号已不适合本阶段的长期验证记录。 [CITED: https://github.com/OWASP/ASVS/tree/v5.0.0_release/5.0/en; https://github.com/OWASP/ASVS/releases/tag/v5.0.0_release]

| ASVS Category | Applies | Standard Control |
|---|---|---|
| V2 Validation and Business Logic | yes | API boundary strict schema、protocol/status allowlist、normalized repo path、exactly-one terminal state machine。 [VERIFIED: current stack and phase contracts; CITED ASVS v5.0.0 tree] |
| V4 API and Web Service | yes | DRF/API auth、明确错误状态、final fileserver enforcement、bounded callback/download。 [VERIFIED: Hub/fileserver implementation seams; CITED ASVS v5.0.0 tree] |
| V5 File Handling | yes | existing-file update、expected file/commit、路径归一化、禁止 sibling replacement。 [VERIFIED: LOCAL-02 contract and current writeback gap; CITED ASVS v5.0.0 tree] |
| V6 Authentication | yes | Seahub session/token；local one-time origin-bound ticket；OnlyOffice signed JWT。 [VERIFIED: current Hub auth classes/session code; CITED OnlyOffice signature docs; ASVS v5.0.0 V6] |
| V7 Session Management | yes | one-time claim、absolute expiry、heartbeat lease、generation、durable terminal outcome。 [VERIFIED: local session/lock implementation and requirements; CITED ASVS v5.0.0 V7] |
| V8 Authorization | yes | Server/fileserver final ACL + revision；active authority fail closed。 [VERIFIED: `AGENTS.md`; SEC requirements; CITED ASVS v5.0.0 V8] |
| V9 Self-contained Tokens | yes | OnlyOffice JWT 严格算法/secret/header-body 验证，descriptor 不携长期 credential。 [VERIFIED: office/local contracts; CITED ASVS v5.0.0 V9; OnlyOffice signature docs] |
| V11 Cryptography | yes | PyJWT HS256 与部署 secret；不得自写签名或在日志回显 secret。 [VERIFIED: current dependency; CITED ASVS v5.0.0 V11; OnlyOffice docs] |
| V13 Configuration | yes | enabled 时 non-empty same-source JWT，缺配置 startup FAIL；secret 不写仓库。 [VERIFIED: OFFICE-01 and project constraints; CITED ASVS v5.0.0 V13] |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---|---|---|
| 搜索 total/snippet/cache 泄漏 | Information Disclosure | observable state 前有效 ACL + revision-aware invalidation。 [VERIFIED: SEC-01] |
| authority outage 被编码为 unrestricted | Elevation of Privilege | explicit active/error state，active fail closed。 [VERIFIED: SEC-02] |
| stale generation 覆盖新内容 | Tampering | native PREPARE 原子 generation/source-version compare。 [VERIFIED: LOCK-01] |
| duplicate callback/writeback | Replay / Tampering | durable unique claim + stable operation_id + prior outcome。 [VERIFIED: FILEOP-01/OFFICE-02/LOCAL-02] |
| 无签名 OnlyOffice callback | Spoofing | enabled startup 强制同源非空 secret，PyJWT 验证后才解析执行。 [VERIFIED: OFFICE-01; CITED official docs] |
| one-time ticket 或 URL 被跨 origin 重放 | Spoofing / Replay | digest-at-rest one-time ticket、短 expiry、origin-bound URL、claim 协议版本。 [VERIFIED: current local session service/Agent checks] |
| authority/Office 依赖故障造成无限等待 | Denial of Service | bounded timeout/retry；安全依赖不可用时明确 FAIL/deny，不伪装 PASS。 [VERIFIED: locked gate/ACL decisions] |

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|---|---|---:|---:|---|
| Python | control-plane fast tests | ✓ | 3.9.6 | CI uses project Python image. [VERIFIED: 2026-08-11 `python3 --version`] |
| pytest / PyJWT | Hub focused tests | ✗ in system Python | — | Hub venv/container;不要污染系统 Python。 [VERIFIED: 2026-08-11 import audit] |
| Go | Server fileserver + Agent tests | ✓ | 1.24.4 darwin/arm64 | CI pinned toolchain. [VERIFIED: 2026-08-11 `go version`] |
| Node / npm | Hub frontend contract tests | ✓ | 24.14.0 / 11.9.0 | 使用项目锁定 Node 20.x 容器保证最终结果。 [VERIFIED: local audit; `.github/workflows/checks.yml`] |
| Docker / Compose CLI | integrated matrices | ✓ | 29.4.0 / v5.1.2 | CI runner；daemon/profile services仍需 preflight。 [VERIFIED: 2026-08-11 version audit] |
| C compiler / GLib | Server C harness | ✓ | Apple clang 21 / GLib 2.86.4 | 完整 build 使用 Linux container/CI。 [VERIFIED: 2026-08-11 audit; `AGENTS.md`] |
| OnlyOffice / SeaSearch / Meili services | slow matrices | not probed running | configured images | Compose profile/CI；required 时缺失必须 FAIL。 [VERIFIED: Compose/workflow configuration; GATE-01] |

**Missing dependencies with no fallback:** 最终 phase gate 若无法启动被声明 required 的 OnlyOffice 或选定搜索 backend，应 FAIL，不能降级为 PASS。 [VERIFIED: locked decision]

**Missing dependencies with fallback:** 本机 Hub pytest 可在 Hub/container venv 运行；完整 C build 可转 Linux CI，但这些 fallback 仍须在 phase gate 留下执行证据。 [VERIFIED: environment audit; project constraints]

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|---|---|---|
| A1 | 示例 wire shape 的具体字段名可按 `operation_id`、`lock_generation`、`revision` 采用。 | Code Examples | 低；CONTEXT 明确把最小 wire representation 交给实现裁量，但 planner 不应把示例字段名误当既有 API。 |

## Open Questions (RESOLVED)

1. **SeaSearch 是否提供可验证的服务端 ACL filter 能力？**
   - What we know: 当前 Hub SeaSearch 分支没有 CloudFile ACL 输入，后过滤会泄漏 total。 [VERIFIED: `../cloudfile-hub/seahub/api2/views.py`]
   - RESOLVED: 本阶段选择 correctness-first、backend-independent 的分批 over-fetch/authorization 流，直到得到精确 authorized total/page；不依赖未验证的 SeaSearch 服务端 ACL filter。只有后续经容器实测和官方接口证明语义等价，才可单独优化下推。 [RESOLVED: adopted by Plans 02-03]

2. **”matching secret” 的运行时证明边界是什么？**
   - What we know: Compose 可由同一 env 注入 Hub 与 Docs，真实 signed callback 可证明配对。 [VERIFIED: Compose seam; CITED official signature docs]
   - RESOLVED: 选择 same-source secret：Compose 将同一 env 值注入 Hub/worker/Docs，startup 验证非空，真实 signed callback smoke 作为运行时配对证明；不得新增 secret fingerprint 或明文比较 API。 [RESOLVED: adopted by Plans 13-16]

3. **真实 Chrome handoff 是否作为 CI required？**
   - What we know: extension 只负责 `.cloudfile` 下载到 Native Messaging handoff，独立于 Server image；当前没有浏览器自动化 harness。 [VERIFIED: `../cloudfile-chrome-extension/background.js`; current tests]
   - RESOLVED: schema/JS/Agent handoff contract 始终 required；真实浏览器 handoff 只在 runner 具备 Chrome、extension 安装与 native-host 注册时执行，否则必须输出带 reason 的显式 SKIP，绝不能 PASS。 [RESOLVED: adopted by Plans 09-12]

## Sources

### Primary (HIGH confidence)

- `01-CONTEXT.md`, `01-UI-SPEC.md`, `.planning/REQUIREMENTS.md`, `AGENTS.md` — locked scope、UI 与项目约束。 [VERIFIED: local files]
- Hub: `seahub/api2/views.py`, `cloudfile_ext/acl/`, `cloudfile_ext/search/`, `cloudfile_ext/file_actions/`, `cloudfile_ext/office/`, `seahub/onlyoffice/views.py` — 实际 API/业务 seam。 [VERIFIED: local source and CodeGraph]
- Server: `common/cf-{ext,fileop,lock}.*`, `server/repo-op.c`, `fileserver/cf_{ext,fileop}.go`, `fileserver/{sync_api,fileop}.go` — 最终裁决与写路径。 [VERIFIED: local source and CodeGraph]
- Agent/extension: `internal/session/session.go`, `internal/runner/runner.go`, `background.js` — local protocol 与 handoff。 [VERIFIED: local source]
- Docker control plane: Compose、bootstrap、preflight、verify-local、workflows、E2E matrices。 [VERIFIED: local source and executed commands]
- OnlyOffice official signature/security/callback docs — JWT 与 callback status/response contract。 [CITED: https://api.onlyoffice.com/docs/docs-api/additional-api/signature/; https://api.onlyoffice.com/docs/docs-api/additional-api/signature/request/; https://api.onlyoffice.com/docs/docs-api/usage-api/callback-handler/; https://api.onlyoffice.com/docs/docs-api/get-started/how-it-works/security/]
- OWASP ASVS v5.0.0 official release/tree — 当前稳定版本与 V2/V4/V5/V6/V7/V8/V9/V11/V13 类别编号。 [CITED: https://github.com/OWASP/ASVS/releases/tag/v5.0.0_release; https://github.com/OWASP/ASVS/tree/v5.0.0_release/5.0/en]

### Secondary (MEDIUM confidence)

- 无；所有决定性结论来自本地 owning code、执行结果或官方文档。 [VERIFIED: research log]

### Tertiary (LOW confidence)

- 无未验证的生态搜索结论。 [VERIFIED: research log]

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — 直接来自仓库 manifests、Compose 与当前源码，无新增依赖。 [VERIFIED: local manifests]
- Architecture: HIGH — CodeGraph 与 owning code 交叉定位了 search、fileserver、fileop、lock、local、office seam。 [VERIFIED: local source exploration]
- Pitfalls: HIGH — 多数是当前可复现控制流；OnlyOffice协议由官方文档验证。 [VERIFIED: local source; CITED official docs]
- Validation: HIGH — 快测实际执行，慢测命令来自现有 verifier/workflows；明确标出本机缺失依赖。 [VERIFIED: 2026-08-11 command runs]

**Research date:** 2026-08-11
**Valid until:** 2026-09-10（实现开始前若四仓库 SHA 或 OnlyOffice/搜索镜像线改变，应重新核验） [VERIFIED: current repository state; validity is a planning policy]
