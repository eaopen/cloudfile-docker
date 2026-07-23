# 上游已经有什么：探针结论

[BRANCHES.md](BRANCHES.md) 第八节列了三个决策探针，每个 1～2 天，结论直接改写
排期规模。这份文档是它们的归属地。

**为什么值得单独一份文档**：[FEATURES.md](FEATURES.md) 的待办 4 写着
"上游 CE 14.0 已带了 P2/P3 的一大半"。那句话如果只是一条待办，每个人动工前
都要自己重查一遍；写成结论，才能真的省下工作量。

> **探针的价值在于它可能让整段排期消失。** 反过来，**没做探针就动工，代价是
> 重写一遍上游已经开源的东西**——那不会报错，不会有冲突，只会在半年后以
> "我们为什么维护着两套属性系统"的形式出现。

| # | 探针 | 状态 | 结论 |
|---|---|---|---|
| 0 | SSO / 身份接入 | ✅ 已做 | 登录整套都在 CE 里，且无 Pro 门控。缺的只有**组织映射** |
| 1 | metadata-server 协议 | ⬜ 未做 | 决定 2.1a 是"实现一个兼容服务"还是"自研全套属性/标签" |
| 2 | OnlyOffice 门控盘点 | ⬜ 未做 | 决定 3.2 的规模，顺带给 3.1 的 Hub 侧成本定量 |
| 3 | seasearch vs meilisearch | ⬜ 未做 | 决定 2.1b 用哪个 provider |

探针 0 不在原来的三个里面——它是做簇 B 时顺手做的，而它的结论**改变了这个
特性的形状**：原计划写一个认证后端，实际只需要写组织映射。所以它被补进来，
也说明这三个不是全部，凡是"上游可能已经有了"的地方都值得先查十分钟。

---

## 探针 0：SSO / 身份接入（已做）

**问题**：特性 36 要不要自己实现一套 SSO 登录？

**做法**：直接读 fork 里的上游代码。命令都在下面，任何人可以复现。

### 结论：登录不用写，组织映射要写

CE 14.0 自带的认证方式：

| 模块 | 开关 | 说明 |
|---|---|---|
| `seahub/oauth/` | `ENABLE_OAUTH` | OAuth2 / OIDC 授权码流程，含属性映射、老用户按邮箱认领、`SocialAuthUser` 账号绑定 |
| `seahub/adfs_auth/` | `ENABLE_ADFS_LOGIN` / `ENABLE_MULTI_ADFS` | SAML 2.0，走 djangosaml2 |
| `seahub/django_cas_ng/` | `ENABLE_CAS` | CAS |
| `seahub/auth/backends.py` | `ENABLE_REMOTE_USER_AUTHENTICATION` | REMOTE_USER（反向代理鉴权） |
| `seahub/base/accounts.py` | `ENABLE_LDAP` | LDAP |
| `seahub/{dingtalk,work_weixin,weixin}/` | 各自开关 | 钉钉 / 企业微信 / 微信 |

**一处 Pro 门控都没有：**

```bash
grep -rl "is_pro_version" seahub/oauth/ seahub/adfs_auth/ seahub/django_cas_ng/ seahub/auth/
```

（输出为空。）

依赖也都在发行包里：`requests_oauthlib` 来自 `seahub/requirements.txt`
（装进 `thirdpartdir`，构建脚本没有把它 sed 掉），`djangosaml2` / `pysaml2` /
`python-ldap` 在镜像的 pip pin 里。**镜像不需要改。**

后端的挂载也是现成的，`seahub/settings.py` 在加载 `seahub_settings.py`
**之后**才决定要不要接：

```bash
sed -n '1437,1450p' seahub/settings.py    # if ENABLE_OAUTH or ...: AUTHENTICATION_BACKENDS += ...
```

所以打开 SSO 只需要往 CloudFile 配置块里写标量，**零上游改动**。

### 上游没有的：通用目录的组织映射

上游的 OAuth 只映射用户**属性**：

```bash
grep -n "OAUTH_ATTRIBUTE_MAP" -A 10 seahub/oauth/views.py   # name / contact_email / login_id / uid
```

组织归属只有企业微信和钉钉两个集成做了，用的是 `external_department` 表：

```bash
sed -n '150,170p' seahub/auth/models.py    # outer_id = models.BigIntegerField()
```

`outer_id` 是 BIGINT，**装不下通用目录的组标识**——OIDC 的组 claim 和 LDAP 的 DN
都是字符串。所以这张表不能复用，CloudFile 另建 `cf_sso_group_map`。

还有一处结构性限制值得记下：**登录断言里的 claim 拿不到**。
`seahub/oauth/views.py` 在自己内部消费 `user_info_json`，发出的
`seahub.auth.signals.user_logged_in` 只带 `request` 和 `user`：

```bash
sed -n '105,115p' seahub/auth/__init__.py
```

要拿 claim 就得改上游文件。这正是簇 B 选择"拉取而不是拦截"的第一条理由，
另外两条见 [sso-mapping.md](sso-mapping.md) 第二节。

### 对排期的影响

| | 原估 | 实际 |
|---|---|---|
| 登录 | 写一个认证后端 + 回调路由 | **0**，配置而已 |
| 组织映射 | 未单独计价 | 一个目录 provider + 编排 + 两个表 + 门禁 |
| 新增上游改动 | 0 | 0（不变） |

规模没有变小，但**变了形状**：原计划里"SSO"最大的一块（登录）消失了，取而代之
的是原计划里根本没有的一块（组织映射）。如果按原计划动工，会得到一个能登录、
但组织结构仍然要手工维护的产物——而后者才是企业提这个需求的原因。

---

## 探针 1：metadata-server 协议（未做）

**问题**：`seahub/repo_metadata/` 已经带了完整 API 与前端，且无 Pro 门控，
只缺一个闭源的 metadata-server。按
`seahub/repo_metadata/metadata_server_api.py` 的 SQL-over-HTTP 请求写一个最小
实现，原生前端能不能跑起来？

**决定**：2.1a 是"实现一个兼容服务"还是"自研全套属性/标签系统"。**量级差一个
数量级**，因为后者等于把上游已开源的前端和 API 重写一遍。

起点：

```bash
ls ../cloudfile-hub/seahub/repo_metadata/
grep -n "def " ../cloudfile-hub/seahub/repo_metadata/metadata_server_api.py
```

## 探针 2：OnlyOffice 门控盘点（未做）

**问题**：`seahub/onlyoffice/` 的 views / converter / callback / models 都在
CE 里。数清 `is_pro_version()` 里哪些是真 Pro 依赖、哪些只是商业门控。

**决定**：3.2 的规模；顺带给 3.1（文件锁的 Hub 侧）定量——
见 [EXTENSION-POINTS.md](EXTENSION-POINTS.md) 缺口 5。

起点：

```bash
grep -rn "is_pro_version" ../cloudfile-hub/seahub/onlyoffice/ \
    ../cloudfile-hub/seahub/views/file.py ../cloudfile-hub/seahub/seadoc/apis.py
```

## 探针 3：seasearch vs meilisearch（未做）

**问题**：上游 CE 14.0 已自带 seasearch 集成（bootstrap 里甚至默认启用它、
把 Elasticsearch 降为回落）。跟随上游是否比自选方案长期成本更低？

**决定**：2.1b 注册哪个 provider。检索的查询侧扩展点已经就位（特性 64），
两者都是 provider，所以这是选型问题，不是架构问题。

起点：

```bash
grep -n "SEASEARCH" -A 10 scripts/scripts_14.0/bootstrap.py
```
