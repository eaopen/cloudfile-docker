<!-- generated-by: gsd-doc-writer -->
# 分支与上游跟随

> **用途**：定义 CloudFile 三仓当前有效的分支类型、合并门槛、发布 ref 与上游同步规则。
> **适用范围**：CloudFile V2 DEV（Seafile CE14 基线）。V2 是产品代际、CE14 是上游版本，均不等同于镜像发布号。
> **状态**：当前有效；实际发布 ref 以 [`../release.yaml`](../release.yaml) 为唯一真相。
> **边界**：CE 提供上游基线；CloudFile 维护扩展点、能力和门禁；官方/第三方组件的版本、许可证与可用性独立管理。

## 当前模型

CloudFile 的三个仓库通常并排 checkout，并使用同一分支语义：

```text
cloudfile-server   权限终判、C/Go 数据面
cloudfile-hub      Web、API、后台任务
cloudfile-docker   构建、镜像、部署与跨仓规格
```

分支只负责代码隔离，**产品代际由命名固定，三仓兼容由 SHA 组合验证**：

| 类型 | 命名 | 起点与去向 |
|---|---|---|
| 唯一开发主线 | `dev` | 三仓当前均代表 V2；不再另开 dev2/dev3/dev14 |
| 新特性 | `feature/v2/<work>-<topic>` | 从各仓 `dev` 创建，只建确有改动的仓；测试后合回各仓 `dev` |
| 修复 | `fix/v2/<work>-<topic>` | 从 `dev` 创建；修复完成后删除 |
| 文档 | `docs/v2/<topic>` | 从 `dev` 创建；不混入运行代码 |
| 同步上游 | `sync/ce14/<YYYYMMDD>` | 在受影响仓从 `dev` 创建，更新 CE anchor 后删除 |
| 发版冻结 | `release/v2.x.y` | 只在 Docker 建立；临时冻结三仓 SHA，发布后使用不可变 Tag |
| 发布修复 | `hotfix/v2.x.y/<topic>` | 从目标已发布 Tag 派生，完成后按评审同步到 `dev` |
| 遗留维护 | `maintenance/v0.9/<topic>` | 仅从 V0.9 归档建立，不直接合入 V2；所需修复单独移植 |
| 只读来源 | `archive/*`、`seafile/*` | 历史 / 上游，不接受常规开发提交 |

`<work>` 可以是 Issue ID 或统一短工作编号；跨仓任务使用同一 ID 和语义（例如 `feature/v2/cf-123-local-object-staging`）。同名仅用于识别任务，**不能当成版本兼容证明**。历史在途分支不强制改名，先完成现有 PR 再按新命名执行。

长期客户定制与产品主线隔离，不能用未经验证的长期 `feature/*` 来充当可发布版本。

## 三仓组合与发布清单

1. **开发快照**：在 Docker 主导的一次集成验证中，实际解析并记录 `server_sha`、`hub_sha`、`docker_sha`、CE 基线、构建时间与 API/DB 契约；CI 用固定 SHA 运行整个测试过程。可以从 `dev` 或同一工作项的在途分支解析，但不得在测试过程中再读取可移动的 `dev`。
2. **跨仓能力**：先验证 Server、Hub、Docker 的同一提交组合，再按兼容顺序合并。若需要双边同时升级，使用兼容过渡接口或短暂冻结集成，不能仅因为同名分支存在就分别合并。
3. **发行冻结**：`release.yaml` 保持唯一的正式发行清单，三个 `*_commit` 必须是不可变 40 位 SHA，并验证与所构建源码一致；生成镜像后记录 Digest 与源代码组合。正式发版不能使用空提交字段或仅依赖浮动 `ref: dev`。
4. **版本分离**：CloudFile 产品版本（如 `v2.0.0`）、Seafile CE 版本（如 `v14.0.8-server`）、实际构建组合 ID、镜像 Tag/Digest 逐个标注；绝不把上游 CE 14、旧 CloudFile V0.9 与 V2 混为同一分支版本。
5. **历史测试隔离**：`build/v2/source-set.json` 当前固定旧的 Server/Hub overlay 提交，`v2-clean.yml` 是指定旧快照的隔离测试。不得以该工作流通过声称最新 `dev` 组合已经通过。若希望覆盖当前 V2，需另建或更新使用当前三仓固定 SHA 的集成门禁；保留原隔离测试的独立身份。
6. **发布入口**：现有三仓没有 `prod` 分支。Docker 可以在现有 `dev` 上冻结并经审查发布，也可以短暂使用 `release/v2.x.y`，但不得假设文档中的 `prod` 已存在。创建新长期 `prod` 非必需。

`release.yaml` 中用于日常开发的 `forks.*.ref: dev` 可以保留；发布与测试收据都必须记录经解析的确切提交，不能把“开发默认”误认为“发布锁”。

## 旧分支退役检查（2026-10-20 快照）

- `dev2-clean`、`dev14` 在三仓均是 `dev` 的祖先：确认引用后归档/删除，不作为新任务起点；`v2-clean.yml` 当前还将 `dev2-clean` 写在触发分支中。
- `dev2` 在三仓均与 `dev` 分叉，不得整枝合入。已有 `archive/dev2-m1-20261016` 与各仓当前 `dev2` 指向同一 SHA，仍须盘点未移植改动后清理旧别名。
- `archive/v0.9-dev-20261016` 保留为旧版来源，`feature/v09-directory-access` 不可直接合并进当前 V2。
- Hub 旧 `feature/v2-*`、`fix/v2-*` 的未合入提交及开放 PR 必须逐个核对；需要的能力重新从 `dev` 派生，不做自动批量合并或删除。
- `seafile/*`、`master`、`seahub-ce` 等上游来源按照用途保留，不因名称看起来“旧”就删除。
- 现存 `feature/local-object-staging-20261020` 三仓均从各自当前 `dev` 向前推进，原分支继续验收；未来新工作项采用带 `v2/` 的统一前缀。

旧分支清理遵循：先记录最后 SHA、PR / CI / 构建引用、上游需要保留的证据和可替代 Tag，之后再决定只读、归档或删除。GitHub 分支保护和“必须先过跨仓 CI”需要由仓库管理员或可用 ruleset 配置，单靠命名文档不会自动生效。

## 发布 ref 与门禁

现有正式镜像构建从 `release.yaml` 解析 Server/Hub refs；开发 ref 可为 `dev`，但发布前必须将解析出的 SHA 写入冻结清单。避免新增第二套常设发行事实来源。旧流程的 `CF_SERVER_REF` 和 `CF_HUB_REF` 仅用于明确的开发/联验覆盖，不能绕过发布锁。

```bash
python3 build/cloudfile_14.0/read-manifest.py release.yaml forks.cloudfile_server.ref
python3 build/cloudfile_14.0/read-manifest.py release.yaml forks.cloudfile_hub.ref
```

CE14 已存在正式发布 Tag；上游源码锚点与未 fork 组件 SHA 分开固定在 `release.yaml`。

## 能力合并门槛

能力进入 `dev` 前至少满足：

1. 开关存在于 `.env.example`、启动配置和 Hub 特性清单。**新开关默认值必须是 `false`**；已验收且不依赖第三方的能力可改为默认 `true`，需在同一变更里修正 `configuration.md` 的默认值表。
2. 开关关闭时通过 `smoke.py` 与 `baseline.py`：核心流程可用、扩展框架已加载、默认态与文档一致。这是回归检查，**不再要求与原生 CE 逐字一致**（该 P0 标准 2026-09-22 废除）。
3. 开关开启时通过专项用例和能力 E2E；“门禁文件已存在”不等于“已有成功跑次”。
4. 跨 Hub/Server 的语义由同一规格和共享用例驱动，不能只修改一侧。
5. 新增上游改动已登记；能通过扩展点实现的能力不得扩大上游修改面。
6. 部署变量、数据库变更、回滚条件和已知限制已写入专项文档。

快速检查与专项门禁入口：

```bash
./tools/run-checks.sh
./tools/verify-local.sh preflight
./tools/verify-local.sh cap <capability>
```

可用能力名以 [`../tools/verify-local.sh`](../tools/verify-local.sh) 的 `CAPABILITIES` 表为准。

## 上游改动登记

允许修改的上游文件分别登记在：

```text
docs/upstream-patches/cloudfile-server.txt
docs/upstream-patches/cloudfile-hub.txt
docs/upstream-patches/cloudfile-docker.txt
```

变更登记后运行：

```bash
./tools/check-upstream-patches.sh
```

登记清单用于发现 fork 维护面是否意外扩大，不代表某项能力已经通过运行时验证。扩展点与消费者见 [`EXTENSION-POINTS.md`](EXTENSION-POINTS.md)。
清单差异和比较环境缺失只产生警告，不再使快速检查或 CI 失败；评审时仍应确认新增 fork 维护面是否必要。

## 上游同步

1. 在受影响仓建立同一工作项的同步分支，例如 `sync/ce14/20261020`。
2. 合入或重放上游改动，逐项解决登记文件中的冲突。
3. 更新 `release.yaml` 的上游 SHA；CloudFile fork ref 仍按待验证分支显式覆盖。
4. 运行快速检查、基线门禁和受影响能力门禁。
5. 三仓评审通过后合入 `dev`；发布前将最终提交写入构建信息和清单。

跟随上游时优先复用官方实现和独立镜像。只有官方组件不满足 CloudFile 的 CE 扩展需求时，才新增协议兼容实现或替换 provider；当前边界见 [`feature-matrix.md`](feature-matrix.md)，探针过程保存在 [`history/上游复用探针-旧版.md`](history/上游复用探针-旧版.md)。

## 并发与跨仓协作

- 只有受影响仓库建立同一工作项标识的能力分支；每个 PR 写明 Server/Hub/Docker 精确 SHA、影响的契约和基线。
- 先改规格与共享用例，再同时实现 Hub 与 Server，最后更新 docker 构建/部署门禁。
- 不把多个未验收能力临时拼成发布分支；组合集成在 `dev` 上，依赖快照和既有能力的真实启用条件隔离。
  历史开关规则仅适用于保留开关的旧能力；V2 已经默认常开的 ACL/原生 Tag/Checkout 不允许人为恢复废弃开关来规避验证。
- 合并前确认能力分支不是 `dev` 的祖先，避免快进后误以为能力代码仍存在：

  ```bash
  git merge-base --is-ancestor feature/<name> dev
  ```

旧排期、历史成本计数与 ACL 分支重建过程保留在 [`history/特性分支与持续维护-旧版.md`](history/特性分支与持续维护-旧版.md)，不作为当前操作依据。
