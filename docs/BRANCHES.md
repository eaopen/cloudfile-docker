<!-- generated-by: gsd-doc-writer -->
# 分支与上游跟随

> **用途**：定义 CloudFile 三仓当前有效的分支类型、合并门槛、发布 ref 与上游同步规则。
> **适用版本**：CloudFile `14.0.0-cf.0`，基于 Seafile CE 14 源码重构。
> **状态**：当前有效；实际发布 ref 以 [`../release.yaml`](../release.yaml) 为唯一真相。
> **边界**：CE 提供上游基线；CloudFile 维护扩展点、能力和门禁；官方/第三方组件的版本、许可证与可用性独立管理。

## 当前模型

CloudFile 的三个仓库通常并排 checkout，并使用同一分支语义：

```text
cloudfile-server   权限终判、C/Go 数据面
cloudfile-hub      Web、API、后台任务
cloudfile-docker   构建、镜像、部署与跨仓规格
```

只使用两类开发分支：

| 类型 | 命名 | 生命周期 | 内容 |
|---|---|---|---|
| 集成基线 | `dev` | 长期 | 已验收能力、扩展点、构建与部署；所有能力开关默认关闭 |
| 能力分支 | `feature/<name>` | 临时 | 单个耦合能力簇；验收后合回 `dev` 并删除 |

客户定制、实验性或许可证不兼容且不准备进入产品的实现，才允许长期保留独立分支。历史分支存在性不能从文档推断，应直接执行 `git branch -a`。

## 发布 ref

`release.yaml` 是构建唯一真相。当前清单默认从 CloudFile fork 的 `dev` 构建；本地验证可用 `CF_SERVER_REF`、`CF_HUB_REF` 临时覆盖，不能把 ref 或 SHA 写死进构建脚本。

```bash
python3 build/cloudfile_14.0/read-manifest.py release.yaml forks.cloudfile_server.ref
python3 build/cloudfile_14.0/read-manifest.py release.yaml forks.cloudfile_hub.ref
```

上游未发布 CE 14 分支或 CE 14 tag，因此未 fork 组件必须在 `release.yaml` 中锁定提交 SHA。当前基线结论见 [`overview.md`](overview.md)，完整决策过程在 [`history/`](history/README.md)。

## 能力合并门槛

能力进入 `dev` 前至少满足：

1. 开关存在于 `.env.example`、启动配置和 Hub 特性清单，默认值均为 `false`。
2. 开关关闭时通过 `smoke.py` 与 `baseline.py`，证明原生 CE 路径正常且扩展框架已加载但未启用。
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

1. 在三仓建立同名同步分支，例如 `sync/upstream-YYYYMMDD`。
2. 合入或重放上游改动，逐项解决登记文件中的冲突。
3. 更新 `release.yaml` 的上游 SHA；CloudFile fork ref 仍按待验证分支显式覆盖。
4. 运行快速检查、基线门禁和受影响能力门禁。
5. 三仓评审通过后合入 `dev`；发布前将最终提交写入构建信息和清单。

跟随上游时优先复用官方实现和独立镜像。只有官方组件不满足 CloudFile 的 CE 扩展需求时，才新增协议兼容实现或替换 provider；当前边界见 [`feature-matrix.md`](feature-matrix.md)，探针过程保存在 [`history/上游复用探针-旧版.md`](history/上游复用探针-旧版.md)。

## 并发与跨仓协作

- 三仓使用同名能力分支，提交说明标明受影响仓库和共享契约。
- 先改规格与共享用例，再同时实现 Hub 与 Server，最后更新 docker 构建/部署门禁。
- 不把多个未验收能力临时拼成发布分支；组合集成在 `dev` 上、由默认关闭的开关隔离。
- 合并前确认能力分支不是 `dev` 的祖先，避免快进后误以为能力代码仍存在：

  ```bash
  git merge-base --is-ancestor feature/<name> dev
  ```

旧排期、历史成本计数与 ACL 分支重建过程保留在 [`history/特性分支与持续维护-旧版.md`](history/特性分支与持续维护-旧版.md)，不作为当前操作依据。
