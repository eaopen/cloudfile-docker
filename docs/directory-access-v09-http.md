# v0.9 目录管理与地址接口

> 历史记录，非当前 V2 契约。文中旧 managed marker、Resource/Intent、委托与旧授权路由已退役；当前实施以 [权限终判契约](/docs/permission-adjudication-contract.md) 和现行源码为准。


状态：目录管理、发现、地址解析和目录分页 API 已实现，新增目录访问下载/上传预检查与原生 scoped 终判已接通；管理界面已统一编辑 ACL 权限与共享开关。完整发布验收仍需真实身份 HTTP 及制品验证。权限语义见 [目录资格契约](directory-access-v09.md)。

## 接口

统一前缀：`/api/v2.1/cloudfile/extensions/authorization/v1/`。复用已有认证会话、CSRF、请求级身份准备与数据库连接。调用方不能指定当前操作人。返回 `Cache-Control: no-store`，错误包含 `code`、`message`、`request_id`。

| 路径 | 方法 | 用途 |
| --- | --- | --- |
| `directory-rules/` | GET、POST | 查询或新增目标 ACL |
| `directory-rules/{id}/` | PUT、DELETE | 按版本修改或撤销 ACL |
| `directory-admins/` | GET、POST | 查询或新增目录管理授权；无管理 UI |
| `directory-admins/{id}/` | PUT、DELETE | 按版本修改或撤销管理授权 |
| `directory-shares/` | GET、POST | 查询或新增目标共享接收者 |
| `directory-shares/{id}/` | DELETE | 撤销共享，不删除 ACL |
| `shared-directories/` | GET | 当前身份的共享目录分页列表 |
| `directory-address/` | GET | 当前身份的目录位置解析及有效浏览根 |
| `directory-entries/` | GET | 当前权限过滤后的原生目录分页 |
| `directory-scope/list/` | POST | 管理范围内的 ACL、共享或管理员记录分页 |
| `directory-scope/revoke/` | POST | 对显式记录集合按版本原子撤销 |

管理查询参数为 `repo_id`、`path`、`kind=dir`，可选 `limit`（1–100，默认 50）、`after`。列表返回 `items`、`next_after`；ACL/共享列表同时返回服务端配置的 `subject_provider`，用于管理页构造接收者标识。接收者使用 `type/provider/namespace/external_id`；用户 namespace 固定 `user`，部门/角色必须使用目录提供方定义的命名空间。

写接口使用 JSON。所有写请求要求 `Idempotency-Key`；修改和删除同时要求记录的强 `If-Match`/`etag`。不确定请求结果时重试原始请求和原始 key；更换内容必须更换 key。兼容 shares 路由不支持 PUT；修改权限或共享模式使用 directory-rules PUT。

共享创建示例（UUID 替换为实际库标识）：

```json
{
  "reference": {"repo_id": "00000000-0000-4000-8000-000000000001", "path": "/项目A", "kind": "dir"},
  "value": {
    "path": "/项目A",
    "subject": {"type": "user", "provider": "directory", "namespace": "user", "external_id": "employee-001"}
  }
}
```

目录管理员 value 在相同主体格式基础上增加 `kind=dir`、`permission=manage`、`inherit`。库管理员可授予非根目录管理权；目录管理员只能在其覆盖范围内配置 ACL/共享，再委派必须严格位于自己授权根的下级。非继承管理权不能授予整个子树的共享/ACL。管理权不授予内容读取权。

## 共享发现与地址解析

`shared-directories/` 仅接收 `limit`、`after`；按当前用户、部门祖先和角色查找 `cf_dir_acl` 中 `share_mode=1` 的记录，相同目录去重，再检查当前权限、账户状态及原生生命周期。关闭共享的 ACL 不产生共享列表记录，也不提供无库访问资格。拒绝项不返回名称；分页游标按扫描位置推进，因此可能出现空页但仍有 `next_after`。调用方应持续分页直到游标为空。

`directory-address/` 接收 `repo_id`、`path`、`kind=dir`，可选 `shared_root`。普通地址按实际资格确定可访问根；共享入口提交 `shared_root` 时必须命中当前有效共享，不能借参数扩大访问。成功结果示例：

```json
{
  "reference": {"repo_id": "00000000-0000-4000-8000-000000000001", "path": "/项目A/设计", "kind": "dir"},
  "root_path": "/项目A",
  "initial_path": "/项目A/设计",
  "permission": "r"
}
```

该结果是当前请求的位置和权限诊断，不能充当后续文件访问凭据。后续读写必须再次裁决；URL 不带授权 token，也不创建共享记录。以太客负责共享列表页面及 URL 路由。

## 状态与验证边界

- `400`：非法字段、重复参数、游标或幂等 key；`403`：无管理/内容资格；`409`：key 与原请求内容冲突；`412`：版本冲突；`428`：缺少版本条件；`503`：身份、生命周期或运行时依赖不可用。
- 配置工厂需要可信原生生命周期 reader，并已应用 042 schema；未装配时新增目录接口失败关闭。此为技术依赖，不是库级共享策略或存量数据激活开关。
- 管理页使用同一套新 ACL/共享接口、条件修改及稳定请求 key；不再把目录 ACL 写入旧接口。兼容共享新建默认写入只读 ACL，已有 ACL 保留权限；删除后重试旧创建请求不会恢复共享。
- 当前证据：隔离 MariaDB/C 核心、HTTP 参数/路由/CSRF 测试，以及 Linux Server 构建和真实 RPC/文件字节联验通过。原生联验使用真实目录历史，但身份、主体与会话为可信夹具；真实 OIDC HTTP 和制品验收仍未完成。

## 目录分页与范围撤销

`directory-entries/` 参数与地址解析一致，另接收 `limit=1..100`、`after`。返回 `items[{reference,name,permission}]`、`head_id`、`next_after`。游标绑定不可变 commit；目录版本变化返回 409，调用方重新开始分页。不可见项不泄露名称，空页可能有后续游标。共享入口每次带 `shared_root`，服务端复核当前共享；URL 或分页游标本身不授予资格。

范围查询 POST 示例：

```json
{"reference":{"repo_id":"00000000-0000-4000-8000-000000000001","path":"/项目A","kind":"dir"},"domain":"shares","limit":50}
```

`domain` 仅允许 `shares`、`acl`、`admins`。查询覆盖目标及路径分隔符下的后代，返回 `items`、`next_after`；续页在 body 带 `after`。要求覆盖整个范围的管理权，避免精确管理权扩大为子树管理。POST 查询也要求 CSRF，但不需要幂等 key。

撤销在同一 reference/domain 上提交 `items:[{"id":"实际记录UUID","etag":"\"实际版本UUID\""}]`（1–100 项）及 `Idempotency-Key`。客户端先分页展示影响记录，再明确选择撤销项；没有隐式全删或授权链级联。任一版本不匹配返回 412，越界返回 403，整个批次回滚。成功逐项记录审计，重试原请求返回相同结果；撤销 shares 永远不删 ACL。目录管理员不能借批量接口删除自己或上级的管理授权。

正常库取流票据和单文件上传/更新接口保持原有库资格预检查。新增目录访问接口复用取流与发布实现，以目录资格预检查，并在原生票据签发、消费和 Branch 发布时重新裁决。共享按同一 ACL 提供 r/rw，单文件创建还必须有父目录写权限。结构性 mkdir/delete/rename/move/copy 尚未开放受控发布 API，旧入口保持管理库拒绝；不能把 rw 理解为这些操作已交付。

## 原生回归运行

在隔离 Linux 环境构建当前 Server 后执行：

```sh
CF_NATIVE_SERVER_BINARY=/absolute/path/to/seaf-server \
CF_NATIVE_ACL_LIB_DIR=/absolute/path/to/server/.libs \
bash tests/e2e/native_directory.sh
```

脚本仅启动专用数据库、Redis、Server 和 fileserver，退出时销毁测试容器，日志与 JSON 证据保留在报告目录。`CF_NATIVE_BACKEND` 可指定本地依赖制品，`CF_NATIVE_REPORT_DIR` 可指定证据路径。原生身份映射及会话是测试夹具，不能作为真实登录验收。

详细测试结果及限制见 [本批验证记录](directory-access-v09-validation.md)。

## 入口隔离（2026-10-13）

既有管理接口 `directory-rules/`、`library-rules/`、`effective-permission/` 使用原有 DirectoryManagement/DirectoryPolicyService；是否装配生命周期 reader 不再切换既有管理机制。v0.9 新增管理和目录访问路由显式选择 DirectoryService。既有用户委托及普通浏览/资源 API 保持原机制。

正常库入口要求库资格；目录入口要求已开启共享且生命周期有效的 ACL 提供无库资格。两类入口最终复用同一套 ACL 核心、账户、屏障、当前身份、路径、库只读和撤权检查；共享使用同一 ACL 记录。

取流与单文件写入前缀为 `/api/v2.1/cloudfile/extensions/identity/v1/`：

| 正常库访问（保持原行为） | 新增目录访问 | 方法 |
| --- | --- | --- |
| `read-tickets/` | `directory-access/read-tickets/` | POST JSON，operation=view/download |
| `manual-upload/` | `directory-access/manual-upload/` | POST multipart，单文件创建 |
| `manual-update/` | `directory-access/manual-update/` | POST multipart，单文件更新 |

新旧接口的业务参数、会话、CSRF、配额、版本与审计要求相同。客户端通过路由选择入口，不能在旧接口 body 中加入权限模式字段。仅新增入口由可信服务器装配原生 `directory_access=true` 条件；这是内部入口区分，不是共享配置或授权事实。原生条件本身不授予权限，仍必须当前有效的 ACL/共享资格。普通本地会话、用户委托和 Agent 接入不因此开放无库权限。

共享入口先请求 shared-directories，再以返回目录为 shared_root 调用 directory-address/directory-entries；后续文件读取/写入使用新增 directory-access 路由。目录地址直达也可使用新增路由，URL 本身不生成资格。每个文件请求均按目标路径复核权限，不能访问未授权父目录或兄弟目录。

统一 ACL 接口新增可选整数 `share_mode`（0/1）；非根目录可开启，库根和文件不得开启。新建省略时为 0，替换省略时保留已有值；界面新增目录规则默认选择 1。响应包含 share_mode 和由服务端生成的 lifecycle_ref，客户端不得提交生命周期证据。shares 接口作为同一 ACL 的兼容投影，共用 id/revision/etag；关闭共享只清除模式和证据，删除 ACL 则同时删除共享。

## 多认证会话证明（2026-10-15）

`read-tickets/` 与 `directory-access/read-tickets/` **同时接受原生 OIDC 会话和 Authentik 旧 OAuth
浏览器会话**，客户端不需要额外参数、专用下载地址或不同的 API 前缀。Hub 按服务器端会话后端
（`_auth_user_backend`）选择会话类型，不读客户端协议提示；两种会话都必须通过各自的签名会话
校验、当前账户状态和 `Profile.login_id` 业务身份绑定，才能得到同一 `context.userId`。

票据条件里携带 Server 可在签发与每次消费时复核的原生会话证明，二者互斥：

| 认证方式 | 条件字段 | Server 复核 |
| --- | --- | --- |
| 原生 OIDC | `oidc_session`（`scope_hash`/`subject_hash`/`sid_hash`/`authenticated_at`/`session_key`） | `cf_oidc_session` 精确行、`cf_oidc_logout_fence`、`django_session` 存活 |
| 旧 OAuth 浏览器会话 | `browser_session`（`session_key`） | `identity_database` 中未过期的 `django_session` 行（登出即删行） |

两者都复用同一套 v0.9 scoped 终判、账户/业务身份锁、屏障与库资格检查；会话证明本身**不授予**
任何权限，只证明"这条票据属于当前仍有效的登录会话"。票据一次性使用，消费后再按同一证明复查
每个传输分块。不允许由 Hub 伪造 OIDC 会话、为某一种认证新增专用下载路由，或以省略会话证明的
方式放宽 Server 终判。旧受管库下载兼容例外（`CloudFileAllowLegacyManagedReads`）与本次适配无关，
历史下载入口全部迁移验证完成后才能删除。
