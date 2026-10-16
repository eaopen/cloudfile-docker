# M1 精简新装 Schema（已撤回的未发布草案）

> 本文为未发布实验的历史记录，不能作为 V2 安装说明。该草案依赖旧运行框架，已退出交付候选；不得据此启用或发布。V2 新装表需重新逐项审核原生替代与必要性。

`dev2` 提供显式选择的 `m1` 新装模式。它只初始化干净的 CloudFile 配置，不迁移或恢复旧扩展历史，不删除 Seafile 原生表、Repo、共享、版本、对象数据或物理存储绑定。已有运行环境不会因升级镜像或修改环境变量而自动切换模式。

## 表与职责

新装共 **13 张 `cf_*` 表**：

| 用途 | 表 |
| --- | --- |
| 两项核心事实 | `cf_library_storage_key`、`cf_dir_acl` |
| 身份与会话 | `cf_sso_group_map`、`cf_oidc_session`、`cf_oidc_logout_fence` |
| 当前执行、幂等与审计依赖 | `cf_background_job`、`cf_policy_request`、`cf_audit_event`、`cf_event_outbox` |
| 原生共享发布对账 | `cf_library_share_revision`、`cf_library_share_ledger` |
| 安装校验 | `cf_schema_migration` |
| 暂留的原生安全边界 | `cf_managed_library` |

`cf_managed_library` 暂留的原因是当前 C/Go 原生访问与最终提交仍读取该边界；它不是待迁移的历史配置。新 M1 凭据 `101_m1_native_boundary` 被两端明确识别；不伪造旧 `032` 迁移已执行。最后一条 ACL 删除后仍保留保护标记，不能把该库重新暴露给旧访问入口。缺表、缺凭据、索引漂移均拒绝访问。

不创建 `cf_dir_admin`、`cf_dir_share`、`cf_managed_library_share`、独立 CloudFile Tag、资源侧写、搜索或 Agent/编辑表。M1 目录内容规则仍由一套 `cf_dir_acl` 执行，目录管理委派归外部系统。原生库设置、管理员及共享清单继续复用既有 CE/CloudFile 读取 API；此模式不增加库管理 API，也不意味着外部系统已认领任何已有库。

## 新装与开发配置重建

全新部署在 Compose `.env` 显式设置：

```dotenv
CLOUDFILE_FRESH_SCHEMA_PROFILE=m1
CF_ENABLE_FILEOPS=false
CF_ENABLE_EXTERNAL_SOURCES=false
CF_ENABLE_SEARCH=false
CF_ENABLE_FILE_LOCK=false
CF_ENABLE_CHECKOUT=false
CF_ENABLE_LOCAL_APP=false
```

兼容默认仍为 `legacy`，便于现有开发实例继续工作。M1 的单用户成员模式在 `CLOUDFILE_POLICY_CONFIG_JSON` 中必须设为 `membership_mode=subject_ttl`，见 [身份契约](identity-v2.md)。未配置外部身份时普通 CE 核心仍可独立使用。

安装意图在 CE 创建数据目录之前持久化。首次成功后保存 `.cloudfile-schema-profile`，重启沿用该值；DDL 失败保留 pending 标记并阻断启动，下一次按同一模式重试。M1 启动跳过旧扩展 bootstrap DDL，防止每次重启把删掉的表重新建回。

开发环境可以丢弃旧 CloudFile 配置后重来；本批不提供自动清空、跨版本转换或历史恢复工具。对已有 Seafile 数据目录，仅设置上述变量不会重建数据库。显式重建时保留 CE 表、实际文件与 `cf_library_storage_key`，准备干净的扩展配置与安装标记后，额外设置 `CLOUDFILE_INITIALIZE_M1_SCHEMA=true`。它只触发 M1 初始化，不清表、不迁移旧数据，也不删除 `seafile-data`；数据库仍有旧扩展表时会拒绝初始化。成功后关闭此初始化开关。

独立数据库开发可直接执行 `python3 -m cloudfile_extensions.schema apply --profile m1`；这是数据库层入口，不自动变更已有部署的安装标记。运行时会从 SQL 凭据识别 M1；不能让文件系统标记、Hub、Server 与 Fileserver 使用不一致的模式或版本。

M1 模式拒绝启用需要缺失表的旧扩展 fileops、外部源、搜索和编辑/Agent 等运行时；原生 CE 文件操作与原生 Tag/预览继续复用。不要把禁用扩展 dedup 视为受保护上传、下载或所有旧客户端的运行验收。

## 验证边界

`test_m1_schema.py` 使用临时 MariaDB/Redis，验证表清单、重试、校验漂移、原生库/共享/版本/Storage Key 行不变、UID 建号和成员投影、ACL 发布审计及保护标记。Directory/IdP 与生命周期读取仍是适配器测试。

Server 的 C 门禁编译生产边界函数，使用 SQL 凭据/故障夹具；Go 门禁另外在真实临时 MariaDB 上验证 CE-only、受保护库、缺凭据和坏索引。以上不等于完整 CE14 镜像编译或真实文件字节验收。

跨仓 `dev2.yml` 持续执行这些检查。完整 M2 仍需真实用户、原生库发现/显式绑定、旁路 SSO、三类授权场景、文件最终提交及回滚联验。
