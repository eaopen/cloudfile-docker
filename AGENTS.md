# AGENTS.md — cloudfile-docker

> **当前版本规则**：`cloudfile-docker/dev` 就是 CloudFile **V2 当前开发主线**，以 Seafile CE14 为基础。与 `cloudfile-server/dev`、`cloudfile-hub/dev` 统一，不存在另一条“当前 V0.x dev”。本规则适用于 AI 开发 Agent 和维护者。

## 最小分支规则

| 名称 | 用途 |
| --- | --- |
| `dev` | 当前唯一 V2 开发主线 |
| `feat/<功能>` | 新功能 |
| `fix/<问题>` | 缺陷修复 |
| `docs/<主题>` | 文档更新 |
| `archive/<历史名称>` | 历史只读快照，不作新开发起点 |

不再给新分支强制增加 `v2/`、发布日期、任务号，也不新增 `dev2`/`dev3` 等版本开发主线。旧 `feature/*`、`fix/v2/*` 任务完成前不强制改名；旧 `dev2`、`dev2-clean` 已归档，V0.x 不允许整枝合入当前 `dev`。完整统一规范见 [BRANCHING.md](BRANCHING.md)。

跨仓任务可同名，但仅在确有修改的仓库创建分支。**兼容性看三仓固定 SHA，不看分支名是否一致。**

## Docker 负责什么

CloudFile Server 负责 C/Go 底层文件、权限与存储；Hub 负责 Web/API/SSO；本仓负责 V2 源码组装、构建、镜像、部署及三仓的真实兼容组合。

**版本与构建事实必须分开：**
- `dev` 表示当前 CloudFile V2 **代码开发线**，不等于正在部署的镜像，也不等于已运行通过的组合。
- 旧构建链的源码快照（`source-set.json`）不在本仓保留；其中 `overlay_commit` 可能早于最新 `dev`，不能仅凭文件名推断为当前 HEAD。
- 根目录 `release.yaml` 与 `build/cloudfile_14.0/` 是当前唯一构建实现；三仓分支在开工时经远端解析一次，生成 `build-receipt.json`，后续仅按收据里的 SHA 构建和验证。旧白名单组装已移出本仓，不作构建入口。
- 真正构建/交付时，须明确 Server、Hub、Docker 的具体 Commit SHA、上游 CE 源码基线与镜像 Digest；历史 V2-clean CI 成功不代表最新 `dev` 已联验。

## 目录分工：上游原样，CloudFile 平行叠加

本仓与上游 `haiwen/seafile-docker` 并行维护，规则与 CE / Pro 那对目录一致：**上游目录保持原样，CloudFile 只放在自己的同名目录里。** 这样同步上游时不会出现 delete/modify 冲突，也能一眼看出哪部分是我们的。

| 层 | 上游（原样，不要改） | CloudFile（唯一新增点） |
| --- | --- | --- |
| 构建 | `build/seafile_14.0/`（`seafile-build.{sh,py}`） | `build/cloudfile_14.0/`（收据、组装、来源校验、`cloudfile-build.sh`） |
| 镜像 | `image/seafile_14.0/`、`image/pro_seafile_*/` | `image/cloudfile_14.0/`（`Dockerfile.base` + `Dockerfile`） |
| 启动脚本 | `scripts/scripts_14.0/` | `scripts/scripts_cf14.0/`（`cloudfile.py`、`cloudfile_schema.py`、`cloudfile_bootstrap.py`、`library_storage.py`） |
| 服务配置 | `services/nginx.conf` 等 | 同文件内的 `# CloudFile:` 段（改动登记在 `docs/upstream-patches/`） |

1. `build/seafile_14.0/` 只允许上游那两个文件；新增实现一律进 `build/cloudfile_14.0/`。`tests/test_source_manifest.py` 有断言守着这条。
2. `scripts/scripts_14.0/bootstrap.py` 与上游逐字节一致；CloudFile 的配置生成全部在 `scripts/scripts_cf14.0/cloudfile_bootstrap.py`。保留在 `start.py` 里的只有标了 `CloudFile hook` 的三段：新增导入、`note_fresh_install()`、配置与建表调用。
3. 镜像把两个 scripts 目录摊平到 `/scripts`，所以 `cloudfile_*` 按同级模块被 `start.py` import；改 import 前先确认两棵树都会被 COPY 进镜像。
4. 需要改上游文件时先问"能不能放进 cloudfile 目录"；确实不能（例如 nginx 的 `location` 只能写在 server 块里）才改，并登记到 `docs/upstream-patches/cloudfile-docker.txt`。
5. nginx 兼容路径：`/cfile/` 重写到 `/seafile/`，`/cfhttp` 与 `/seafhttp` 同源（都去前缀转发到 8082）。两个别名都在 `services/seafile.nginx.conf` 的 `# CloudFile:` 段里，新增别名时保持同一形状。

## tools / tests 的固定分区

| 目录 | 放什么 | 不放什么 |
| --- | --- | --- |
| `tools/gates/` | 门禁：本地 preflight、三仓契约检查、开关清单一致性、提交前静态检查 | 构建、运维、迁移脚本 |
| `tools/build/` | 构建与发布辅助：平台规范化、发行包校验、历史维护发布 | 日常门禁 |
| `tools/ops/` | 运维：SSO 目录健康报表、存储类配置、自动本地存储作业 | 测试 |
| `tools/migrate/` | 迁移与导入：离线快照恢复、单向导入、工作树准备 | 常规构建 |
| `tests/e2e/smoke.py` | **默认** E2E：起得来 + 主路径通 | 能力矩阵 |
| `tests/e2e/full/` | 能力矩阵与扩展点基线，**参考用**，不进默认门禁 | 冒烟 |

新增脚本先选目录再写，不要往 `tools/` 根上堆。

## Agent 镜像构建与发布操作规程（执行前必读）

**这里描述的是仓库已经实现的机制，不是让 Agent 设计新构建系统。** 在本仓进行编译、构建镜像、联验或发布之前，必须先按本节选择现有入口；不得试错式地临时拼 Docker 命令、切换旧版 Dockerfile、重复安装依赖或绕开来源收据。代码事实优先级：`release.yaml` → 当前入口脚本 → `.github/workflows/{dev,prod}.yml`；旧文档与脚本冲突时以这些可执行入口为准，先记录冲突，不自行创造替代流程。

### 唯一当前入口（从仓库根目录执行）

| 工作 | 当前入口 | 执行条件 |
| --- | --- | --- |
| 普通提交、PR、纯文档 | `.github/workflows/dev.yml`、受影响文件的静态检查 | **不编译、不打镜像**；普通 push/PR 不触发完整 CI |
| 明确要求集成测试 / 制作发行包 | `bash build/cloudfile_14.0/build-in-docker.sh <version>` | 仅在明确需要可运行产物时 |
| 用既有发行包组装本地应用镜像 | `bash image/cloudfile_14.0/docker-build.sh <version>` | 必须先有同版本发行包及有效构建收据 |
| 基础镜像缺失 / 基础依赖或 Dockerfile.base 确实改变 | `bash image/cloudfile_14.0/base-build.sh` | **低频维护操作**；优先恢复已经验证的同架构基础镜像 |
| CI 三仓完整联验 | 手动运行 `.github/workflows/prod.yml`（`CloudFile receipt build`） | `workflow_dispatch`；当前是完整编译 + 隔离挂载测试，不是自动发布流水线 |
| 推送 Registry、更新 Compose / DEV / PROD | 必须另有明确发布任务及目标镜像 / Registry / 环境 | **构建成功不等于已推送或已部署**；此仓当前 workflow 不自动 push / deploy |

- `build/cloudfile_14.0/build-in-docker.sh` 是唯一构建入口，`build/cloudfile_14.0/build-local-image.sh` 转发到 `image/cloudfile_14.0/docker-build.sh`。上游 `build/seafile_14.0/` 已还原为上游原样，不承担 CloudFile 构建。历史归档脚本一律不可作为当前构建入口；`image/seafile_14.0/docker-build-push.sh`、`image/pro_seafile_*` 等上游/历史 push 入口不用于 CloudFile V2。
- **`tools/build/release-dev162.sh` 当前显式只允许 `maintenance/v0.9/*` 历史维护分支，不支持 V2 `dev` 发布。** 即使旧部署文档仍有使用示例，也不得借此脚本发布当前 V2；不要删除脚本的保护条件来绕过限制。
- 历史上的 `CLOUDFILE_RUNTIME_BASE` / `cloudfile/runtime-base:*` 说明与当前入口不一致；当前镜像链以 `release.yaml` 的 `build_base_image`（目前 `cloudfile-build-base:ce14-v2`）和 `CF_BASE_IMAGE` 为准。不要增加第二套 Runtime Base。

### 已有依赖层和缓存如何复用（默认必须复用）

1. **基础层（低频）**：`image/cloudfile_14.0/Dockerfile.base` 一次预装 Ubuntu/APT、C/Go、Node 和 Python 运行依赖；日常应用镜像 `image/cloudfile_14.0/Dockerfile` 直接 `FROM ${CLOUDFILE_BASE}`，**不重新执行 APT、安装 Node 或 pip 系统依赖**。先 `docker image inspect cloudfile-build-base:ce14-v2`，存在且架构匹配就直接用；不存在则按已验证来源 `docker pull` 或 `docker save/load` 恢复，只有基础层确需升级或明确授权重新创建时才运行 `base-build.sh`。
2. **编译层（增量）**：`build-in-docker.sh` 把 `build/cloudfile_14.0/.cache/` 持久挂载到容器，自动复用 ccache、Go build/module、npm、pip、前端工具及 Python thirdpart 缓存；也可用 `CF_CACHE_DIR` 指向已有持久目录。**不要清缓存、`docker builder prune`、`--no-cache` 或临时改路径来“修复”一个普通构建失败。**
3. **产物层（按输入指纹）**：`cloudfile-build.sh` 自带 `frontend` 和 `dist` 缓存命中/恢复逻辑。Hub 前端输入未变时恢复 webpack/assets/stats/locale；发行包输入未变时复用发行包。小改动不应该重新安装整个依赖树或全量编译；源码/架构/配方变化由已有指纹决定失效，不得手工伪造命中标记。
4. **源码层（固定 SHA）**：每轮完整构建先从 Server、Hub、Docker 的所选分支解析一次 SHA 到 `build/cloudfile_14.0/build-receipt.json`；后续继续使用同一收据（必要时通过 `CF_BUILD_RECEIPT=/absolute/path/build-receipt.json` 传递），而不是在多阶段间重复读取浮动 `dev`。Docker 工作树必须干净，且 HEAD 与收据中的 Docker SHA 一致；未提交代码不会进入正式构建。
5. **架构层**：默认构建宿主机原生 `linux/amd64` 或 `linux/arm64`；显式跨架构时需 `CF_PLATFORM` 与基础镜像架构一致。生产 AMD64 最好在 AMD64 runner/build host 构建，不要在 ARM Mac 上默默用 QEMU 做昂贵跨架构全编译。

### Agent 正确执行顺序（确实需要制作镜像时）

以下示例只生成本地发行包和镜像，不推送、不重启服务。`VERSION` 应使用此次任务指定的独立标签；示例仅供隔离测试，**不要用固定标签覆盖正在使用的镜像**。

```bash
# 0. 在 cloudfile-docker 根目录；先检查已提交源码与基础镜像
git status --short
git rev-parse HEAD
docker image inspect cloudfile-build-base:ce14-v2 >/dev/null
# 若基础镜像缺失：停止并从已验证缓存/Registry 恢复；不得立即重建。

# 1. 仅在任务明确要求集成构建时，沿用已有收据与缓存
VERSION=14.0.8-storage-test
CF_BUILD_JOBS=2 bash build/cloudfile_14.0/build-in-docker.sh "$VERSION"

# 2. 验证构建产物，使用当前脚本离线组装镜像
bash tools/build/verify-release-artifact.sh "build/cloudfile_14.0/seafile-server-$VERSION"
bash image/cloudfile_14.0/docker-build.sh "$VERSION"

# 3. 核对来源收据、架构和镜像 ID，再报告结果
python3 build/cloudfile_14.0/build_receipt.py verify \
  build/cloudfile_14.0/build-receipt.json --recipe . --version "$VERSION"
docker image inspect "cloudfile/cloudfile:$VERSION" \
  --format '{{.Id}} {{.Architecture}}'
```

- 脚本自动检查包的来源/完整性，镜像组装指定 `--pull=false --network=none`，记录来源 SHA 与本地 image config digest。**不得跳过这些检查，不能把本地 image ID 称为已经推送的 Registry manifest digest。**
- 指定其他 Server/Hub 分支时使用现有 `CF_SERVER_REF`、`CF_HUB_REF`；用于 PR 验证时 Docker 也必须在对应**已提交、干净且已推送**的分支，必要时配 `CF_DOCKER_REF`。不允许依赖未提交工作区或容器内任意克隆的 HEAD 来构建。构建缺远端 SHA 时停止，不能用旧 receipt 偷换新代码。
- 如完整编译代价太高，先判断目标：**仅修改后端**无需主动重编前端；**仅修改 Web**无需主动编译 C/Go。脚本有 `CF_BUILD_TARGET=backend|frontend|package|all`，但 `package` 必须消费匹配 SHA、校验通过的 `cloudfile-backend` 和 `cloudfile-frontend` 产物；当前 `prod.yml` 仍运行完整 `all`，**不要声称 CI 已经拆分成三个 job**。没有现成跨 job 产物时使用脚本默认 `all`，依赖自身缓存，不自行发明新流水线。
- 只为定位确定的缓存问题才有选择地设置 `CF_FORCE_FRONTEND_REBUILD=1` 或 `CF_FORCE_DIST_REBUILD=1`；`CF_FORCE_REBUILD=1` 是最后手段，禁止作为每次构建默认值。不得未经批准更改基础镜像依赖、当前 CI 触发策略或引入新 BuildKit/Makefile/Compose 流程。

### 推送 / 部署分界与失败处理

- 若只是完成代码或文档修改，**止于静态验证**；没有明确“构建”请求就不能主动执行上面的重任务。若只要求制作镜像，止于本地标签、收据和校验结果；**只有明确要求发布时**才在已授权目标 Registry 使用已校验版本化镜像执行 `docker tag` / `docker push`，并取得远端 digest。部署 Compose/DEV/PROD、数据升级和实际业务验收均是另一步，不能由 Agent 隐式执行。
- 报告必须区分：①代码 SHA 已合入；②构建收据/受影响测试通过；③本地镜像 ID；④Registry digest（如果确实推送）；⑤环境镜像和运行验收（如果确实部署）。绝不把 CI 绿色、缓存命中或本地 `docker image inspect` 写成已经部署。
- 若报缺基础镜像、架构错、receipt 不一致、测试失败或发行包不完整：**停在出错阶段**，报告现有缓存/镜像状态与具体错误，修复根因后仅重跑受影响阶段；不删除历史数据、不全量 prune、不切旧入口、不绕过 patch/测试/来源检查。

更多技术细节以构建入口 `build/cloudfile_14.0/build-in-docker.sh`、镜像入口 `image/cloudfile_14.0/docker-build.sh`、当前 CI `.github/workflows/prod.yml` 与 `CLOUDFILE.md` 为准。

## 不扩大改动范围

优先复用 Seafile CE14 的原生行为与官方依赖，不因同步上游或小修引入平行框架；原生补丁及不可绕过的安全逻辑须记录在 `docs/upstream-patches/`。

V2 内置 ACL、CE 原生 Tag 和已安装 Guard 的 Checkout 不应重新受旧版 Feature Flag 控制；可选 Meilisearch、SSO、Office 等外部组件通过真正的连接与依赖判断。不要恢复旧 `v2_acl_enabled` 或把 CloudFile 设计成“所有开关关闭就等于原生 CE”。

**本项目不使用 GSD。** 不自行生成 GSD 工件、修改外部账号/配置、覆盖现有 DEV/PROD 数据或静默改变运行容器。代码变更按当前任务最小范围推进，非必要完善项留待确认。

## 省时的验证规则

**纯文档变更不编译、不跑测试、不构建镜像，也不部署。** 小范围代码改动优先检查受影响路径、复用已验证的证据；全量 C/Go/前端构建、三仓联验及镜像发布只在明确必要的阶段或发布任务开展。不要因一次文档提交自动要求全仓编译。

不要提交 `deploy/compose/.env`、任何真实凭据、密钥、持久数据卷或镜像构建产物。文档中文，代码和 commit message 英文；上游既有风格优先。

## 数据库唯一规则：当前五表

- V2 仅保留 `cf_library_storage`、`cf_dir_acl`、`cf_sso_group_map`、`cf_edit_guard`、`cf_audit_event`。新装五表一次性创建，已有卷只校验，不自动迁移或修补。
- DEV 旧数据全部放弃。存储绑定从 Seafile 原生库重新发现，ACL/共享与组织角色从 Etech 重同步，Guard/审计从空表开始；旧 `cf_tag`/Resource/Intent/Session/Outbox 等绝不恢复。
- DEV 如需清表重建，仅允许停写后由人工管理员按当前 DDL 操作，不做产品级迁移/历史追溯/归档库；**绝不删除或改写 Seafile 原生文件版本和存储路由**。

## Agent2 本地编辑 V2 边界

- 当前 Hub Web API 是 `/api/v2.1/cloudfile/edit/v1/open/`，Agent2 URI 为 `cloudfile-open://v2/open`，Server Go 最终文件协议为 `/cf-edit/v1/*`。
- 正常查看/编辑不创建服务端 Session；独占编辑只使用 `cf_edit_guard` 与 Agent2 本地 Journal。
- **不得为修复缺表错误恢复 `cf_edit_session` / `cf_resource` / `cf_commit_intent` 或旧 `local-edit/v1/sessions` 路由。** 开发环境清理由人工管理员负责，产品不维护历史迁移工具。
- GitHub `dev` 代码修复不等于 DEV 容器已升级；发布须确认 Server/Hub/Docker 三仓固定源码 SHA 和实际镜像，并定向验收本地查看、普通编辑、独占编辑。

## 当前镜像只携带 V2 初始化及运行入口

- 启动调用 `cloudfile_schema.py`，只创建/校验 4+1 表；历史 `cloudfile.sql`、SchemaRunner 和旧 SQL Workers 不属于产品镜像。禁止为旧代码恢复 `cf_schema_migration` 或其他旧表。
- 旧 DEV 修复/迁移材料不属于当前产品代码，不由构建、启动、升级或工作进程调用。禁止用测试历史脚本的成功状态声称当前 DEV 镜像已经升级。

## 轻量跨仓运行表检查

- `tools/gates/check-sql-contracts.py` 当前只检查 4+1 DDL 与 Server/Hub/Docker/可选 Agent2 **可运行** SQL 依赖，不再生成/更新旧 001–042 checksum 台账；DEV 数据直接舍弃重建，不提供历史数据修复工具。
- `tools/gates/run-checks.sh` 不再将历史 001–042 数据转换、旧四表 SQL 包作为日常产品测试。禁止每次小改动启动全量编译。

## 现行 V2 权限契约：禁止“托管库”复活（2026-10-21）

- `dev` **不存在托管库/非托管库两种类别**。任何 `cf_dir_acl` 行只代表其目标路径和主体的显式规则，不能被用于判定整库被托管、整库访问关闭、旧入口一律拒绝或重新进入单独的库级安全模式。
- 唯一权限链：Seafile CE 原生库资格 + Hub `Authority.effective()` 对当前身份和实际路径的 ACL/共享目录结果 + C/Go 真实文件与最终 Commit 终判。无整库资格但有 `share_mode=true` 的用户只从共享目录根进入，不得开放库根、父级或兄弟目录。
- **坚决禁止**恢复 `cf_managed_library`、`cf_managed_library_share`、`cf_library_share_revision`、`checkLegacyLibrary`、`cf_policy_check_legacy_library`、`managed_library_guard`、`allow_legacy_managed_reads`，也禁止恢复用于断言“库有任意 ACL 行就应全库拒绝”的测试。
- 没有可信当前用户/路径的整库同步或无范围票据，允许因该**操作缺乏授权证明**而拒绝；这不是库分类。任何有路径证明的 Web/API/Agent/下载/上传必须按实际目标裁决，不能用无关目录的 ACL 拒绝整个库。策略异常不回退宽权限。
- 当前文档与测试应以 V2 权限终判契约及五张扩展表为准；历史文档只用于追溯，不得作为实施依据。跨仓变更必须维护防复活的源码扫描和正反权限用例。
