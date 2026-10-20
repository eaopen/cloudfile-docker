[CloudFile product home / 产品总入口](https://github.com/eaopen/cloudfile) · [English](https://github.com/eaopen/cloudfile/blob/main/README.md) · [简体中文](https://github.com/eaopen/cloudfile/blob/main/README.zh-CN.md)

# CloudFile Docker

> **当前开发：GitHub 默认 `dev` = CloudFile V2**，基于 Seafile CE14。Server、Hub、Docker 三仓的 `dev` 含义一致；V0.x 和已归档的 `dev2`、`dev2-clean` 不是当前开发入口。

CloudFile Docker 负责三仓源码组装、镜像构建、部署配置、跨仓契约及发布来源记录。CloudFile Server 提供 C/Go 文件数据面与权限终判，CloudFile Hub 提供 Web、API、SSO 和功能扩展。

## 日常开发

只使用简单规则：`dev` 为主线，新功能 `feat/<功能>`，问题修复 `fix/<问题>`，文档 `docs/<主题>`，旧版本归 `archive/<历史名称>`。**不需要增加 `v2/`、日期或任务编号作为强制前缀。** 跨仓任务可同名，但只在涉及修改的仓库建立分支。详见 [BRANCHING.md](BRANCHING.md) 和 [docs/BRANCHES.md](docs/BRANCHES.md)。

**V2 当前源码 ≠ 已验证的源码组合 ≠ 已打包镜像 ≠ 已部署环境。** 跨仓联验和交付时须记录 Server、Hub、Docker 的固定 SHA 及镜像 Digest。

## V2 构建与旧版入口的区别

- [V2 源码组装及开发运行说明](build/v2/README.md)：描述 `build/v2/` 路径。`source-set.json` 是一次**固定源码快照**，不能默认它等于三个仓库最新 `dev`。
- 根目录 [`release.yaml`](release.yaml) 和 `build/cloudfile_14.0/` 保留较早版本的发布和 CE14 扩展构建方式；**不要未经核实就直接将它们用于当前 V2 `dev` 构建或部署**。
- [历史技术文档](docs/history/README.md) 仅用于追溯旧版行为。实际 V2 的授权、Tag、Checkout 等内置能力以当前 V2 代码/契约为准，不恢复旧 `CF_ENABLE_*` 参数。

**不因每次小改动重新编译。** 文档修改无需测试和构建；代码只针对受影响模块做必要检查。需要镜像或三仓真实运行验收时，在明确的集成或发布任务中选定固定 SHA，再按实际入口操作；不要把旧 CI 的成功误称为最新 V2 已验收。

## 项目仓库与参考

| 仓库 | 职责 |
| --- | --- |
| [cloudfile-server](https://github.com/eaopen/cloudfile-server) | 文件存储、底层权限、C/Go 原生文件服务 |
| [cloudfile-hub](https://github.com/eaopen/cloudfile-hub) | Web/API、SSO、目录/文件访问、可选增强能力 |
| [cloudfile-docker](https://github.com/eaopen/cloudfile-docker) | 构建、运行、部署与跨仓版本组合 |

更多资料：[开发约束](AGENTS.md) · [部署文档](docs/deployment.md) · [V2 源码组装](build/v2/README.md) · [上游改动清单](docs/upstream-patches/)。

本仓保留原上游 Seafile 组件的许可证及各自授权；请核对 [LICENSE.txt](LICENSE.txt) 和具体组件的许可证。
