# AGENTS.md — cloudfile-docker

> 用途：约束构建、部署、跨仓规格和上游同步工作。
> 适用版本：CloudFile `dev`，面向 Seafile CE 14 参考基线。
> 当前状态：有效；产品状态以 [`docs/feature-matrix.md`](docs/feature-matrix.md) 为准。

给在本仓库工作的 AI coding agent。人类同样适用。

## 工作方式：不使用 GSD

本项目**不采用 GSD 工作流**。不得运行 GSD 命令、创建或维护 `.planning/`、
生成 GSD 计划/总结/工作树，也不得以 GSD 产物作为交付依据。

开发按一个可验证改动一次提交的方式推进；现行能力状态与实现依据以
[`docs/feature-matrix.md`](docs/feature-matrix.md)、代码和可执行测试为准。

## 这是什么

`haiwen/seafile-docker` 的 fork，CloudFile（Seafile CE 企业扩展版）的
**构建、镜像、部署，以及跨仓规格文档的归属地**。

CloudFile 由三个仓库组成，通常并排 checkout：

```
workspace/
├── cloudfile-server/   fork of haiwen/seafile-server —— 权限终判层
├── cloudfile-hub/      fork of haiwen/seahub        —— Web/API 层
└── cloudfile-docker/   fork of haiwen/seafile-docker —— 本仓库
```

本仓库同时是**发布的归属地**：`release.yaml` 决定每次构建用哪些代码，
`BRANCHING.md` 定义三仓共用的分支模型。

## CE 14 基线：上游已发布，运行时配方以上游为准

> **曾评估退回 CE 13.0，已否决——维持 14.0**（当前结论见 [docs/overview.md](docs/overview.md)，完整决策已归档）。
> 关键事实：CloudFile 改了 C/Go 服务端，**13 和 14 都得重新编译**，于是 13.0
> "复用官方镜像"的核心收益不成立；而 14.0 已跑通、更新、迁移成本为零。

**前提在 2026-09 变了**：上游补上了 CE 14 的发布与镜像，原先是"上游没有，所以只能
从源码重构"的三条论据不再成立：

- `haiwen/seafile-server` 仍**没有 `14.0` 分支**（只有 `master`），但已有 CE tag
  `v14.0.8-server`；`haiwen/seahub` 同样有 `v14.0.8-server`（以及 `-pro` 系列）
- 上游提供 `image/seafile_14.0/`（CE 14 镜像配方，产出
  `seafileltd/seafile-mc:<version>-testing`），不再只有 13.0 CE 与 14.0 Pro

按 [BRANCHING.md](BRANCHING.md)「冲突与移植的裁决顺序」第 1 条（涉及 CE 14 的以上游为准），运行时层跟上游：

- **上游有的 pin 一个都不能少。** 比对对象是上游 CE 14 配方与 CloudFile 的
  `image/cloudfile_14.0/Dockerfile.base`——pin 都在 base 里，不在应用 Dockerfile 里。
- CloudFile 多出来的只有两类，都属于第 2 条，**不能因为上游没有就删**：编译改了
  C/Go 的服务端所需的构建工具链（valac / golang / ccache / cmake / 各类 `-dev`），
  以及自有能力与前端构建需要的 `scikit-learn`、`boto3`、Node。

```bash
# 上游 CE 14 的 pip pin 与 CloudFile base 的差集（应为空）
comm -23 \
  <(git show upstream/master:image/seafile_14.0/Dockerfile | grep -oE '[a-zA-Z0-9_.-]+==[0-9][^ ]*' | sort -u) \
  <(grep -oE '[a-zA-Z0-9_.-]+==[0-9][^ ]*' image/cloudfile_14.0/Dockerfile.base | sort -u)
```

构建方式本身不变：`image/cloudfile_14.0/Dockerfile` 仍是 CloudFile 自己写的应用层
（以自建 base 为底、装 CloudFile 编译出的发行包），`release.yaml` 仍是 ref/SHA 的
唯一真相来源。

基线跟 `upstream/master`，但不得落后于上游 CE 14 正式发布：`release.yaml` 的
`ce_anchor` 记录那次发布的源码提交，`./tools/check-ce-anchor.sh` 断言它已在被验证的
ref 上（`run-checks.sh` 已接入）。上游打新的 `v14.0.N-server` 时同步更新它。

## 目录

```
release.yaml                       构建清单：各组件的 SHA/ref、镜像名、schema 版本
BRANCHING.md                       三仓共用分支模型 + 上游改动文件清单
docs/feature-matrix.md             特性状态、来源、定位、证据和上游策略 —— 先看这个再动手
docs/BRANCHES.md                   当前分支、合并门槛与上游同步规则
docs/EXTENSION-POINTS.md           扩展点清单 × 特性关联矩阵、已知缺口
docs/upstream-patches/             各仓允许修改的上游文件登记
tools/check-upstream-patches.sh    强制登记清单不被悄悄变长
build/cloudfile_14.0/
├── cloudfile-build.sh             拉源码、按 SHA 检出、构建发行包
├── cloudfile-build.py             上游 seafile-build.py 的副本（13.0/14.0 版本完全相同）
└── read-manifest.py               读 release.yaml，不依赖 PyYAML
image/cloudfile_14.0/
├── Dockerfile.base                一次性联网构建的 CE 14 工具链/运行时基础镜像
├── base-build.sh                  构建并加载基础镜像
├── Dockerfile                     断网构建的 CE 14 应用镜像
└── docker-build.sh                禁止拉取与联网的应用镜像构建
deploy/compose/                    一键部署，含 search/office/worker/full profile
scripts/scripts_14.0/              容器内运行时脚本（上游文件，改动见下）
```

## 上游改动

| 文件 | 改了什么 |
|---|---|
| `scripts/scripts_14.0/bootstrap.py` | 写 CloudFile 配置段、建 `cf_*` 表 |
| `scripts/scripts_14.0/start.py` | 每次启动调用 `write_cloudfile_config()` |
| `.gitignore` | 忽略构建产物与部署密钥 |

其余全是新增文件，不参与合并冲突。改动这份清单时同步更新 `BRANCHING.md`。

## 两个非显而易见的设计

**配置在每次启动时重写，不是首次 bootstrap。**

`init_seafile_server()` 在 `seafile-data` 已存在时会提前返回。配置如果写在那里面，
运维改了 `.env` 里的开关重启后**什么都不会发生**——这是个很难排查的坑。
所以 `write_cloudfile_config()` 从 `start.py` 每次调用，且写的是带标记的区块
（`CF_BEGIN` / `CF_END`），重复执行幂等，运维在同一文件里的其它改动不受影响。

**建表也在每次启动时执行。**

`apply_cloudfile_schema()` 执行 `cloudfile.sql`，全部 `IF NOT EXISTS`。
必须覆盖三条路径：新装、版本升级、**既有 CE 部署切换到 CloudFile**。
最后一条不跑任何 setup 或 upgrade 脚本，能力缺表时会 fail closed 把所有人锁在外面。
基线不带任何表，文件不存在时这一步只告警并跳过。

## 铁律

**新增开关默认必须是 `false`**，`.env.example` 里也是 `false`。未验收能力默认不生效，
这是未验收能力与已发布能力之间的隔离机制。

> 修改说明（2026-09-22 产品决策）：“新增开关默认 false”不变，但**已验收且不依赖第三方的能力已改为默认 `true`**
> （DIR_ACL/AUDIT/METADATA/TAGS/FILE_PREVIEW/FILE_LOCK/CHECKOUT/FAVORITES_ID/WATCH/FILEOPS/SHARE_RESTRICT）。
> 原因：网盘是产品线主工程，已验收能力默认关闭会让交付部署逐项开开关；
> 而“全关 = 原生 CE”铁律已废除，默认关闭不再是升级成本的保证。
> 完整名单与依赖边界见 [`docs/configuration.md`](docs/configuration.md)。

**但不再要求"全关 = 原生 CE 逐字一致"**（2026-09-22 废除该 P0 标准）。CloudFile
本来就是 CE 的扩展版，基线里始终存在不受开关约束的改动——登记在
[`docs/upstream-patches/`](docs/upstream-patches/) 的兼容与安全补丁就是这类，它们
在全关时同样生效，例如 B-1 的字节通道按目标路径判定权限、标签按目标路径判定、
CE 无群组配额、SSO 建号回填 `contact_email`。拿"全关是否等于原生 CE"当验收标准，
在本仓从第一天起就不成立。升级成本可控靠的是"开关默认关闭 + 上游改动有登记清单"，
不是关闭态逐字等于 CE。

`docker-compose.yml` 里**不要给 profile 专属变量加 `:?` 必填标记**。
compose 会对整个文件做插值，与激活哪个 profile 无关，`:?` 会让默认的
`docker compose up` 直接失败。

## 验证

```bash
cd deploy/compose && cp .env.example .env && docker compose config --quiet
```
```bash
for p in search office worker full; do docker compose --profile $p config --services; done
```
```bash
python3 build/cloudfile_14.0/read-manifest.py release.yaml forks.cloudfile_hub.ref
```

完整构建（需要 Linux）：

```bash
./build/cloudfile_14.0/cloudfile-build.sh 14.0.0-cf.0
```
```bash
./image/cloudfile_14.0/docker-build.sh 14.0.0-cf.0
```

## 基线与能力的边界

```
dev       = 扩展基线 + 已验收能力，默认值见 docs/configuration.md
feature/* = 开发中的能力（一个耦合簇一条），验收后合回 dev 并删除
```

能力带着自己的规格、用例集和本地 E2E 门禁一起进 `dev`——例如 ACL 的
`docs/acl-semantics.md`、`docs/acl-cases.json`、`tests/e2e/acl_matrix.py`，
以及 `./tools/verify-local.sh cap acl`。

**能力不长期分叉**：构建脚本每个仓库只认一个 ref，两个尚未合并的能力无法一起
构建，也就无法一起交付。让能力住在 `dev` 上仍然安全，靠的是**未验收能力默认关闭**——
未验收的能力默认不生效，所以基线与能力可以共存于一条分支。（2026-09-22 之前这条
论证依赖"全关 = 原生 CE"那条铁律；该铁律废除后，隔离由"默认不生效"承担，代价是
关闭态的回归面比过去宽，见下面的门禁定位。）
论证与四条开发线的切分见 [docs/BRANCHES.md](docs/BRANCHES.md) 第一节。

**基线本地门禁是回归检查，不是"与原生 CE 等同"的证明**（`./tools/verify-local.sh`）：

1. 镜像能不能构建出来
2. 关闭态下核心流程可用（`tests/e2e/smoke.py`），且扩展机制确实装好了、
   能力确实都没启用（`tests/e2e/baseline.py`）

2026-09-22 之前第 2 条问的是"行为是否与原生 CE 一致"，现在只问"有没有把可用性
弄坏"。两半仍然缺一不可：只跑 smoke 的话，一个 `cloudfile_ext` 根本没被加载的
镜像也能通过。这类检查**不构成发布阻塞**——真正阻塞发布的是 `./tools/run-checks.sh`
以及各能力的专项门禁。

**能力门禁在本地另跑一份，各开各的开关。** 两层互不阻塞：某个能力的门禁挂了，
把它的开关留在关闭状态照样能发基线——这就是原先靠分支隔离想达到的效果，
用开关达到，而且不会带来组合爆炸。

跨层语义（同一套规则同时在 Hub 和 seafile-server 实现）必须用共享用例集驱动
两端。改语义的正确顺序：先改规格 → 再改用例集 → 最后同时改两处实现。
只改一处 = 引入漂移，而漂移在权限系统里意味着安全漏洞。

**能力分支会腐坏，跟进不是可选项。** `feature/dir-acl` 就是活的反例：它停在
基线剥离前的提交上，落后六个构建修复，那条分支上的镜像根本构建不出来；
而且它是 `dev` 的祖先，`git merge dev` 会**快进并静默删光能力代码**。
跟进前先查：

```bash
git merge-base --is-ancestor feature/<能力> dev && echo "危险：merge 会快进"
```

重建步骤见 [docs/BRANCHES.md](docs/BRANCHES.md) 第九节。

## 约定

- 代码、注释、commit message 用英文；文档（`*.md`）用中文。
- shell 脚本用 `set -e`，改完跑 `bash -n`。
- `release.yaml` 是构建的唯一真相来源。**不要把 ref 或 SHA 写死在构建脚本里**，
  加进 manifest 再用 `read-manifest.py` 读。
- 绝不提交 `deploy/compose/.env` 和 `deploy/compose/data/`（含密码与实际数据，
  已在 `.gitignore`）。
