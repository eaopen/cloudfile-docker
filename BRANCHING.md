<!-- generated-by: gsd-doc-writer -->
# CloudFile 三仓分支模型

> **用途**：规定 `cloudfile-server`、`cloudfile-hub`、`cloudfile-docker` 共用的分支、发布和上游同步规则。
> **适用版本**：CloudFile `14.0.0-cf.0`，基于 Seafile CE 14 源码重构。
> **状态**：当前有效；构建 ref 以 [`release.yaml`](release.yaml) 为准，详细门槛见 [`docs/BRANCHES.md`](docs/BRANCHES.md)。

## 分支类型

| 分支 | 用途 | 生命周期 |
|---|---|---|
| `dev` | 集成基线：扩展点、构建、部署和已验收能力；全部能力开关默认关闭 | 长期 |
| `feature/<name>` | 单个耦合能力簇 | 验收后合回 `dev` 并删除 |
| `fix/<name>` | 独立缺陷修复 | 验证后合回 `dev` 并删除 |
| `sync/upstream-YYYYMMDD` | 三仓同步上游的临时工作分支 | 同步与回归完成后删除 |

长期能力分支只用于不准备进入产品的客户定制、实验或许可证不兼容实现。能力不能长期各自分叉：构建脚本每仓只接受一个 ref，正式组合必须在 `dev` 上通过默认关闭的开关隔离和集成验证。

## 上游基线

未 fork 组件按 `release.yaml` 的 `upstream` SHA 锁定；CloudFile fork 使用 `forks` 下的 URL/ref。上游未发布 CE 14 tag，不能用 Pro tag 代替 CE 基线。

```bash
python3 build/cloudfile_14.0/read-manifest.py release.yaml forks.cloudfile_server.ref
python3 build/cloudfile_14.0/read-manifest.py release.yaml upstream.seafile_server
```

## 跟随上游

1. 三仓各自从 `dev` 创建同名 `sync/upstream-YYYYMMDD`。
2. 获取并合入对应上游分支，逐项处理已登记上游文件的冲突。
3. 更新 `release.yaml` 的上游 SHA。
4. 运行上游改动登记、快速检查、基线门禁和所有受影响能力门禁。
5. 三仓评审通过后合入 `dev`。

```bash
git fetch upstream master
git switch -c sync/upstream-$(date +%Y%m%d) dev
git merge upstream/master
./tools/check-upstream-patches.sh
./tools/run-checks.sh
```

允许修改的上游文件以 [`docs/upstream-patches/`](docs/upstream-patches/) 三份清单为准。脚本报告新增文件时，先确认无法用新增文件或现有扩展点实现，再更新清单和本文件；不能直接补登记来绕过审查。

## 合并与发布

能力合并前必须证明开关关闭时仍走原生 CE 路径，并在开关开启时通过专项门禁。跨 Hub/Server 的语义先更新共享规格和用例，再同步实现。

发布时将三个仓库的最终提交写入 `release.yaml` 的 `server_commit`、`hub_commit`、`docker_commit`，再使用同一版本 tag。未填写提交的开发清单不能当作可追溯发布记录。

历史分支事故、旧排期和过期文件清单保留在 [`docs/history/`](docs/history/)，不作为当前操作依据。
