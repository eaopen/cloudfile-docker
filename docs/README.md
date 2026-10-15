# CloudFile 构建与部署文档

本仓维护构建、镜像、配置、部署、升级恢复以及跨层技术契约和验证入口。产品定位、公开路线、AI 方向和专业服务统一见 [CloudFile 产品文档](https://github.com/eaopen/cloudfile/blob/main/docs/README.md)。

## 安装与运行

| 入口 | 内容 |
| --- | --- |
| [Compose](../deploy/compose/README.md)、[部署](deployment.md) | 安装、profile、升级、备份与恢复 |
| [配置](configuration.md)、[构建](docker-build.md)、[源码构建](../build/README.md) | 参数、配置生成、镜像和产物 |
| [发布清单](../release.yaml)、[能力矩阵](feature-matrix.md) | 版本引用、逐项状态、适用限制与证据 |
| [部署概览](overview.md)、[架构](architecture.md) | CE 14 基线、组件职责和数据边界 |
| [分支规则](../BRANCHING.md)、[同步说明](BRANCHES.md)、[上游贡献](upstream-contribution.md) | 兼容、源码改动登记与维护 |

## 技术专题

| 入口 | 内容 |
| --- | --- |
| [认证](features/sso-authentik.md)、[目录 ACL](acl-semantics.md)、[权限表](permission-tables.md) | 通用认证与跨层授权契约 |
| [存储](features/storage-backends.md)、[自动分库目录](features/automatic-local-storage.md)、[RustFS](features/rustfs-storage.md) | 配置、迁移和后端兼容边界；RustFS 仍需完整业务 E2E |
| [写入生命周期](fileop-lifecycle.md)、[本地应用](features/file-collaboration.md)、[设备编辑上传](device-edit-upload.md) | 写入、锁与本地工作流技术说明 |
| [搜索](features/search.md)、[标签](features/tags.md)、[审计](features/audit.md) | 索引、属性及操作事实 |
| [外部资料](features/external-sources.md)、[外部目录规划](features/external-directory-mount.md) | 来源、只读根与尚未支持范围 |
| [AI 配置](features/seafile-ai.md)、[扩展点](EXTENSION-POINTS.md)、[版本差异排查](edition-differences.md) | 可选集成与开发维护参考 |

机器可读共享用例 `acl-cases.json`、`fileop-cases.json` 及 `upstream-patches/` 登记保留原位。组件实现说明分别见 [Server](https://github.com/eaopen/cloudfile-server/blob/dev/doc/README.md)、[Hub](https://github.com/eaopen/cloudfile-hub/blob/dev/docs/README.md)、[Agent](https://github.com/eaopen/cloudfile-local-agent)、[浏览器扩展](https://github.com/eaopen/cloudfile-chrome-extension)。

## 文档边界

[路线图](roadmap.md) 仅导航到公开产品中心；[历史目录](history/README.md) 保留兼容入口，内部讨论和客户环境记录不在本仓归档。技术文档须注明适用版本，开发分支的配置不能冒充已发布兼容保证。

## 迁移与兼容参考

[扩展运行配置](../CLOUDFILE.md) · [历史资料迁移](features/local-migration.md) · [旧标签批处理](legacy-file-tags-batch.md) · [单文件编辑验证范围](../tests/e2e/EDITING_SINGLE_FILE.md)

上述技术参考按各自版本使用；命令执行前核对适用条件，不从文档存在推导当前环境已验收。
