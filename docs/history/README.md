<!-- generated-by: gsd-doc-writer -->
# 历史文档索引

> **用途**：索引已被当前方案取代但仍需保留的决策反转、失败方案与经验记录。
> **适用版本**：历史记录涉及 Seafile CE 13/14；不得作为当前部署说明。
> **状态**：已归档、只读参考；当前结论以 `docs/` 顶层文档和 `release.yaml` 为准。

这里存放**已被最终版本取代、但仍有价值的推理与反转记录**。

正式文档（上一级 `docs/`）只保留最终结论，读起来是"现在是什么"。而"为什么是
现在这样、曾经错在哪、哪个备选被否决"这类信息不该塞进正式文档让它变成流水账——
但也不能丢，否则同一个错误会被重犯、同一个备选会被重新提出。所以放在这里。

| 原文件 | 归档时间 | 当前替代文档 | 归档原因 | 历史决策价值 |
|---|---|---|---|---|
| `docs/历史版本/修订史与教训.md` → [修订史与教训.md](修订史与教训.md) | 2026-08-11 | [项目概览](../overview.md) | 旧目录合并，内容是更正过程而非当前说明 | 有；保留误判与教训 |
| `docs/历史版本/镜像基线-13.0备选.md` → [镜像基线-13.0备选.md](镜像基线-13.0备选.md) | 2026-08-11 | [项目概览](../overview.md) | CE 13 备选已否决 | 有；避免重复提出 |
| `docs/BRANCHES.md` → [特性分支与持续维护-旧版.md](特性分支与持续维护-旧版.md) | 2026-08-11 | [分支与上游跟随](../BRANCHES.md) | 旧稿混入排期、事故和过期计数 | 有；保留分支腐坏案例 |
| `BRANCHING.md` → [BRANCHING-旧版.md](BRANCHING-旧版.md) | 2026-08-11 | [`BRANCHING.md`](../../BRANCHING.md) | 旧稿混合规则、清单和事故 | 有；保留演化过程 |
| `README.md` → [上游README-旧版.md](上游README-旧版.md) | 2026-08-11 | [`README.md`](../../README.md) | 上游通用入口未描述 CloudFile | 无 |
| `README.pro.md` → [上游README-Pro-旧版.md](上游README-Pro-旧版.md) | 2026-08-11 | [`README.md`](../../README.md) | Pro 部署入口不适用于 CE 扩展版 | 有限；仅供上游差异参考 |
| `MAINT.md` → [上游发布维护-旧版.md](上游发布维护-旧版.md) | 2026-08-11 | [部署](../deployment.md) | Seafile 6/Travis/旧 tag 流程已失效 | 有限；仅供考古 |
| `docs/FEATURES.md` → [FEATURES-旧版.md](FEATURES-旧版.md) | 2026-08-11 | [扩展能力矩阵](../feature-matrix.md) | 以编号和日期堆叠状态，含过期验证结论 | 有；保留能力演进与测试事故 |
| `docs/pro-parity.md` → [Pro-对标-旧版.md](Pro-对标-旧版.md) | 2026-08-11 | [扩展能力矩阵](../feature-matrix.md) | 外部公开不宜使用旧竞品式对标口径 | 有；保留内部产品判断 |
| `docs/upstream-reuse.md` → [上游复用探针-旧版.md](上游复用探针-旧版.md) | 2026-08-11 | [项目概览](../overview.md)、[功能矩阵](../feature-matrix.md) | 探针过程和阶段方案不再是当前使用说明 | 有；保留复用判断依据 |
| `docs/sso-mapping.md` → [SSO-组织映射-旧版.md](SSO-组织映射-旧版.md) | 2026-08-11 | [Authentik 与企业认证](../features/sso-authentik.md) | 未采用 Authentik 默认入口的统一产品定义 | 有；保留组织同步语义细节 |
| `docs/storage.md` → [存储后端-旧版.md](存储后端-旧版.md) | 2026-08-11 | [多存储与 S3](../features/storage-backends.md) | 未充分区分官方模型、CloudFile 实现和缺失的分配 UI | 有；保留实现与测试细节 |
| `docs/external-sources.md` → [外部资料源-旧版.md](外部资料源-旧版.md) | 2026-08-11 | [SMB/NFS 外部资料源](../features/external-sources.md) | 旧设计稿含阶段规划和已变化状态 | 有；保留 provider 设计过程 |
| `docs/search.md` → [检索方案-旧版.md](检索方案-旧版.md) | 2026-08-11 | [检索](../features/search.md) | 方案比较和排期过长，部分验证状态已变化 | 有；保留 SeaSearch/Meilisearch 取舍 |
| `docs/file-preview-and-edit.md` → [文件预览与协同-旧版.md](文件预览与协同-旧版.md) | 2026-08-11 | [文件协作与本地应用](../features/file-collaboration.md) | 旧稿混合需求、阶段计划和大量已替代设计 | 有；保留锁与本地应用决策 |
| `docs/ai.md` → [AI-方案-旧版.md](AI-方案-旧版.md) | 2026-08-11 | [路线图](../roadmap.md) | 只有方案，仓库无已实现能力证据 | 有；未来立项时参考 |
| `docs/decision-image-baseline.md` → [镜像基线决策-旧版.md](镜像基线决策-旧版.md) | 2026-08-11 | [项目概览](../overview.md) | 结论仍有效，但完整决策过程不属于主导航 | 有；保留为何不退回 CE 13 |

**规则**：正式文档里凡是"此前记错/更正/反转"的长篇叙述，都应压缩成一句最终结论
（必要时加一行指向这里的链接），把叙述搬到这里。
