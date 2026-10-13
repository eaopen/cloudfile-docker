# v0.9 目录管理与地址接口

状态：Hub 服务、HTTP 路由和管理页面已实现；原生文件浏览、字节传输和写入终判尚未完成接线，不作为 v0.9 发布验收依据。权限语义见 [目录资格契约](directory-access-v09.md)。

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

管理查询参数为 `repo_id`、`path`、`kind=dir`，可选 `limit`（1–100，默认 50）、`after`。列表返回 `items`、`next_after`；ACL/共享列表同时返回服务端配置的 `subject_provider`，用于管理页构造接收者标识。接收者使用 `type/provider/namespace/external_id`；用户 namespace 固定 `user`，部门/角色必须使用目录提供方定义的命名空间。

写接口使用 JSON。所有写请求要求 `Idempotency-Key`；修改和删除同时要求记录的强 `If-Match`/`etag`。不确定请求结果时重试原始请求和原始 key；更换内容必须更换 key。共享没有可修改的 permission，不支持 PUT。

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

`shared-directories/` 仅接收 `limit`、`after`；按当前用户、部门祖先和角色查找 `cf_dir_share`，相同目录去重，再检查当前权限、账户状态及原生生命周期。独立 ACL 不产生共享列表记录。拒绝项不返回名称；分页游标按扫描位置推进，因此可能出现空页但仍有 `next_after`。调用方应持续分页直到游标为空。

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
- 配置工厂需要可信原生生命周期 reader，并已应用 040/041 schema；未装配时新增目录接口失败关闭。此为技术依赖，不是库级共享策略或存量数据激活开关。
- 管理页使用同一套新 ACL/共享接口、条件修改及稳定请求 key；不再把目录 ACL 写入旧接口。共享默认只读，不写 ACL；删除后重试旧创建请求不会恢复共享。
- 当前证据：真实隔离 MariaDB 与 C 核心测试、HTTP 路由/参数/CSRF回归、前端交互测试及 ACL 生产 bundle 编译。身份与生命周期仍含测试夹具，真实会话及 Linux 原生读写联验未完成。
