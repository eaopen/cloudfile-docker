# 版本差异说明：Seafile CE / Seafile Pro / CloudFile

> 用途：回答"某个行为或接口，是 CE 本来就这样、Pro 才有、还是 CloudFile 改的"。
> 适用版本：Seafile CE 14 参考基线，CloudFile `dev`。
> 当前状态：有效；所有结论必须能落到代码、git diff 或可执行验证。新案例按第六节格式登记。

## 1. 三个版本是什么关系

| 版本 | 是什么 | 代码边界 |
|---|---|---|
| Seafile CE | 上游开源版（haiwen/seahub、seafile、seafobj 等） | `cloudfile-*` 三仓的基线；工作区 `seafile/`、`seafobj/` 是上游依赖检出 |
| Seafile Pro | 官方商业版，**闭源**。一部分"Pro 特性"代码其实就在 CE 源码里（由 settings/角色权限控制），一部分真在闭源组件里（如 seafevents 的 `ldap_sync`） | 本工作区没有 Pro 源码；Pro 侧信息只能来自官方对比页与文档映射，**不能拿 Pro 二进制行为当依据** |
| CloudFile | CE 14 fork（`cloudfile-server` + `cloudfile-hub` + `cloudfile-docker`） | 新增能力全部走 `CF_ENABLE_*` 开关，**全关 = 原生 CE 行为**（P0 铁律）；对上游文件的改动以 `upstream-patches/*.txt` 登记为准 |

能力状态与来源的权威文档：[功能矩阵](feature-matrix.md)（定位列：Pro 平替 / CE 补强 / 新应用扩展）。
"Pro 逐项对标"的方法论见历史档 [Pro-对标-旧版](history/Pro-对标-旧版.md)——它教怎么把 Pro 卖点映射回 CE 源码，
但其状态列已归档，当前状态一律以功能矩阵为准。

## 2. 一次判定的总模型：三层门控

任何"行为不符合预期"，先归到下面某一层，再谈改法：

| 层 | 机制 | 怎么识别 | 证据位置 |
|---|---|---|---|
| ① CE 原生默认 | 上游 settings + 角色权限（role permissions） | 视图代码里的 `request.user.permissions.can_xxx()`；默认值在 `DEFAULT_ENABLED_ROLE_PERMISSIONS` | [`role_permissions/settings.py`](../../cloudfile-hub/seahub/role_permissions/settings.py)、[`base/accounts.py`](../../cloudfile-hub/seahub/base/accounts.py) |
| ② CE 内的 Pro 门控 | `is_pro_version()` / `IS_PRO_VERSION`，按 license 开 | grep 即得全部点（命令见下节）；命中则该能力属 Pro 范畴 | 功能矩阵对应行的"上游策略" |
| ③ CloudFile 扩展 | `CF_ENABLE_*`（默认 False）；影子端点；登记过的上游文件改动 | [`cloudfile_ext/features.py`](../../cloudfile-hub/cloudfile_ext/features.py)；改动登记 [`upstream-patches/`](upstream-patches/cloudfile-hub.txt) | [功能矩阵](feature-matrix.md)、[Hub 能力矩阵](../../cloudfile-hub/docs/CAPABILITIES.md) |

两个经常反直觉的事实：

- **Pro/CE 是营销线，不是源码线**。ADFS/SAML、OAuth2/OIDC、角色管理、2FA、远程擦除等
  "Pro 卖点"的代码就在 CE 仓里，并没有被 `is_pro_version` 挡住——在 CE 上写对 settings 就能用。
- **角色权限默认值经常是"罪魁"**。很多"是不是 Pro 才行"的体感，其实是 `can_xxx: False`
  的默认角色权限（第①层），与版本无关，改配置即可。

## 3. 特性差异怎么查

| 想知道 | 看哪里 |
|---|---|
| 某能力当前状态、来源、是不是 Pro 平替 | [功能矩阵](feature-matrix.md)（唯一真相，勿引用归档文档的状态列） |
| Hub/Web 层某开关背后 CE 复用了什么、Hub 新增了什么 | [Hub 能力矩阵](../../cloudfile-hub/docs/CAPABILITIES.md) |
| 某 Pro 独占特性在 CE 源码里到底有没有 | [Pro-对标-旧版](history/Pro-对标-旧版.md) 的逐项映射 + 自己 grep 验证 |
| CloudFile 相比上游改了哪些文件 | [`docs/upstream-patches/*.txt`](upstream-patches/cloudfile-hub.txt)（强制登记清单） |

代码级命令：

```bash
# CE 源码里全部 Pro 门控点——"Pro 比 CE 多了什么"的代码级清单
grep -rn "is_pro_version\|IS_PRO_VERSION" cloudfile-hub/seahub --include="*.py"

# 验证"营销线 vs 源码线"：这些 Pro 卖点目录里没有 is_pro 门控 → CE 本来就有
grep -rln is_pro_version cloudfile-hub/seahub/adfs_auth/ cloudfile-hub/seahub/oauth/ \
    cloudfile-hub/seahub/role_permissions/ cloudfile-hub/seahub/two_factor/

# CloudFile 开关全集（默认全 False）
grep -n "CF_ENABLE" cloudfile-hub/cloudfile_ext/features.py
```

## 4. API 差异怎么查

1. **CloudFile 专属端点**：`/api/v2.1/cloudfile/*`（用户）与 `/api/v2.1/admin/cloudfile/*`（管理员），
   全表（方法、认证、开关）在 [`cloudfile-hub/docs/API.md`](../../cloudfile-hub/docs/API.md)。
   功能关闭时这些端点 404 或不注册。
2. **影子/解锁端点**：CloudFile 在原生路由上注册的 shadow（如 `/api2/search/` 解开上游 Pro gate、
   外部源的 `/api/v2.1/repos/*` 影子）。开关关闭时回落上游原生行为。
3. **上游 API 是否被 CloudFile 改动**：先查登记清单，再用 git 比对
   （`seahub/api2/views.py` 等文件同时存在上游代码与 fork 改动，必须按函数/类粒度看）：

   ```bash
   cd cloudfile-hub
   BASE=$(git merge-base HEAD upstream/master)          # fork 分叉点
   git diff $BASE...HEAD --stat -- seahub/api2/views.py # 某上游文件是否被本 fork 改过
   # 类/函数粒度比对（以 PubRepos 为例）：
   diff <(git show upstream/master:seahub/api2/views.py | sed -n '/^class PubRepos/,/^class [A-Z]/p') \
        <(sed -n '/^class PubRepos/,/^class [A-Z]/p' seahub/api2/views.py)
   ```

   结论只有两种：diff 为空 = 原生上游代码，行为差异在第①/②层找；
   diff 非空 = 必须能在 `upstream-patches/*.txt` 里找到登记，登记都没有 = 未登记改动（需要处理）。
4. **运行时探测部署形态**（集成侧判别 CE vs CloudFile）：

   ```text
   GET /api/v2.1/cloudfile/features/
   ├── 200          → CloudFile（响应含全部 CF_ENABLE_* 开关与 provider）
   └── 404/不存在   → 纯 CE
   ```

## 5. "行为和预期不一样"排查流程

1. **定位实际调用的端点**：浏览器 Network 面板或 seahub/nginx 访问日志，拿到方法 + 路径 + 状态码。
   不要凭前端页面猜接口。
2. **读该端点视图代码，列出门控点**：角色权限 `can_xxx()`、`is_pro_version()`、`CF_ENABLE_*`、
   registry 权限钩子（`check_folder_permission` 会串起所有已注册权限检查）。
3. **对照部署配置**：`.env` 的 `CF_ENABLE_*`、`seahub_settings.py` 的 CF 区块与
   `ENABLED_ROLE_PERMISSIONS`、相关角色权限默认值。
4. **归层（四选一）**：
   - A. CE 原生默认行为（上游就这样）→ 按上游文档/角色权限调整配置；
   - B. CE 内 Pro 门控（`is_pro_version`）→ 查功能矩阵该能力是否被 CloudFile 解锁及开关名；
   - C. 配置未开（`CF_ENABLE_*` 或上游 settings）→ 开关打开即得；
   - D. CloudFile 改动 → 必须能在 `cloudfile_ext/` 或 upstream-patches 登记里找到代码；
     **找不到就回到 A/B 重新验证，不要停在"应该是 CloudFile 改的"**。
5. **登记结论**：把端点、门控点、归层、git diff 结论按第六节格式补进本档，供下一个人直接命中。

## 6. 案例：创建公共资料库，得到的却是私人资料库

**问题原文**：创建公共资料库的底层 API 没变，换成 CloudFile 创建的就是私人资料库不是公共
资料库，CloudFile 这块是不是改了底层逻辑？

**结论：没有改。** 创建公共资料库的全部相关代码与上游 haiwen/seahub 零差异；"变成私人库"
只有下面两种真实原因。

### 证据链

1. **端点与门控**：公共资料库 = "inner pub repo"。创建端点是 `POST /api2/repos/public/`
   （[`api2/views.py` `PubRepos.post`](../../cloudfile-hub/seahub/api2/views.py)，约 L1399），
   第一步就是 `request.user.permissions.can_add_public_repo()`，不满足直接 403——
   该端点**不会**把公共库"降级"建成私人库。
2. **权限判定**（[`base/accounts.py:373`](../../cloudfile-hub/seahub/base/accounts.py)）：
   `CLOUD_MODE`（默认 False）且非 MULTI_TENANCY → False；`is_staff`（管理员）→ 恒 True；
   否则查角色权限 `can_add_public_repo`。
3. **上游默认值**：[`role_permissions/settings.py:33`](../../cloudfile-hub/seahub/role_permissions/settings.py)
   里 default 角色的 `can_add_public_repo` 就是 **False**；`git show upstream/master` 同值。
   这是上游 Seafile 的默认行为，普通用户默认不能建公共库，与 CloudFile 无关。
4. **git 证据**：`PubRepos` 类、`base/accounts.py`、`role_permissions/settings.py`、
   `api2/endpoints/shared_repos.py` 与 upstream/master diff 全部为空（命令见第四节）。
5. **前端一致**：公共资料库页"新建"按钮由 `canAddPublicRepo` 控制渲染
   ([`pages/shared-with-all/index.js`](../../cloudfile-hub/frontend/src/pages/shared-with-all/index.js)，
   值来自 `seahub/views/__init__.py` 注入的 `pageOptions`)。权限关闭时入口整个不出现。

### 两种真实原因与处理

| 原因 | 怎么判定 | 处理 |
|---|---|---|
| A. 调用的是通用建库端点 `POST /api2/repos/`（或前端"我的资料库"新建）——它**定义上就是私人库** | 看访问日志实际打的端点 | 公共库必须显式调 `POST /api2/repos/public/`；对已有库设公开走 share 接口（`api2/endpoints/shared_repos.py`，同样受 `can_add_public_repo` 门控）。API 客户端（含 eap 集成）改调公共库端点即可 |
| B. 用户角色没有 `can_add_public_repo` 权限（上游默认普通用户关闭） | 管理员账号能建、普通用户 403/无入口，即此项 | 放开角色权限（见下） |

放开方式（二选一，重启 seahub 生效）：

```python
# seahub_settings.py——写在 CF 区块之外，属运维自有改动，不会被启动重写覆盖
ENABLED_ROLE_PERMISSIONS = {'default': {'can_add_public_repo': True}}
```

```bash
# 或 CloudFile 部署 .env——bootstrap 每次启动翻译写入 CF 区块
CF_ROLE_PERMISSIONS_JSON={"default": {"can_add_public_repo": true}}
```

注意：`CLOUD_MODE=True`（默认 False）且未开 `MULTI_TENANCY` 时，`can_add_public_repo`
对所有人 False，调角色权限也救不回来——先确认部署没用云模式。

## 7. 常见疑问速查

| 症状 | 门控点 | 归层 | 依据 |
|---|---|---|---|
| 建库得到私人库不是公共库 | `can_add_public_repo` + 端点选择 | ① CE 原生 | 本档案例一 |
| `/api2/search/`、`/api/v2.1/published-repo-search/` 403 | 上游 Pro gate；CloudFile 由 `CF_ENABLE_SEARCH` 解锁 | ②→③ | 功能矩阵检索行、API.md 搜索节 |
| `monitored-repos` 403 | 上游 `is_pro_version` gate；`CF_ENABLE_WATCH` 放开 | ②→③ | API.md 监控节 |
| 组织群组接口 `quota`/`parent_group_id` 恒为 0 | `organizations/api/address_book/groups.py` 的 `is_pro_version()` | ②（CloudFile 未解锁） | grep 可复核 |
| `storage_id` 建库不生效 | `is_pro_version() and ENABLE_STORAGE_CLASSES` 门控，且 CE fork C RPC 无 `storage_id` | ② + 已知缺口 | [storage-backends.md](features/storage-backends.md) |
| 分享链接创建 403 / 匿名访问旧链 404 | `CF_ENABLE_SHARE_RESTRICT` 开启后的管控行为（默认关 = 原生 CE） | ③ | [share-restrict.md](features/share-restrict.md) |
| 目录权限不生效或被拒 | `CF_ENABLE_DIR_ACL`；规则读取失败 fail closed（收紧） | ③ | [acl-semantics.md](acl-semantics.md) |
| 上传/保存被 423 | `CF_ENABLE_FILE_LOCK`/`CF_ENABLE_CHECKOUT` 的锁租约 | ③ | [fileop-lifecycle.md](fileop-lifecycle.md) |

## 8. 维护约定

- 新案例登记到第六节，必须带：端点/函数路径、门控点、归层结论、git diff 结论；速查表加一行索引。
- 本档**不复制**功能矩阵的状态列——能力状态以 [feature-matrix.md](feature-matrix.md) 为唯一真相，避免两处漂移。
- "Pro 平替"是内部目标分类；对外表述遵守 [overview.md](overview.md) 的口径，不使用"完全替代/完全兼容"。
