# CloudFile 当前分支与跨仓规则

> **当前唯一开发版本**：`cloudfile-server/dev`、`cloudfile-hub/dev`、`cloudfile-docker/dev` 均为 **CloudFile V2**，Seafile CE14 仅指上游基线。完整规范见 [BRANCHING.md](../BRANCHING.md)。

## 简单分支

| 名称 | 用途 |
| --- | --- |
| `dev` | 唯一当前 V2 开发主线 |
| `feat/<功能>` | 新功能 |
| `fix/<问题>` | 修复 |
| `docs/<主题>` | 文档 |
| `archive/<历史名称>` | 历史只读快照 |

不强制追加 `v2/`、日期或 Issue ID，不新增 `dev2`、`dev3`。旧版 `dev2-clean`、`dev2` 已归档并移除原名，V0.x 历史代码不可直接整枝合入 `dev`。已有在途老命名分支无需改名，按具体 PR 审查后处理。

## 跨仓只锁提交，不增加管理分支

三仓使用同一开发分支语义。单仓工作只在一仓开分支，跨仓工作可同名，但联验/发布必须固定 Server、Hub、Docker 三个 Commit SHA 及上游基线，不能只因分支名一致就认定兼容。

`release.yaml` 属于现存旧版发布配方；`build/v2/source-set.json` 是某次固定的 V2 组装快照，可能落后于最新 `dev`。不要混用这些版本事实，不得把历史源码测试当作当前 V2 联验成功。发布时核对实际构建入口、固定 SHA 和镜像 Digest，**无需建立固定的 release/prod 长期分支**。

## 按修改范围验证

**文档修改不编译、不测试、不构建镜像。** 小范围源码修改只做真正受影响的检查，完整编译/镜像/E2E 在明确集成或发布时按需进行。API、权限、文件读写或数据库契约改动不能因已有其他测试通过就跳过必要的相关验证。

## 其他

Seafile 上游源码引用、已归档历史分支均不是日常开发主线；需要移植时另行审查。优先复用 CE 原生能力；确需修改上游文件请核对 [上游改动登记](upstream-patches/)。旧功能开关和旧 Schema 不得绕过 V2 的原生授权、Tag 与 Checkout 约束。

本文件和根目录 [BRANCHING.md](../BRANCHING.md)共同描述同一套简单规则；遇到其他旧文档矛盾时，以当前 `dev`、代码事实和本规范为准。
