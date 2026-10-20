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
- `build/v2/source-set.json` 是其中一次固定 CE14/V2 源码快照；内部 `overlay_commit` 可能早于最新 `dev`，不能仅凭文件名推断为当前 HEAD。
- 根目录 `release.yaml` 及 `build/cloudfile_14.0/` 保留较早扩展版发布配方与证据；在确认它们的有效源码组合前，**不得直接用其浮动 `ref: dev` 发布当前 V2**。
- 真正构建/交付时，须明确 Server、Hub、Docker 的具体 Commit SHA、上游 CE 源码基线与镜像 Digest；历史 V2-clean CI 成功不代表最新 `dev` 已联验。

## 不扩大改动范围

优先复用 Seafile CE14 的原生行为与官方依赖，不因同步上游或小修引入平行框架；原生补丁及不可绕过的安全逻辑须记录在 [docs/upstream-patches/](docs/upstream-patches/)。

V2 内置 ACL、CE 原生 Tag 和已安装 Guard 的 Checkout 不应重新受旧版 Feature Flag 控制；可选 Meilisearch、SSO、Office 等外部组件通过真正的连接与依赖判断。不要恢复旧 `v2_acl_enabled` 或把 CloudFile 设计成“所有开关关闭就等于原生 CE”。

**本项目不使用 GSD。** 不自行生成 GSD 工件、修改外部账号/配置、覆盖现有 DEV/PROD 数据或静默改变运行容器。代码变更按当前任务最小范围推进，非必要完善项留待确认。

## 省时的验证规则

**纯文档变更不编译、不跑测试、不构建镜像，也不部署。** 小范围代码改动优先检查受影响路径、复用已验证的证据；全量 C/Go/前端构建、三仓联验及镜像发布只在明确必要的阶段或发布任务开展。不要因一次文档提交自动要求全仓编译。

不要提交 `deploy/compose/.env`、任何真实凭据、密钥、持久数据卷或镜像构建产物。文档中文，代码和 commit message 英文；上游既有风格优先。
