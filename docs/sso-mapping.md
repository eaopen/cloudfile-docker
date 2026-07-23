# SSO 与组织映射语义

簇 B（特性 36）的规格。配套：[FEATURES.md](FEATURES.md)（特性状态）、
[EXTENSION-POINTS.md](EXTENSION-POINTS.md)（扩展点）、
[upstream-reuse.md](upstream-reuse.md)（上游已有什么）。

实现：`cloudfile-hub/cloudfile_ext/sso/`。门禁：`tests/e2e/sso_matrix.py` +
`.github/workflows/sso-e2e.yml`。

---

## 一、这个能力做什么，不做什么

**登录不归它管。** Seafile CE 14.0 自带 OAuth2/OIDC（`seahub/oauth/`）、
SAML（`seahub/adfs_auth/`）、CAS、LDAP、REMOTE_USER，**全部没有 Pro 门控**。
再写一套等于永久维护一条与 fork 里已有实现平行的登录路径。

CloudFile 只补上游没有的两件事：

| | 归属 | 位置 |
|---|---|---|
| 登录 | **上游** | `seahub/oauth/` 等，CloudFile 只是把 `.env` 翻译成它读的设置 |
| 配置 | CloudFile | `bootstrap.py` 的 `_settings_block_sso()`，每次启动重写 |
| **组织映射** | CloudFile | `cloudfile_ext/sso/`，本文档其余部分 |

上游对用户**属性**（昵称、联系邮箱、login id）有映射，对**组织归属**没有——
除了企业微信与钉钉那两个集成，而它们的 `external_department.outer_id` 是
BIGINT，装不下通用目录的组标识（OIDC 的组 claim、LDAP 的 DN 都是字符串）。

---

## 二、拉取，不拦截

```
┌──────────────┐   周期拉取（cf-worker）        ┌─────────────┐
│  企业目录     │ ←───────────────────────────  │  sso_       │
│ （LDAP/OA/   │   webhook 推送（自有路由）      │  directory  │ ← provider
│   IdP/自研）  │ ────────────────────────────→ │  provider   │
└──────────────┘   登录后单人刷新（可选）        └──────┬──────┘
                                                      │ 写入
                                                      ▼
                                          ┌───────────────────────┐
                                          │ ccnet 组 + 成员        │
                                          │ cf_sso_group_map 记录  │
                                          │ 哪些组是我们建的        │
                                          └───────────┬───────────┘
                                                      │ 只读
                        ┌─────────────────────────────┼─────────────────┐
                        ▼                             ▼                 ▼
                     共享                          目录 ACL            配额
```

**为什么不从登录断言里读组 claim**——这个想法反复会被提出来，所以写下三个理由：

1. **拿不到，除非改上游。** seahub 的 OAuth/SAML 视图在自己内部消费断言，
   发出的 `user_logged_in` 信号只带 `request` 和 `user`。要拿到 claim 就得改
   `seahub/oauth/views.py`，而这个 fork 的成本模型就是"改了几个上游文件"。
2. **claim 只描述刚登录的那个人。** 组要**完整**才有用——没法把资料库共享给
   "周二以来登录过的那部分成员"。
3. **它把 IdP 放到登录路径上第二次。** IdP 慢则登录慢；IdP 的组服务挂了，
   成员关系就在有人正要干活的那一刻是错的。

代价是**最终一致**：目录改了，到 CloudFile 生效有延迟。webhook 能把延迟压到
秒级，纯周期拉取则取决于 `CF_SSO_SYNC_INTERVAL`。**这是本设计唯一真正的妥协**，
必须写进客户对接文档。

与目录 ACL 规则来源（[EXTENSION-POINTS.md](EXTENSION-POINTS.md) 第五节）是
同一个形状，理由也一样。

---

## 三、编排语义

`cloudfile_ext/sso/reconcile.py`，无 Django、无数据库，可单独测。

输入：目录快照、`cf_sso_group_map` 里的既有映射、这些组当前的成员。
输出一个**计划**（create / rename / add / remove / unmap），先算完再执行。

### 铁律 1：只碰自己建的组

一个组在 `cf_sso_group_map` 里，当且仅当它是同步建出来的。管理员手工建的组
**永远不会**被改名、清空或加人。

这不是礼貌问题：Seafile 的组**拥有资料库**，同步若"收编"了一个已有的组，
等于把一整个目录的人加进一批没人打算共享的数据里。

### 铁律 2：被管理的组里，成员就是目录说的那些

映射的含义就是这个。若改成"合并"，就再没有任何办法把人移出去。

例外只有一个：**组的创建者永远不会被移除**。Seafile 的组需要有主，而目录里
通常不会列出这个服务账号——不保护它的话，第一次同步就把自己踢出去，第二次
就管不了这些组了。

### 铁律 3：离开目录的组只解除映射，不删除

它可能拥有资料库、被共享进来。解除映射是可逆的，删除不是——**一个同步 tick
永远不该有能力做这个决定**。管理接口的 DELETE 同理，只动映射。

### 铁律 4：计划会被整体拒绝

危险的失效不是某个成员错了，而是**目录调用成功但返回了空**：token 过期、
端点改名、代理用 200 回了个空 body。按字面理解，空快照的意思是"所有组现在都空了"，
同步会忠实地把每个被管理的组清空——静默地，日志里还是 200。

于是两道闸门，都在编排层，因此都可测：

| 闸门 | 条件 | 理由 |
|---|---|---|
| 空快照 | 快照为空且已有映射 | "目录真的没有组"和"调用失败"在这里长得一模一样，而其中一种理解会毁数据 |
| 删除比例 | 单次删除超过被管理成员的 `CF_SSO_MAX_REMOVAL_RATIO`（默认 50%） | 正常的目录变动是渐进的；一个 tick 掉一半人是坏掉的数据源，不是重组 |

都是**拒绝**，不是告警。"大部分成功"的同步会把部署留在一个没人选择、
也没人能描述的状态里。

真要做一次大重组：把 `CF_SSO_MAX_REMOVAL_RATIO` 留空以取消上限，做完再设回去。

### 无法解析的成员

目录里的登录串要先解析成 Seafile 的**身份**（`cloudfile_ext/identity.py`，
Seafile 14 之后身份与邮箱是两回事）。解析不了的成员被**丢弃并记名**在同步报告里，
不会被当成"这个人不在组里"而触发删除——推广期间账号还没建是正常的，
但一直解析不了意味着目录和 Seafile 对"人是谁"的认识不一致，这必须看得见。

---

## 四、触发方式

| 方式 | 延迟 | 说明 |
|---|---|---|
| 周期任务 | `CF_SSO_SYNC_INTERVAL`（默认 600s） | cf-worker 跑。**这是契约**，其余都是在它之上减少延迟 |
| webhook | 秒级 | `POST /api/v2.1/cloudfile/sso/directory-webhook/` |
| 管理接口 | 立即 | `POST /api/v2.1/admin/cloudfile/sso/sync/` |
| 登录后单人刷新 | 立即，仅该用户 | 目录 provider 支持按人查询时才有；失败静默 |

**webhook 忽略请求体。** 接受"哪些组变了"等于让一个不走会话认证的调用方指定
要改哪些组；这个接口的语义只有"现在去重读目录"，改动仍然全部来自我们自己发起的
那次连接。签名用 `CF_SERVICE_SSO_DIRECTORY_SECRET`，与出站调用同一套 HS256——
**没配 secret 时这个接口直接不存在**（404），因为那时没有任何办法把目录服务和
网络上的其他人区分开。

**登录后刷新只处理已存在的组**，不建新组：从一个人的视角建组只会建出一个
半空的组。

---

## 五、配置

全部经 `.env`，见 [deploy/compose/.env.example](../deploy/compose/.env.example)。

| 变量 | 作用 |
|---|---|
| `CF_ENABLE_SSO` | 总开关。关掉 = 原生 CE，一个字节都不写 |
| `CF_SSO_OAUTH_*` | 填给上游的 OAuth2/OIDC 登录。留空 `CLIENT_ID` 则完全不碰登录 |
| `CF_PROVIDER_SSO_DIRECTORY` | `static` / `external-service` / 留空（不做映射） |
| `CF_SSO_GROUP_OWNER` | 同步所建组的属主。**必填**，不猜 |
| `CF_SSO_SYNC_INTERVAL` | 周期同步间隔（秒） |
| `CF_SSO_MAX_REMOVAL_RATIO` | 删除比例上限，留空取消 |
| `CF_SSO_DIRECTORY_STATIC` | `static` 源的组定义（JSON） |
| `CF_SERVICE_SSO_DIRECTORY_{URL,SECRET}` | `external-service` 源的地址与签名密钥 |

`CF_SSO_GROUP_OWNER` 没有默认值是有意的：随手选一个（"第一个管理员"）会把所有
同步出来的组悄悄挂在碰巧排在最前的那个账号上，那个账号一旦被删，所有组跟着动。

`CF_PROVIDER_SSO_DIRECTORY` 留空是**合法部署**——"用上游的 OAuth 登录，别动我的组"。

### 目录源

**`static`**：组写在配置里。适合组织结构小而稳定、且本来就由写 compose 文件的
人掌握的部署，也是能力门禁用的源（不需要再起一个服务就能跑通整条链路）。
它不是桩：它就是"目录即配置文件"这件事的完整实现。

**`external-service`**：两个 GET，都不在请求路径上：

```
GET <url>/groups               -> {"groups": [{external_id, name, members}]}
GET <url>/users/<login>/groups -> {"groups": ["eng", ...]}     # 可选
```

第二个可以不实现（返回 404），代价只是登录后刷新失效，等下一次周期同步。
超时、重试、签名、失败策略全部来自 `cloudfile_ext/external_service.py`。

**没有实现的源不注册。** 选了一个不存在的名字会以 `UnknownProvider` 显式失败，
而不是解析成一个空目录——空目录看起来是"没配组"，不是"这个源没做"。
同理由见 `cloudfile_ext/acl/sources.py`。

---

## 六、接口

| 方法 | 路径 | 权限 |
|---|---|---|
| `GET` | `/api/v2.1/admin/cloudfile/sso/sync/` | 管理员。上次同步时间/结果；`?dry_run=true` 额外给出下一次的计划 |
| `POST` | `/api/v2.1/admin/cloudfile/sso/sync/` | 管理员。立即同步 |
| `GET` | `/api/v2.1/admin/cloudfile/sso/group-map/` | 管理员。列出被管理的组 |
| `DELETE` | `/api/v2.1/admin/cloudfile/sso/group-map/?external_id=…` | 管理员。**只解除映射** |
| `POST` | `/api/v2.1/cloudfile/sso/directory-webhook/` | HS256 签名。未配 secret 时 404 |

**没有面向普通用户的接口。** 成员关系归目录决定，给用户一个能改它的接口，
下一次同步就会把改动撤销——那比不提供更糟。

干跑（`dry_run`）默认不做：它会调外部目录，而一个每次被打开都去戳第三方的
状态页会跟着第三方一起挂。

---

## 七、验收

`tests/e2e/sso_matrix.py`，**两个阶段，中间改 `.env` 并重启**：

| 阶段 | 目录 | 验什么 |
|---|---|---|
| 1 | `eng=[A,B]`、`sales=[B]` | 建组、成员落地、幂等、干跑、未配 secret 时 webhook 不存在 |
| 2 | `eng=[A]`，`sales` 消失 | B 被移出 eng；A 仍在（防"整组被清空"也算通过）；sales 解除映射但**组还在**；管理员手工解除映射同样不删组 |

两阶段是必要的：**只加不删的同步在阶段 1 里全绿**，而"离职的人还留在组里"是
这套东西唯一真正危险的失效方式——它没有任何症状，直到有人发现前同事还看得见
资料库。重启这一步顺带也在测"改了 `.env` 重启是否生效"，那是这套部署踩过的坑。

编排本身另有 14 项单元测试（`cloudfile_ext/sso/tests/test_reconcile.py`），
五个变异全部被捕获；目录源 12 项（`test_directory.py`）。2026-07-24 已从本地
`feature/sso` 构建镜像并通过这套两阶段矩阵；CI 仍待跑一次。

---

## 八、已知边界

- **组是平的。** 目录快照里没有父子关系，所以建出来的是普通组，不是有层级和
  配额的部门。要做部门需要先扩展目录契约，届时再定。
- **不建用户。** 同步只处理组成员关系；账号仍由登录时创建（上游的
  `OAUTH_CREATE_UNKNOWN_USER`）或由管理员创建。目录里有、Seafile 里没有的人，
  会作为"无法解析"出现在同步报告里。
- **不处理组织（multi-tenant org）。** `ccnet_api.create_org_group` 这条路径
  没有接。单组织部署不受影响。
