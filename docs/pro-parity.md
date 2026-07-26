# Pro 对标：CloudFile 站在哪，以及"打包"还是"构建"

以 Seafile 官方 [Pro vs CE 对比](https://www.seafile.com/en/pricing/?produce=on-premises)
为基准，把每一项 Pro 独占特性映射到 CloudFile 的现状。配套：
[FEATURES.md](FEATURES.md)、[BRANCHES.md](BRANCHES.md)、
[upstream-reuse.md](upstream-reuse.md)。

## 一个贯穿全表的事实：Pro/CE 是**营销线**，不是源码线

对比页把一批特性标成 Pro 独占。但把它们逐个拉到 CE 源码里看，**大半的代码
本来就在开源仓里**——由普通的 settings 开关或纯营销门控，而**不是**
`is_pro_version()`。实测：

```bash
# 这些"Pro"特性的代码都在 CE 源码里，且不被 is_pro_version 挡：
grep -rln is_pro_version seahub/adfs_auth/ seahub/oauth/ seahub/role_permissions/ \
    seahub/two_factor/ seahub/base/accounts.py   # → 空
# LDAP 登录后端、ADFS/SAML、角色、2FA、设备远程擦除，源码俱在。
```

于是 CloudFile 的特性分成两层，**优化的第一步就是把它们分开**——因为把"翻个
开关"和"两端重写权限强制"当成同级排期，是当前 roadmap 最大的失真：

| 层 | 含义 | 成本 | 是不是一条 `feature/*` 分支？ |
|---|---|---|---|
| **打包（Package）** | 代码已在 CE 源码，只是默认关或被营销门控。启用 = bootstrap 写配置 + 可能拆个 UI 门控 | 近乎零 | **不是**。它是 bootstrap 的一段配置 + 文档清单，不该单独开分支 |
| **构建（Build）** | CE 里**没有**这个机制，需要新代码 | 真实工作量 | **是**。就是现有八个耦合簇 |

> **这直接影响"优化特性分支"**：打包层的东西**不该变成特性分支**——把 2FA 做成
> 一条分支和一个 `CF_ENABLE_*` 开关，是给一个上游 settings 开关又套一层壳。
> 分支只留给真正要写新机制的簇。打包层是一张**启用清单**，归 bootstrap 和文档。

---

## 二、逐项对标

`✅ 已完成` `🔨 构建中/待建` `📦 打包（启用即可）` `—（CE 已具备）`

### 文件与协作

| Pro 特性 | CE 源码有吗 | 归属 | 做法 | 状态 |
|---|---|---|---|---|
| Fine-grained folder permission | ❌ CE 只有库级共享 | 簇 A | **构建**：两端强制的目录 ACL | ✅ 已完成（`feature/dir-acl`） |
| Full text search | 检索路径在 CE；**seasearch 已在 CE** | 簇 E | **配置** seasearch + **精确解除搜索接口的 Pro 门**（`Search`+`public_repos_search` 两个接口，URL 影子，零上游改动，不动全局 `is_pro_version()`）；可选 meilisearch provider。完整方案 [search.md](search.md) | 🟡 P0/P1/P2 已实现，未随镜像验证 |
| Office file editing（OnlyOffice/Collabora） | ✅ `seahub/onlyoffice/` 全套 | 簇 F | **构建**：锁集成两行受 `is_pro_version` 门控，需拆 | 🔨 待探针 2 |
| File locking | ✅ RPC + `FileLocks` 表在 CE；**Hub 侧受 `is_pro_version` 门控** | 簇 F | **构建**：server 白捡，Hub 拆门控（缺口 5） | 🔨 |
| WebDAV | ✅ `seafdav`，已在 CloudFile 构建里 | — | **打包**：已具备，ACL 读写补丁已测 | ✅ 已具备 |

### 用户与身份

| Pro 特性 | CE 源码有吗 | 归属 | 做法 | 状态 |
|---|---|---|---|---|
| Authenticate against LDAP/AD | ✅ `CustomLDAPBackend`（`ENABLE_LDAP`） | 簇 B·登录半 | **打包** | 🟡 bootstrap 已接；待真实目录验收 |
| SSO with ADFS（SAML） | ✅ `seahub/adfs_auth/`，无 `is_pro` | 簇 B·登录半 | **打包** | 🟡 bootstrap 与 `xmlsec1` 已接；待 IdP/SP 证书验收 |
| SSO with Shibboleth | ✅ `adfs_auth` 的 Shibboleth 路径 | 簇 B·登录半 | **打包** | 🟡 bootstrap 已接；待可信 SP 代理验收 |
| （OAuth2/OIDC，未单列但同类） | ✅ `seahub/oauth/` | 簇 B·登录半 | **打包** | ✅ 已接（bootstrap `_settings_block_sso`） |
| **Syncing LDAP/AD Users and Groups** | ❌ CE 无后台同步（Pro 的 `ldap_sync` 在闭源 seafevents） | 簇 B·**同步半** | **构建**：这是登录之外真正缺的机制 | ✅ 通用组织映射已完成；**待补一个 LDAP 目录源** |
| Role based Account Management | ✅ `seahub/role_permissions/`，无 `is_pro` | 打包层 | **打包**：`ENABLED_ROLE_PERMISSIONS` 配置 | ✅ bootstrap 配置生成已验 |

> **簇 B 的正确切法**：登录后端（LDAP/ADFS/Shibboleth/OAuth）全是**打包**；
> 真正要**构建**的只有**目录/组同步**——而对比页恰好把
> "Authenticate against LDAP/AD" 与 "Syncing LDAP/AD Users and Groups" 分成两行，
> 印证了这条线。CloudFile 的组织映射（特性 76–88）就是那个"同步半"的通用实现；
> 补一个 `ldap` 目录源即得 Pro 同款。见 [sso-mapping.md](sso-mapping.md)。

### 安全与合规

| Pro 特性 | CE 源码有吗 | 归属 | 做法 | 状态 |
|---|---|---|---|---|
| Two factor authentication | ✅ `seahub/two_factor/` app 无条件装载，`ENABLE_TWO_FACTOR_AUTH` | 打包层 | **打包** | ✅ bootstrap 配置生成已验 |
| Remote Wipe | ✅ `seahub/utils/devices.py` `mark_device_to_be_remote_wiped` + 管理端点 | 打包层 | **打包** | ✅ 已具备 |
| Audit Log | Server `repo-update` → seafevents `Activity` 已覆盖提交差异 | 簇 C | `CF_ENABLE_AUDIT` API 与系统管理员 UI | ✅ 已验收 |
| Antivirus Integration | ❌ 镜像已**主动剥离** clamav；扫描在 server/pipeline 侧 | 新增·server 侧 | **构建**：这是"缺失机制"里唯一较重的一项 | 🔨 未开始 |

### 存储与扩展

| Pro 特性 | CE 源码有吗 | 归属 | 做法 | 状态 |
|---|---|---|---|---|
| AWS S3 / 多存储 | Go fileserver 已有 S3 + `RepoStorageId` 路由，Docker 已生成官方配置，seafobj 读侧已有 S3；**C 主服务、GC、FSCK 仍只有 FS** | 簇 H | 补 C `obj-backend-s3.c`、C 多存储路由、创建映射入口与迁移/GC/FSCK E2E。**非"1 登记项"**，见 [storage.md](storage.md) | ⚠️ 部分完成 |
| 属性 / 标签 / 多视图（未单列，Pro 的 metadata） | 前端+API+投喂管线全在 CE；官方 metadata-server 提供存储引擎 | 簇 D | **打包**：接官方兼容服务并复用 CE 前端/API | ✅ 属性与标签真实 API 已验收 |

---

## 三、优化后的结论

**打包层（近零成本，企业准入门槛，应最先做）**——**它们不是分支，是一段
bootstrap 配置 + 一张启用清单**：

- LDAP/ADFS/Shibboleth 登录：写上游已读的 `ENABLE_LDAP` / `ENABLE_ADFS_LOGIN`
  等，做法与已落地的 OAuth（`_settings_block_sso`）完全一致。
- Role-based account management：`ENABLED_ROLE_PERMISSIONS`。
- 2FA：`ENABLE_TWO_FACTOR_AUTH`。
- Remote wipe：设备管理端点已在，确认前端入口未被藏起即可。
- WebDAV：已具备。
- AI 按需能力（标签/摘要/描述/OCR）：`ENABLE_SEAFILE_AI` + 官方 seafile-ai 组件
  （不在 Pro 对比表里，但代码在 CE、无 Pro 门控；需自备 LLM）。**自动**那一环
  是构建，见 [ai.md](ai.md)。

> 铁律不变：这些也必须**默认关**，开关全关 = 原生 CE。区别只是它们的开关是
> **上游自己的 settings**，CloudFile 只负责在 bootstrap 里从 `.env` 写进去，
> 不新增 `CF_ENABLE_*`、不开分支。

**构建层（真正的耦合簇，才是 `feature/*` 分支）**：

| 簇 | Pro 对标项 | 现状 |
|---|---|---|
| A 目录 ACL | Fine-grained folder permission | ✅ 已完成 |
| B 身份·同步半 | Syncing LDAP/AD Users and Groups | ✅ 已完成（待补 LDAP 源） |
| C 审计 | Audit Log | ✅ 已完成 |
| D 元数据 | 属性/标签/多视图 | ✅ 官方 metadata-server 已接入；移动/重命名关联待做 |
| E 检索 | Full text search | 🟡 已实现（配 seasearch 默认 + meilisearch 可切换），未随镜像验证 |
| F 协同 | Office editing + File locking | 🔨 拆 `is_pro` 门控（缺口 5 / 探针 2） |
| H 存储 | AWS S3 | 🔨 1 登记项 |
| **新** | **Antivirus** | 🔨 **唯一"缺失机制"里没归簇的**——server 侧扫描管线，镜像已剥离 clamav |

**对特性分支的三条具体优化**：

1. **打包层移出分支计划。** LDAP 登录、ADFS、Shibboleth、角色、2FA、远程擦除、
   WebDAV 不开分支、不加 `CF_ENABLE_*`——它们是 bootstrap 的配置面。把它们当
   分支排期，是给上游开关又套一层壳。
2. **簇 B 更名为"身份与目录同步"**，明确"登录=打包、同步=构建"。已落地的组织
   映射就是同步半；补一个 `ldap` 目录源就与 Pro 的 LDAP/AD 同步对齐。
3. **Antivirus 是"缺失机制"里唯一还没归属的一项**，且是其中较重的（server 侧、
   镜像已剥离 clamav）。要么单列一簇，要么并入 H 之外的一条"server 侧管线"线。
   落地前先做一次门控盘点（同 OnlyOffice 探针 2 的做法）。

**一句话**：Pro 对比表里约一半的特性，CloudFile **已经有了源码，只差启用**；
真正要写的机制集中在已有的耦合簇里，外加一个 Antivirus。先清打包层拿下企业
准入，再按四条开发线推进构建层。
