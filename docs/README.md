# CloudFile 文档地图

CE 扩展版的规格、规划与决策。每份文档只保留**最终版本**内容；被取代但仍有价值的
推理（反转、被更正的判断）在 [历史版本/](历史版本/)。

## 框架与规划

| 文档 | 内容 |
|---|---|
| [FEATURES.md](FEATURES.md) | 全部特性清单与完成状态（✅ 已验 / 🟡 未验 / ⬜ 未做）。**先看这个** |
| [BRANCHES.md](BRANCHES.md) | 首要原则（复用官方优先）、分支模型、八个耦合簇、上游成本、排期 |
| [EXTENSION-POINTS.md](EXTENSION-POINTS.md) | 扩展点 × 特性关联矩阵，已知缺口 |
| [fileop-lifecycle.md](fileop-lifecycle.md) + [fileop-cases.json](fileop-cases.json) | **写入生命周期契约**（PREPARE / COMMITTED / ABORTED）。属基线，不属任何簇——文件锁、签入签出、OnlyOffice 写回、属性、标签、元数据跟随六个特性共同的前置 |
| [pro-parity.md](pro-parity.md) | 官方 Pro vs CE 逐项对标：哪些是"打包"（启用即可）、哪些要"构建" |
| [upstream-reuse.md](upstream-reuse.md) | 决策探针结论：上游已有什么，哪些能白拿 |

## 能力规格（一簇一份）

| 文档 | 簇 | 对应 Pro 特性 | 状态 |
|---|---|---|---|
| [acl-semantics.md](acl-semantics.md) + [acl-cases.json](acl-cases.json) | A 目录 ACL | Fine-grained folder permission | ✅ 已落地 |
| [sso-mapping.md](sso-mapping.md) | B 身份与目录同步 | Syncing LDAP/AD Users & Groups | ✅ 本机两阶段门禁与 CI 均通过；LDAP 目录源待补 |
| [audit.md](audit.md) | C 审计 | Audit Log | ✅ API、筛选与管理员页面已验收 |
| [upstream-reuse.md](upstream-reuse.md) | D 元数据与标签 | Metadata | ✅ 官方 metadata-server 已接入并通过真实 API 验收 |
| [search.md](search.md) | E 检索 | Full text search | ⬜ 方案已定 |
| [file-preview-and-edit.md](file-preview-and-edit.md) | F 协同与本地编辑 | File locking / Online editing | 🟡 OnlyOffice、文件锁与签入签出已有部分实现；尚缺生产协议兼容面与容器级 E2E |
| [external-sources.md](external-sources.md) | G 外部资料源 | SMB/NFS 外部资料源 | 🟡 阶段 2 自有只读浏览与管理入口已完成；增量扫描、原生库影子挂载与 Overlay 尚未实现 |
| [storage.md](storage.md) | H 存储 | AWS S3 / 多存储 | ✅ 已完成，并已通过完整整机验证 |
| [ai.md](ai.md) | AI | 自动属性/标签/摘要（非 Pro 表项） | ⬜ 方案已定 |

> 元数据（簇 D）默认用官方 `seafile-md-server`，规格与探针结论在
> [upstream-reuse.md](upstream-reuse.md)；各簇（含 E 检索、F 协同、G 外部源、H 存储）的
> 细项状态见 [FEATURES.md](FEATURES.md)。

## 决策记录

| 文档 | 决策 |
|---|---|
| [decision-image-baseline.md](decision-image-baseline.md) | 镜像基线维持 CE 14.0（否决退回 13.0） |

## 数据与登记

| 路径 | 内容 |
|---|---|
| [acl-cases.json](acl-cases.json) | ACL 共享用例集，同时驱动 C 与 Python 两端 |
| [fileop-cases.json](fileop-cases.json) | 写入生命周期共享用例集，同时驱动 C 与 Go 两端 |
| [upstream-patches/](upstream-patches/) | 各仓允许修改的上游文件登记（fork 成本的硬约束） |

---

## 两条贯穿全部文档的原则

1. **优先复用官方组件**（[BRANCHES.md 原则 0](BRANCHES.md)）：官方镜像/实现能用就用，
   是否开源不是首要约束；官方不满足需求时才自建，且尽量留协议 seam 以便替换。
2. **最小化上游改动**：fork 唯一的持续成本是改了多少上游文件（当前 7/35/3，
   见 [upstream-patches/](upstream-patches/)；权威值以
   `tools/check-upstream-patches.sh` 为准，这里的数字只是提醒它有代价）。
   能力只新增文件、经扩展点接线；打包类特性只写配置、不开分支。
