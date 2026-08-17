# 扩展能力矩阵

> 用途：统一记录能力状态、代码来源、产品定位、证据和上游策略
> 适用版本：Seafile CE 14 参考基线，当前 `dev` 代码
> 当前状态：有效；状态按代码、配置、测试和已记录验证保守判定

状态含义：**已完成**表示当前范围有实现及可复现验证；**验证中**表示实现存在但当前
环境、组件版本或端到端覆盖仍有限；**部分完成**表示只有定义范围的一部分可用；**规划**
表示没有可确认实现；**待确认**表示证据不足。门禁文件存在不等于门禁已经成功运行。

验证策略：GitHub Actions 只保留 `dev` 快速检查和 `prod` 生产构建；所有容器 E2E
与能力矩阵均通过 `./tools/verify-local.sh` 在本地执行。

实现策略是先复用 Seafile 已有可用模块，再用可关闭扩展补齐缺口。每项能力先形成覆盖
权限、数据、配置、故障和验证的完整 MVP，再持续改进界面、兼容范围和运维自动化。

| 功能名称 | 当前状态 | 代码来源 | 改动范围 | 产品定位 | 主要依赖 | 证据 | 上游策略 | 重要说明 |
|---|---|---|---|---|---|---|---|---|
| CE 14 源码构建与扩展基线 | 已完成 | 复用 Seafile CE；本项目新增构建/配置 | 部署、配置、构建 | CE 补强 | Docker、离线基础镜像、锁定的上游提交 | [`release.yaml`](../release.yaml)、[`Dockerfile.base`](../image/cloudfile_14.0/Dockerfile.base)、[`base-build.sh`](../image/cloudfile_14.0/base-build.sh)、[`build-platform.sh`](../tools/build-platform.sh)、[`build-and-e2e.yml`](../.github/workflows/build-and-e2e.yml)、[`smoke.py`](../tests/e2e/smoke.py)、[`cloudfile-build.sh`](../build/cloudfile_14.0/cloudfile-build.sh) | 拆分后 PR | 日常应用镜像要求本地或内网基础镜像，并禁止拉取和构建期联网；首次发行包源码/项目依赖仍需预置或缓存。构建已做冷启动加速并加固缓存：`cloudfile-build.py` 拆 `--compile-only`/`--package-only` 使 C/Go 编译与前端构建并行、C/Go 走 ccache、缓存戳按架构/SOABI 区分，基础镜像升到 ce14-v2（冷构建约 15.5min→7.7min）。基础镜像构建按宿主机自动探测原生平台（macOS Apple Silicon→arm64、Windows Docker Desktop→amd64、Linux 按 `uname -m`），避免 Apple Silicon 上静默走 QEMU 出 amd64 工具链；`CF_PLATFORM` 仍可覆盖且只接受 amd64/arm64。当前无正式 CE 14 镜像；不能把上游预览功能算作扩展版交付。 |
| 扩展注册与功能开关 | 已完成 | 扩展版既有代码；少量上游注入点 | 前端、后端、配置 | CE 补强 | Django、seafile-server RPC | [`cloudfile_ext/apps.py`](../../cloudfile-hub/cloudfile_ext/apps.py)、[`cf-ext.c`](../../cloudfile-server/common/cf-ext.c)、[`baseline.py`](../tests/e2e/baseline.py) | 拆分后 PR | 无 provider 时必须透传 CE；可提取通用 hook/registry 设计，CloudFile 命名和产品开关不提交。 |
| 目录级 ACL | 已完成 | 本项目新增 Hub/C 实现；复用 CE 库权限和组 | 前端、后端、数据结构 | Pro 平替 | `cf_dir_acl`、Seafile 身份/组 | [`acl-semantics.md`](acl-semantics.md)、[`acl-cases.json`](acl-cases.json)、[`acl-e2e.yml`](../.github/workflows/acl-e2e.yml) | 不适合 PR | 目标接近细粒度目录权限；当前证据不构成与 Pro 完全兼容。同步入口每次读取 C 权威结果，启用后故障 fail closed；六入口（REST/上传下载/打包下载/同步/WebDAV/移动重命名）加即时撤权与管理员清空容器矩阵 37/37 通过。 |
| Authentik 登录入口 | 部分完成 | 复用 CE OAuth2/OIDC；本项目新增配置翻译；Authentik 提供协议/身份源适配 | 配置、部署、外部服务 | CE 补强 | Authentik 2026.5.6、Seahub OAuth2/OIDC | [`bootstrap.py`](../scripts/scripts_14.0/bootstrap.py)、[`test-bootstrap-settings.py`](../tools/test-bootstrap-settings.py)、[`seahub/oauth/`](../../cloudfile-hub/seahub/oauth/)、[认证说明](features/sso-authentik.md) | 拆分后 PR | 默认采用通用 OIDC Authorization Code，不开发专用协议。完整 OAuth 配置、TLS 默认、RP 发起登出和首次用户策略已在启动阶段验证；仓库仍缺 Authentik 登录、登出和恢复容器 E2E。生产固定稳定补丁版本，不使用 `latest`。 |
| 组织与组同步 | 已完成 | 本项目新增；复用 CE 组与登录信号 | 后端、数据结构、worker | Pro 平替 | `cf-worker`、目录 provider、`cf_sso_*` | [`cloudfile_ext/sso/`](../../cloudfile-hub/cloudfile_ext/sso/)、[`sso_matrix.py`](../tests/e2e/sso_matrix.py)、[`sso-e2e.yml`](../.github/workflows/sso-e2e.yml) | 不适合 PR | 已验证 `static` 目录语义；`external-service` 有代码和单测。LDAP/AD/Authentik 目录源未做专属 provider 验证。只同步已存在用户的组关系。 |
| 目录/文件操作日志（提交变更） | 验证中 | 本项目新增查询/UI；复用 CE/seafevents 事件 | 前端、后端、外部服务 | Pro 平替 | seafevents `Activity` | [操作日志](features/audit.md)、[文件/文件夹历史增强](features/history.md)、[`cloudfile_ext/audit/`](../../cloudfile-hub/cloudfile_ext/audit/)、[`audit_matrix.py`](../tests/e2e/audit_matrix.py)、[`audit-e2e.yml`](../.github/workflows/audit-e2e.yml)、[`review_history_matrix.py`](../tests/e2e/review_history_matrix.py) | 不适合 PR | E2E 已覆盖目录创建/重命名、文件上传、移动、删除与恢复的查询，含按类型/按操作筛选与旧路径保留，容器矩阵通过；批量操作 detail 为列表导致列表接口崩溃已修复（951203edb）。P2-08 已补齐：查询/导出接口支持按时间/操作人/类型/对象/来源/结果/路径筛选，`source`/`result`/`before`/`after` 作为一等字段返回，标签增删/改名/系统标签变化经 `cf_audit_event`（seafile-db）记录前后值并可导出 CSV。P2-10 已给文件/文件夹历史补绿：`file/history` 支持 `q`/`operator`/`source`/`page`/`per_page`，`repo/history` 支持 `path` 文件夹范围（默认直属下一级）与 `current_folder_only`，均加性参数、不传时与 CE 一致；容器矩阵 7/7 通过。不覆盖读取/下载访问日志、合规审计、不可抵赖或长期留存。审计字段已按决策简化收敛到 CE `Activity` + `before`/`after` 侧车；PRO 的 `client_ip`/`device`/`request_id` 属访问/合规范畴，不追求。 |
| 文件属性与多视图 | 验证中 | 复用 CE 前端/API/seafevents；复用官方 metadata-server；本项目新增部署配置 | 前端、后端、部署、外部服务 | CE 补强 | `seafile-md-server`、Redis、JWT | [`metadata-e2e.yml`](../.github/workflows/metadata-e2e.yml)、[`metadata_matrix.py`](../tests/e2e/metadata_matrix.py)、[`bootstrap.py`](../scripts/scripts_14.0/bootstrap.py) | 待确认 | `cloudfile_ext/metadata` 当前无自主存储实现；自定义属性列按 metadata-server 的列名键写入（矩阵已改为列名而非内部 key），复验由 `metadata-e2e.yml` 在每次 push dev 时执行。上游 14.0 尚无 stable tag（仅 `14.0.3-testing`，2026-06-15），compose 已固定该 tag 而非 latest；上游发布 stable 后平移一次即可。容器复验发现 metadata-server 与 seahub 的 JWT 密钥必须在同一轮重建中一致（`docker compose down -v` 不带 profile 不会移除 metadata 容器，旧容器会持旧密钥导致 401）；`metadata_matrix.py` 全量通过（含移动/恢复后自定义属性与标签跟随回归）。 |
| 目录/文件标签机制 | 验证中 | 复用 CE `repo_metadata`、`repo_tags`/`file_tags` 前端与 API；复用官方 metadata-server；本项目新增部署配置 | 前端、后端、部署、外部服务 | CE 补强 | `seafile-md-server`、Redis、JWT | [标签机制](features/tags.md)、[`metadata_matrix.py`](../tests/e2e/metadata_matrix.py)、[`repo_metadata/`](../../cloudfile-hub/seahub/repo_metadata/)、[目录表格前端](../../cloudfile-hub/frontend/src/components/dir-view-mode/dir-table-view/index.js)、[`review-tags-cases.json`](review-tags-cases.json)、[`review_tags_matrix.py`](../tests/e2e/review_tags_matrix.py)、[`repo_tags` 端点](../../cloudfile-hub/seahub/api2/endpoints/repo_tags.py) | 拆分后 PR | 旧 `FileTags` 只证明文件标签；元数据记录与目录表格提供了目录/文件统一绑定通路，当前 E2E 已验证标签创建、绑定、反查、重命名/移动跟随与恢复；容器 E2E（`review_tags_matrix.py`，tags-001~005）5/5 通过（修复了 fixture 参数顺序导致的系统标签预置 404）。自定义属性跟随随 metadata-server 一并复验通过；稳定镜像待确认。P2-07 已在 `repo-tags` 落地系统/用户标签（`is_system`，仅 `CF_ENABLE_TAGS` 开启时生效）：系统标签仅 `admin` 可写、用户标签 `rw` 及以上可编辑、列表先用户后系统、批量加标签受 `CF_TAG_BATCH_LIMIT`（默认 100）上限，权限用例 tags-001～005 由 `review_tags_matrix.py` 断言。UI 侧（tags-006/007/008/009）已就绪：系统标签在「已用标签栏」显示锁形图标（`repo-info-bar.js`，`repo-tag.js` 解析 `is_system`）、列表用户标签在前（`repo_tags.py` `.order_by('is_system','id')` 前端保序）、超过两枚折叠（`file-tags/index.js`）、点击标签仅选中不弹关联列表（`tags-tree-view` `selectTag`）。系统/用户标签只存在于 CE `repo_tags`，metadata-server `/metadata/tags/` 上游无该概念，故锁形/排序落在 repo-tags 展示面而非 metadata 标签树。 |
| 全文检索 | 部分完成 | 复用 CE/SeaSearch；可选本项目 Meilisearch provider 和索引器 | 前端、后端、worker、外部服务 | Pro 平替 | SeaSearch 或 Meilisearch | [`cloudfile_ext/search/`](../../cloudfile-hub/cloudfile_ext/search/)、[`search-e2e.yml`](../.github/workflows/search-e2e.yml)、[`search_matrix.py`](../tests/e2e/search_matrix.py)、[`review-search-cases.json`](review-search-cases.json) | 不适合 PR | 解开 Pro API 门控不适合提交；Meilisearch 仅提取通用 provider seam 后才可能讨论。目录 ACL `invisible`/`none` 统一查询后裁剪（复用 acl resolver，fail closed）；高级筛选（类型/位置/标签/创建人/时间/大小）接同一入口，标签命中经 `matched_tags` 与名称命中区分；UI 侧"匹配标签"徽标与文件夹"打开/定位"已加；容器 E2E（`review_search_matrix.py`，search-001~007）通过。索引器修复：`batch_<op>` Activity 行归一化并展开 detail 列表、文档 id 去掉冒号、mtime 存 unix 时间戳、文件夹范围用 `dirs IN` 过滤（meilisearch 1.10 无 STARTS WITH）。 |
| 原生预览入口 | 验证中 | 复用 CE 预览；本项目新增动作选择和兼容补丁 | 前端、后端 | CE 补强 | Seahub 预览组件 | [`file_actions/`](../../cloudfile-hub/cloudfile_ext/file_actions/)、[`local-professional-software.md`](../../cloudfile-hub/docs/local-professional-software.md) | 拆分后 PR | CloudFile 不实现渲染器；格式覆盖与 Seafile CE 14 上游预览能力一致，预览版新增格式不能自动计入。 |
| OnlyOffice 在线编辑 | 部分完成 | 复用 CE/OnlyOffice 集成；本项目新增回调校验与锁协同 | 前端、后端、外部服务 | Pro 平替 | OnlyOffice Document Server、JWT、文件锁 | [`cloudfile_ext/office/`](../../cloudfile-hub/cloudfile_ext/office/)、[`office_matrix.py`](../tests/e2e/office_matrix.py)、[`office-e2e.yml`](../.github/workflows/office-e2e.yml)、[`docker-compose.yml`](../deploy/compose/docker-compose.yml) | 不适合 PR | 回调守卫已注册进 `apps.py`（`CF_ENABLE_ONLYOFFICE` 开启时影子接管回调 URL：JWT 验证 + 完成保存幂等 + 签入释放）。`office_matrix.py` 验证：路由挂载、**编辑页 HTML 带 OnlyOffice 配置**（会话登录后断言 `callbackUrl` + `DocsAPI.DocEditor`，031e223）、无签名回调拒绝、带签名 status 2/6 回调不 500、status 6 重投递不 500；`convert` 往返需真实 Document Server 8.2（JWT 开，`--profile office`）。本机验证 6/7 绿（仅 convert 因本机 DS 镜像拉取中断而缺），编辑页配置与回调守卫无需 DS 即可断言；convert 已在此前带 DS 的容器门禁通过。仍缺：浏览器内真实编辑会话（DS iframe 内输入并保存）。不能声称与 Pro 在线编辑等价。 |
| 复制/移动统一预检查与幂等 | 验证中 | 本项目新增 Hub 影子端点；复用 CE `copy_file`/`move_file` | 后端、数据结构 | Pro 平替 | 写入生命周期、`cf_fileop_task` | [复制/移动预检查](features/fileops.md)、[`fileops/`](../../cloudfile-hub/cloudfile_ext/fileops/)、[`review-copy-cases.json`](review-copy-cases.json)、[`review-move-cases.json`](review-move-cases.json)、[`review_copy_matrix.py`](../tests/e2e/review_copy_matrix.py)、[`review_move_matrix.py`](../tests/e2e/review_move_matrix.py) | 不适合 PR | 影子端点实现统一预检查（权限/大小/层级/配额/同名冲突）、移动返回 `affected_members`、`cf_fileop_task` 幂等去重、失败清单；`CF_ENABLE_FILEOPS` 默认关闭，四个 `CF_FILEOP_MAX_*` 限制默认 0=不限。容器 E2E 通过（copy 7 + move 9，含层级/配额/幂等/预检预览）；深度测量改用 `stat.S_ISDIR(entry.mode)`（Dirent.is_dir 在该版本不可靠）、配额错误先于大小策略。`fileops/move` 支持 `preview` 标志：只返回 `affected_members`/失败清单不落库（move-008 验证）。移动权限影响确认框已接前端：`move-dirent-dialog` 在 `CF_ENABLE_FILEOPS` 开启且 `affected_members>0` 时先弹确认框（文案含受影响成员数）再执行移动，关闭开关时保持原生 CE 直移；镜像内已含该组件（`may lose access`/`moveFileopsPreview` 已编译进 bundle）。v2.1 批量入口已接：批量移动时前端把整份选中项经 `fileops/move` 的 `src_dirents` 契约一次性预检（`moveFileopsPreview` 收整份 `srcNames`），后端 `_source_names` 归一化单条/批量两种形状；move-009 断言 `item_count` 等于选中数且预览不落库。 |
| 外部分享管控 | 验证中 | 本项目新增开关与门禁；复用 CE 外链创建/访问/列表 | 后端、配置、前端 | CE 补强 | `CF_ENABLE_SHARE_RESTRICT`、CE FileShare | [外部分享管控](features/share-restrict.md)、[`share_links.py`](../../cloudfile-hub/seahub/api2/endpoints/share_links.py)、[`review-share-cases.json`](review-share-cases.json)、[`review_share_matrix.py`](../tests/e2e/review_share_matrix.py) | 拆分后 PR | 开关默认 false = 原生 CE 分享行为。开启后非管理员创建外链 403、匿名访问旧外链按不存在处理（404）、列表/查询端点保留、管理员仍可创建与管理；前端入口隐藏属浏览器套件阶段。基线 smoke（开关全关）仍覆盖普通用户建链成功。 |
| 文件锁与签入签出 | 部分完成 | 本项目新增租约/终判；复用 CE 文件操作 | 前端、后端、数据结构 | Pro 平替 | 写入生命周期、`cf_lock_lease` | [`cf-lock.c`](../../cloudfile-server/common/cf-lock.c)、[`file_actions/`](../../cloudfile-hub/cloudfile_ext/file_actions/)、[`fileop-lifecycle.md`](fileop-lifecycle.md) | 不适合 PR | 锁/签入签出/续租/管理员恢复跨协议矩阵 21/21；WebDAV 与 REST 拒绝统一映射 423（searpc 透传 `CF_ERR_FILE_LOCKED`，见 `python/seafile/rpcclient.py` 与 seafdav patch）。目标接近 Pro 能力，客户端兼容与锁语义未证明等价。 |
| 收藏对象 ID 化 | 验证中 | 本项目新增 `obj_id` 标识与回填；复用 CE 收藏 API/前端 | 后端、数据结构、迁移 | CE 补强 | Seafile 对象 ID、`CF_ENABLE_FAVORITES_ID` | [`favorites.md`](features/favorites.md)、[`star.py`](../../cloudfile-hub/seahub/utils/star.py)、[`backfill_starred_obj_ids.py`](../../cloudfile-hub/seahub/base/management/commands/backfill_starred_obj_ids.py)、[`starred_items.py`](../../cloudfile-hub/seahub/api2/endpoints/starred_items.py) | 拆分后 PR | 收藏身份改为 `(email, org_id, obj_id)`，移动/重命名跟随对象；旧 `repo_id + path` 记录经幂等命令无损回填。内容相同的文件共享 `obj_id`，故“收藏对象”等价于“收藏内容”。开关关闭时保持原生 CE 行为；纯规则单测通过。容器 E2E（`favorites_matrix.py`，favorites-001/002）通过：星标后移动文件，收藏列表按 obj_id 重定位到新路径（`locate_obj_id` 树遍历兜底）而非标记删除；迁移回填命令可用。 |
| 本地应用查看与编辑 | 验证中 | 本项目新增 Hub 会话；已创建独立项目 `cloudfile-local-agent`、`cloudfile-chrome-extension`；复用 CE 下载/写回 | 前端、后端、外部应用 | 新应用扩展 | Native Messaging、已安装桌面软件 | [`cloudfile-local-agent`](../../cloudfile-local-agent/README.md)、[`cloudfile-chrome-extension`](../../cloudfile-chrome-extension/README.md)、[`file_actions/`](../../cloudfile-hub/cloudfile_ext/file_actions/) | 不适合 PR | 下载—领取—编辑—写回容器矩阵 14/14 通过（写回已改用 `put_file` 替换，避免生成重名副本）。内部部署无需代码签名（决策 2026-08-15：签名发布包不作为交付前提），跨平台升级仍待后续。 |
| 关注、转换与导出 | 部分完成 | 主要复用 CE/SeaDoc；本项目新增配置和 UI 接线 | 前端、部署、外部服务 | CE 补强 | 邮件任务、SeaDoc 2.0、JWT | [`.env.example`](../deploy/compose/.env.example)、[`docker-compose.yml`](../deploy/compose/docker-compose.yml)、Hub 前端补丁登记 | 拆分后 PR | 不应包装为自研渲染或转换；各格式和写回流程尚未形成独立 E2E 结论。通用 CE UI 修正可单独评估。 |
| 多存储与 S3 兼容存储 | 已完成 | 参考官方存储模型；本项目新增 CE C/Go 后端、部署、迁移和维护；MinIO 提供 S3 | 后端、部署、配置、数据结构 | Pro 平替 | MinIO、`RepoStorageId` | [存储说明](features/storage-backends.md)、[`storage-e2e.yml`](../.github/workflows/storage-e2e.yml)、[`storage_matrix.py`](../tests/e2e/storage_matrix.py) | 不适合 PR | 支持管理员为不同资料库指定存储方案（`RepoStorageId` + `seaf-storage-migrate` 离线迁移）；新建库自助选择/自动分配 UI 未完成。根因不只是前端：CE fork 的 C `seafile_create_repo` 与 Python `rpcclient.create_repo` 签名都没有 `storage_id`（seaserv 的 `create_repo(storage_id=...)` 参数被静默丢弃），且 `get_library_storages`/`_create_repo` 有 `is_pro_version()` 门控——要接自助分配需跨 C RPC + Python + Seahub + 前端四处改动（见 storage-backends.md）。S3 兼容性当前只验证 MinIO，不承诺其他实现。 |
| SMB/NFS 外部资料源 | 部分完成 | 本项目新增入口、授权、影子路由、扫描/Overlay；宿主机和协议栈负责挂载 | 前端、后端、部署、外部存储 | 新应用扩展 | 宿主机 SMB/NFS mount、可选 Meilisearch | [外部资料源](features/external-sources.md)、[`external_sources/`](../../cloudfile-hub/cloudfile_ext/external_sources/)、[`external_sources-e2e.yml`](../.github/workflows/external_sources-e2e.yml) | 不适合 PR | 当前 `local-path` 为只读内容入口；不是 Seafile 原生资料库，桌面同步、WebDAV、历史和锁不适用。容器 E2E（`external_sources_matrix.py`）15/15 通过：登记挂载目录、只读列举/下载、影子库出现在原生列表、Overlay 只存路径元数据与标签、目录逃逸拒绝、禁用后拒绝数据面、删除源与授权记录。真实 SMB/NFS 挂载由宿主机负责，仍待验收。 |
| CloudFile 外部资料联邦与虚拟目录挂载 | 规划 | 计划独立项目；复用 OpenList/rclone 适配外部存储；CloudFile 负责消费接口 | 外部服务、部署、前端、后端 | 新应用扩展 | OpenList、rclone | [规划说明](features/external-directory-mount.md)；当前仓无匹配代码/配置/测试 | 不适合 PR | 模块计划同时为 AI 应用提供统一文件资料库、为 CloudFile 提供虚拟目录挂载。它不同于 Seafile 虚拟资料库和现有 `local-path`；模式均未实现。 |
| Seafile AI 与外接 LLM | 验证中 | 复用官方 Seahub/Seafile AI；本项目新增 Compose profile 与配置接线；模型由外部 LLM 提供 | 部署、配置、外部服务 | CE 补强 | `seafile-ai`、Metadata Server、Redis、OpenAI-compatible/local LLM | [AI 说明](features/seafile-ai.md)、[`docker-compose.yml`](../deploy/compose/docker-compose.yml)、[`.env.example`](../deploy/compose/.env.example) | 不适合 PR | `ai` profile、官方镜像和 `CF_AI_*` 配置已存在，但当前仓无容器 E2E 结果。CloudFile 不自研模型或平行 AI 后端。 |

## 复用与新增的关键结论

- OAuth2/OIDC 登录、SAML、LDAP、元数据 UI/API、预览及部分文件管理来自 Seafile CE；
  CloudFile 的贡献主要是配置、扩展接线或缺失的组织/权限逻辑。
- S3/多存储采用 Seafile 官方文档描述的存储类与 `RepoStorageId` 模型，但当前锁定 CE
  上游提交中没有 CloudFile 新增的 C/Go 后端实现，不能简单写成“直接启用官方 CE 代码”。
- Authentik、MinIO、Meilisearch、OnlyOffice、OpenList 和 rclone 的协议、存储、检索或
  渲染能力归各自项目；CloudFile 只拥有其配置、接口和产品集成部分。
- AI 默认复用官方 Seafile AI，并由运维从 [`seafile_ai_config.example.yaml`](../deploy/compose/seafile_ai_config.example.yaml) 创建运行时配置以外接 LLM；未来外部资料联邦
  只能作为新的资料入口，不能被描述为当前 AI 已有能力。
- “Pro 平替”是内部目标分类。所有相关行都保留了未验证的等价性、兼容性或运维限制。
- 回收站决策（2026-08-15）：维持原生 Seafile CE 回收站行为，不做管理员门禁、不隐藏
  普通用户入口；评审清单里“回收站普通用户禁止”两条用例随决策移除，保留 CE 原生的
  软删除与管理员恢复验收。
- UI 用例实现状态（2026-08-15 代码核对）：图标视图多选 5 条、树悬停更多/复制、搜索
  匹配标签徽标与文件夹定位、分享入口隐藏均已在 `frontend/src` 实现（浏览器套件
  `review_ui_matrix.py` 已在真实栈上跑通：网格渲染、框选（icon-001）、ctrl 离散多选
  （icon-002）、shift 连续多选（icon-003）、全选（icon-004，网格视图全选控件已加）、
  批量操作栏（icon-005）均通过；tree-002 悬停收藏按钮已验证；tags-008 折叠已实现。
  标签 ui 四条（tags-006 锁形图标 / tags-007 用户在前 / tags-008 折叠 / tags-009 点击
  仅选中）均已实现：系统/用户标签只存在于 CE `repo_tags`，故锁形图标与排序落在消费
  `repo-tags` 的「已用标签栏」，而非 metadata 标签树（上游无 `is_system`）。复制/移动
  v2.1 批量入口已接（批量移动整份选中项经 `fileops/move` 的 `src_dirents` 一次性预检，
  move-009 断言）。详见 review-cases.md 4.5。
- 基线修复（2026-08-15）：`apply_metadata_schema_compatibility` 取消开关门控——上游
  14.0 的 `RepoMetadata` 模型无条件读 `summary_enabled` 列，但建表 SQL 缺该列，导致
  基线（开关全关）时前端目录视图（`/api/v2.1/repos/{id}/dir/`）500。现在每次启动
  无条件补齐该列（缺列时 ALTER，幂等），基线目录视图恢复 200。

## 未完成与阻塞项（2026-08-15 复核）

按特性清单逐项登记尚未闭环的条目，给出可复现现状与阻塞原因。已完成条目的验证见上文
各能力行与 `docs/review-cases.md`。

| 清单项 | 现状 | 阻塞/缺口原因 |
|---|---|---|
| OnlyOffice 浏览器内编辑会话（编辑-保存-重试去重） | 编辑页 HTML 配置（`callbackUrl`+`DocsAPI.DocEditor`）与回调守卫（无签名拒绝/带签名不 500/status 6 重投递幂等）已由 `office_matrix.py` 断言（本机 6/7 绿，仅 convert 需 DS）；纯规则 `dedupe_key` 单测通过；浏览器内真实编辑会话（DS iframe 内输入、保存、验证只落一个版本）仍待补 | 真实 Document Server 8.2 镜像本机拉取中断（约 20 分钟无进度），无法起 `--profile office` 复验 convert 与浏览器 iframe；CloudFile 侧交付物（编辑页配置 + 回调校验 + 保存幂等）已覆盖，浏览器会话主要验证第三方编辑器自身保存流程 |
| Authentik 登录/登出/故障恢复 E2E | OAuth/OIDC 配置翻译、TLS、RP 发起登出、首次用户策略已在启动阶段验证（`test-bootstrap-settings.py`） | 缺真实 Authentik 2026.5.6 服务做登录/登出/故障恢复容器 E2E（外部服务） |
| 本地 Agent 三平台签名与升级 | 下载-领取-编辑-写回容器矩阵 14/14 通过 | 决策（2026-08-15）：内部部署无需代码签名，签名发布包不作为交付前提；跨平台升级仍待后续 |
| 转换导出 / Seafile AI 完整 E2E | `ai`/`office` profile、`CF_AI_*`、转换导出 JWT 配置与 UI 接线存在 | 完整 E2E 需 SeaDoc 2.0 + 外部 LLM 端点；当前仓无容器 E2E 结果 |
| S3 新建库自助分配 UI（剩余工作，非阻塞） | 多存储后端 + 离线迁移 + 管理员按库分配已完成（`storage_matrix.py`） | 自助选择需跨 C RPC + Python + Seahub + 前端四处改动：CE fork 的 C `seafile_create_repo`/`rpcclient.create_repo` 无 `storage_id`（seaserv 参数被静默丢弃），且 `get_library_storages`/`_create_repo` 有 `is_pro_version()` 门控；属超出本轮预算的 P2 全栈改动，非环境或上游阻塞 |
| 审计字段（简化，决策 2026-08-15） | 以 CE `Activity` 字段为准（操作者/时间/库/路径/操作/旧路径/提交）+ `cf_audit_event` 侧车 `source`/`result`/`before`/`after` | 参照 CE/PRO：PRO 的 `client_ip`/`device`/`request_id` 属访问/合规审计范畴，非目录/文件操作日志必需，**不追求**，审计字段就此收敛到 CE 基线 |
| 外部资料联邦独立项目规划 | 规划文档已存在（`features/external-directory-mount.md`） | 按决策作为独立项目，当前仓无实现 |
