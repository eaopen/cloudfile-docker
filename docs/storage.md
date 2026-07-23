# 存储后端（簇 H）规格与分阶段方案

簇 H 的规格，对应 Pro 的 **AWS S3 / 多存储**。配套：[pro-parity.md](pro-parity.md)、
[EXTENSION-POINTS.md](EXTENSION-POINTS.md)（缺口 4）、[FEATURES.md](FEATURES.md)、
[BRANCHES.md](BRANCHES.md)。

本文是对一份外部方案的**核对与确认**——凡"确认"的给出代码位置；凡与代码不符
或此前文档记错的，直接改正。**本轮最重要的一条改正**：S3 **不是**"1 个新增登记项"，
而是要在**核心文件服务里补齐存储驱动**。见第四节。

---

## 一、原则与范围

沿用[首要原则](BRANCHES.md#〇首要原则优先复用官方组件)：存储层**保持 Seafile 原有
模型与配置兼容，不新增独立存储服务或私有仓库格式**，S3 变量沿用官方，不造 CloudFile
私有格式。

| 模式 | 首批 | 说明 |
|---|---|---|
| 本地文件系统 | ✅ 默认 | 本地盘或容器挂载的 NFS（见第七节的 NFS 辨析） |
| 单一 S3 | ✅ 首批 | AWS S3、MinIO、Ceph RGW，及兼容 S3 API 的 OSS/COS/Wasabi 等 |
| 多存储类 | ✅ 首批 | 同一实例组合 FS + S3；原生 Ceph/Swift/Aliyun OSS 后续补 |
| 库迁移 | ✅ | 在不同存储类间迁移整个资料库 |
| IAM Role、SSE-C | ⏳ 第二阶段 | 涉及安全与兼容性，单独验证 |

---

## 二、S3 配置：沿用官方变量

```bash
SEAF_SERVER_STORAGE_TYPE=s3
S3_COMMIT_BUCKET=cloudfile-commits
S3_FS_BUCKET=cloudfile-fs
S3_BLOCK_BUCKET=cloudfile-blocks
S3_KEY_ID=...
S3_SECRET_KEY=...
S3_HOST=minio.example.com
S3_AWS_REGION=us-east-1
S3_USE_HTTPS=true
S3_USE_V4_SIGNATURE=true
S3_PATH_STYLE_REQUEST=true          # MinIO / Ceph RGW 通常需要
```

Seafile 把对象分为 **commit / filesystem / block** 三类，官方建议**分别用三个
bucket**。这三类正是下面 Go/C 对象层里 `objType` 的取值（`"commit"|"fs"|"block"`）——
不是 CloudFile 造的概念，是既有模型。

---

## 三、多存储：沿用官方机制

```bash
SEAF_SERVER_STORAGE_TYPE=multiple
```
```ini
[storage]
enable_storage_classes = true
storage_classes_file = /shared/conf/seafile_storage_classes.json
```

三种映射策略（官方语义，不改）：

| 策略 | 含义 |
|---|---|
| `USER_SELECT` | 建库时用户选择存储类 |
| `ROLE_BASED` | 按角色限制可选存储类（与打包层的角色管理相衔接） |
| `REPO_ID_MAPPING` | 按库 ID 分布 |

> **映射单位是"资料库"，不是单个文件。** 库创建后改变策略**不会自动迁移**已有数据——
> 迁移要显式走库迁移工具（见第四节 GC/迁移）。这条要写进运维文档，否则"改了策略
> 数据怎么没动"会成为支持工单。

---

## 四、代码边界（本轮核对的重点）

> **纠正 [EXTENSION-POINTS.md](EXTENSION-POINTS.md) 缺口 4 与 [BRANCHES.md](BRANCHES.md)
> "S3 比预想便宜"那条。** 那两处基于"seafobj（Python 读取侧）上游已带 S3"就判断
> S3 几乎白捡。**但 seafobj 只是 Python 读侧**（seahub 缩略图、seafevents 索引读对象），
> **不在核心文件服务的写入/服务路径上**。核心路径是 Go fileserver（14.0 的 HTTP 文件
> 服务）与 C 的 seaf-server / GC / FSCK——**这两处目前只有 FS 后端**。

实测（cloudfile-server，无 S3 后端存在）：

| 层 | 现状 | 要补什么 |
|---|---|---|
| **Go fileserver** | `fileserver/objstore/` **只有 `backend_fs.go`**（113 行）；`New()` 写死 `newFSBackend`；`option.go` 不解析 S3/multiple | `backend_s3.go`（实现 4 方法接口 `read/write/exists/stat` + S3 SDK）+ 配置解析（`SEAF_SERVER_STORAGE_TYPE`、`S3_*`）+ `New()` 后端选择 + 多存储 `storage_id` 路由 |
| **C seaf-server / GC / FSCK** | `common/obj-store.c` 写死 `obj_backend_fs_new`；只有 `obj-backend-fs.c` + 遗留 `riak`。GC/FSCK（`server/gc/gc-core.c`、`fsck.c`）经同一 `obj_store` | `obj-backend-s3.c` + `obj-store.c` 后端选择 + 多存储路由。**覆盖上传/下载/同步/历史/GC/FSCK/迁移/校验/清理** |
| **Python 读侧（seafobj）** | ✅ **本地 checkout 已核实**：`seafobj/backends/` 有 `filesystem.py`/`s3.py`/`alioss.py`/`ceph.py`/`swift.py`，`objstore_factory.py` 的 `get_s3_conf_from_env(obj_type)` 按 commit/fs/block 分别读 S3 env、含多存储 JSON。Apache-2.0，构建里已 clone | **无需 fork**——唯一白捡的一层 |
| **Hub** | 存储类相关入口受 Pro 判断门控 | **精确移除**存储功能上的 Pro 判断（同 search 的做法：只动相关接口，**不动全局 `is_pro_version()`**）+ 存储类选择/管理/状态界面 |
| **Compose** | 只有 local | `local` / `s3` / `multiple` 三套模板；凭据经环境变量或 Docker secrets |

**接口是干净的 seam，这是好消息**：Go 侧 `storageBackend` 只有四个方法，`backend_fs.go`
113 行，`backend_s3.go` 照同一接口实现即可；C 侧同理照 `obj-backend-fs.c` 的形状写。
**但它终究是"实现驱动"，不是"翻个开关"**——量级是**核心文件服务的存储驱动 + 多存储
路由**，跨 Go/C 两语言、覆盖服务/GC/FSCK/迁移全路径。这是 roadmap 里**最重**的一条
构建项，不是最轻。排期按此重新计，别按旧文档的"1 个登记项"。

> **SeaSearch、Metadata Server 各自的存储**：用 S3 时它们分别配自己的
> `S3_SS_BUCKET`、`S3_MD_BUCKET`，与 Seafile 三桶分开。它们是官方镜像，存储配置
> 各管各的，不共用 Seafile 的 commit/fs/block 桶。

---

## 五、镜像与许可边界

外部方案提到"以官方 `seafileltd/seafile-mc` 为基础构建"。**核对后要澄清一处**：

- `seafile-mc` 是 **CE 13.0** 镜像。**上游没有 CE 14.0 镜像**（[AGENTS.md](../AGENTS.md)
  的既有前提），所以 CloudFile 的 14.0 镜像**不是**基于任何官方 CE 镜像，而是
  `FROM ubuntu:24.04` **从源码构建**，套用 14.0 的版本 pin、去掉 Pro 专用部分。
- 但**意图已经满足**：CloudFile **不依赖 Pro 镜像**。官方 Pro 镜像的许可证限制
  再分发与衍生修改，所以它**只能作为"用户自行提供有效许可"的可选运行时**，
  不能作为可自由分发的 CE 默认依赖。这一点现行架构本就如此——从 CE 源码构建，
  正是为了绕开这个许可边界。

一句话：**"基于 CE、不依赖 Pro 镜像"这条已成立**；只是因为没有 CE 14.0 镜像，
落地形式是"从 CE 源码构建"而非"FROM seafile-mc"。

---

## 六、分阶段

| 阶段 | 内容 | 依赖 |
|---|---|---|
| **P0** | 单一 S3：Go `backend_s3.go` + C `obj-backend-s3.c` + 配置解析 + 后端选择；打通上传/下载/同步/历史；`local`/`s3` 两套 Compose 模板 | S3 SDK |
| **P1** | 多存储：`storage_classes` 解析 + `storage_id` 路由（Go/C 两侧）+ 三种映射策略；`multiple` 模板 | P0 |
| **P2** | 库迁移：`migrate-repo` + 校验 + 安全清理；GC/FSCK 在 S3 后端下验证 | P1 |
| **P3** | IAM Role、SSE-C：安全与兼容性单独验证 | P0 |

**P0/P2 的验收面**（存储最怕"写进去读不出/GC 误删"）：上传后立即下载校验一致；
历史版本可取；**GC 在 S3 后端下不误删活对象**（拿一个刚写入的对象跑一轮 GC 后仍在）；
FSCK 能在 S3 上跑完。这些进 `storage-e2e.yml` 能力门禁。

---

## 七、NFS 辨析：内部存储 ≠ 外部资料源

两件容易混的事，必须分开：

| | 内部 NFS 存储（本簇 H） | 挂载现有 SMB/NFS 资料源（簇 G） |
|---|---|---|
| 谁管理对象布局 | **Seafile**（就是 FS 后端跑在 NFS 挂载上） | 外部系统，Seafile 只读映射 |
| 进 repo/commit/block 模型？ | ✅ 是 | ❌ 否 |
| 协作/签入签出 | ✅ 正常 | ❌ 降级为只读、无协作、无签入签出 |

**内部 NFS 就是默认的 FS 后端**，不需要任何新代码——把 `seafile-data` 放在 NFS 挂载上
即可。**外部 SMB/NFS 源是另一回事**，属簇 G，见 [EXTENSION-POINTS.md](EXTENSION-POINTS.md)
缺口 3（融入原生库列表的产品代价）。别把两者的配置或期望混在一起。

---

## 八、产品口径

> CloudFile 存储层保持与 Seafile 原有模型和配置完全兼容，沿用官方 S3 与多存储变量，
> 不新增独立存储服务或私有格式。首批支持本地 FS、单一 S3、FS+S3 多存储与库迁移；
> 落地方式是在核心文件服务（Go fileserver 与 C seaf-server/GC/FSCK）里补齐 S3 存储
> 驱动与多存储路由，Python 读侧复用上游 seafobj。默认镜像基于 CE 源码构建，不依赖
> 受限的 Pro 镜像。
