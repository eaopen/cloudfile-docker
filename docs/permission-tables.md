# CloudFile V2 权限表与身份事实（当前 dev）

> 只描述现行 V2 / CE14。旧版本的 `cf_managed_library`、`cf_dir_admin`、`cf_managed_library_share` 和任何权限迁移账本不属于当前运行时；禁止从历史材料还原这些表。

## CE 原生事实

| 原生表/能力 | 作用 |
| --- | --- |
| `RepoOwner` | 库所有者与管理资格 |
| `SharedRepo` / `RepoGroup` | 原生用户、组整库 `r/rw` 授权 |
| `GroupUser` | 原生组的实际成员关系 |
| `VirtualRepo` | CE 兼容的虚拟库及原库路径关联，必须验证 origin |
| `Branch` / Commit / Repo | 原生文件版本、提交、库事实 |
| `FileShare` / CE 分享链接 | 原生链接证明，**不取代** CloudFile 路径 ACL |

## CloudFile 唯一五张扩展表

| 表 | 唯一职责 |
| --- | --- |
| `cf_library_storage` | 库与存储后端绑定，由原生库存储状态识别/补全 |
| `cf_dir_acl` | 目录 ACL、路径继承/覆盖和目录共享（`share_mode`） |
| `cf_sso_group_map` | 外部组织/角色到 CE 原生组的映射 |
| `cf_edit_guard` | 已启用独占编辑的当前 Guard，不存旧 Session |
| `cf_audit_event` | 当前审计事件，不追溯开发期旧记录 |

权限计算不需要“托管库”分类字段，也不需要额外库状态表。`cf_dir_acl` 中存在记录仅代表该路径/主体有显式规则。

## 授权规则

- 默认 CE 库权限为普通目录树资格；本地共享目录可在无整库资格时作为独立访问根。
- 当前目录规则持久化 `r`、`rw`、`invisible`；`none` 是内部无资格哨兵，不是持久化值。
- `inherit` 控制当前规则是否向下生效；同一主体轨道以更深有效规则覆盖祖先，跨轨道按当前 V2 求解规则执行。
- 无效主体、数据不一致或权限依赖不可用不得被解释成没有 ACL 后直接授予原生宽权限。

## 防回归

不可添加第六张 `cf_*` 业务表，不得在任何接口把 `EXISTS(cf_dir_acl WHERE repo_id=?)` 当成整库管理或文件访问拒绝条件。需要保护路径不足的旧协议时，应命名并校验具体协议的能力范围。参阅 [现行权限终判契约](permission-adjudication-contract.md)。
