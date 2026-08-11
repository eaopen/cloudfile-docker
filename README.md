<!-- generated-by: gsd-doc-writer -->
# CloudFile Docker

> **用途**：提供 CloudFile 的源码构建、镜像、Compose 部署、发布清单与跨仓规格入口。
> **适用版本**：CloudFile `14.0.0-cf.0`，基于 Seafile CE 14 源码重构。
> **状态**：当前有效；发布组件 ref 与版本以 [`release.yaml`](release.yaml) 为唯一真相。

CloudFile Docker 面向需要在 Seafile CE 14 基础上部署企业扩展能力的开发和运维团队；本仓不承载 Seahub 或 seaf-server 业务实现，而是负责把三个 CloudFile 仓库构建、打包并部署为可验证的系统。

本仓同时是 CloudFile 跨仓项目文档的权威入口。当前架构、部署、配置、能力状态、路线图和
上游贡献建议统一维护在 [`docs/`](docs/README.md)；代码、配置、测试与 `release.yaml` 的证据
优先于规划文档，历史稿不作为当前功能说明。

## 项目组成

| 项目 | 职责 | 文档入口 |
|---|---|---|
| `cloudfile-server` | Seafile Server fork；权限终判、写入生命周期和存储扩展 | [`../cloudfile-server/doc/README.md`](../cloudfile-server/doc/README.md) |
| `cloudfile-hub` | Seahub fork；Web/API、扩展注册和能力界面 | [`../cloudfile-hub/docs/README.md`](../cloudfile-hub/docs/README.md) |
| `cloudfile-docker` | 构建、镜像、部署、跨仓规格、文档与发布清单 | [`docs/README.md`](docs/README.md) |
| `cloudfile-local-agent` | 本地查看与编辑的 Native Messaging Host | [`../cloudfile-local-agent/README.md`](../cloudfile-local-agent/README.md) |
| `cloudfile-chrome-extension` | 浏览器与本地 Agent 之间的受限桥接 | [`../cloudfile-chrome-extension/README.md`](../cloudfile-chrome-extension/README.md) |
| `seafile`、`seafobj` | 上游依赖检出，不属于 CloudFile 扩展能力实现 | 各上游仓库 README |

## 边界

- **复用 Seafile CE**：资料库、同步、WebDAV、分享、预览，以及 CE 源码中已有的 LDAP/SAML/OIDC、OnlyOffice、metadata 和 AI 接口。
- **CloudFile 新增**：扩展注册、目录 ACL、组织映射、审计、可替换检索、多存储、外部资料源、写入生命周期，以及对应构建和门禁。
- **外部组件**：MariaDB、Redis、Caddy、SeaSearch、Meilisearch、Metadata Server、seafile-ai、OnlyOffice、SeaDoc 和对象/文件存储；其许可证、容量、备份和可用性由部署方负责。

上游未发布 CE 14 分支、tag 或镜像，因此 CloudFile 按 [`release.yaml`](release.yaml) 锁定源码并自建 CE 14 发行包和镜像。当前结论见 [`docs/overview.md`](docs/overview.md)，完整决策过程已归档。

## 快速部署

```bash
git clone https://github.com/eaopen/cloudfile-docker.git
cd cloudfile-docker/deploy/compose
cp .env.example .env
```

修改 `.env` 中的主机名、管理员密码和数据库密码，然后：

```bash
docker compose config --quiet
docker compose up -d
docker compose logs -f cloudfile
```

所有 `CF_ENABLE_*` 默认关闭。可选 profile、能力开关、TLS、数据目录和备份边界见 [`deploy/compose/README.md`](deploy/compose/README.md)。

## 从源码构建

需要 Linux 或 Docker：

```bash
./build/cloudfile_14.0/build-in-docker.sh 14.0.0-cf.0
./image/cloudfile_14.0/docker-build.sh 14.0.0-cf.0
```

构建依赖、ref 覆盖和产物位置见 [`build/README.md`](build/README.md)。

## 验证

```bash
./tools/run-checks.sh
./tools/verify-local.sh preflight
```

完整基线构建与整机回归：

```bash
./tools/verify-local.sh
```

专项能力门禁使用 `./tools/verify-local.sh cap <capability>`；支持的能力名以脚本的 `CAPABILITIES` 表为准。

## 文档

- [`docs/README.md`](docs/README.md)：当前文档地图与阅读顺序。
- [`docs/overview.md`](docs/overview.md)：产品定位、上游策略与仓库边界。
- [`docs/architecture.md`](docs/architecture.md)：系统组件、控制面和数据面。
- [`docs/deployment.md`](docs/deployment.md)：部署形态与生产边界。
- [`docs/configuration.md`](docs/configuration.md)：环境变量与配置语义。
- [`docs/feature-matrix.md`](docs/feature-matrix.md)：CE 复用、CloudFile 新增、外部组件与验证状态。
- [`docs/history/README.md`](docs/history/README.md)：失效方案和旧流程索引。

开始部署前阅读 [`docs/deployment.md`](docs/deployment.md) 和
[`docs/configuration.md`](docs/configuration.md)。判断能力是否可用时，以
[`docs/feature-matrix.md`](docs/feature-matrix.md) 中的状态、限制和证据为准。

## 许可证

本仓沿用 [Apache License 2.0](LICENSE.txt)。各上游源码、官方二进制镜像和第三方组件仍受各自许可证约束。
