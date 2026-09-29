# cf-import：独立的受控单向导入工具

`tools/cf-import` 与现有 `cf-migration` 并行；它不启动或修改 seaf-cli，也不修改
`cf-migration` 容器、状态或暂存副本。`cf-migration` 仍用于已验证的空库海量初始化；
`cf-import` 使用 CloudFile/Seafile 原生上传 API 处理指定目录和后续增量。

## 当前实现

- `create` 保存本地任务配置；`check` 扫描来源并生成新增、修改、删除候选计划；
  `plan` 查看计划；`apply --exclusive` 单向上传新增和修改；`status` 查看本地状态。
- 来源支持只读本地目录 `local:///绝对路径`，或使用 Filestash 目录列表/文件读取
  API 的 `filestash://稳定别名/目录`。Filestash 别名由管理员约定，仅用于任务身份，
  不是 Filestash 自带的 mount ID。FileStash 来源逐文件流式读入任务目录下的临时文件，
  上传时按块发送，不把整个来源复制到暂存目录。
- 首次导入要求目标库中的指定目录不存在或为空，可把指定来源目录映射到库内目录。
  后续 `check` 根据上次已应用的清单计算增量，并要求资料库 HEAD 与上次导入一致；
  目标发生任何外部提交时停止。`apply` 不调用下载回源，也不删除目标文件。
- 每个上传文件计算来源 SHA-256，并从目标重新下载核验内容。删除仅报告为
  `delete_candidate`，没有自动删除选项；重命名表现为新增加删除候选。
- 任务目录中的 SQLite 保存清单、计划和进度，不向 CloudFile 的业务数据库写入
  百万条逐文件记录。状态只属于这个任务目录，不能复用于另一个来源或目标。

## 使用

运行机需要 Python 3 和 `requests`，能访问 CloudFile API、返回的 fileserver 地址，
并有足够空间容纳单个最大文件的临时副本。目标使用专用技术账户 token；Filestash
使用独立只读 token。token 文件与任务目录不得放进待导入的本地来源树。

```bash
python3 tools/cf-import create \
  --job-dir /srv/import-jobs/tech-archive \
  --source local:///srv/frozen-share/技术部/A \
  --repo 00000000-0000-0000-0000-000000000000 \
  --target /历史资料/技术部/A \
  --server https://cloudfile.example \
  --token-file /run/secrets/cf_import_token \
  --fileserver-origin https://fileserver.example

python3 tools/cf-import check /srv/import-jobs/tech-archive
python3 tools/cf-import plan /srv/import-jobs/tech-archive --limit 20
python3 tools/cf-import apply /srv/import-jobs/tech-archive --exclusive
python3 tools/cf-import status /srv/import-jobs/tech-archive
```

Filestash 来源在 `create` 时增加 `--filestash-url` 与
`--filestash-token-file`，例如 `--source filestash://old-smb/技术部/A`。
URL 中的目录是 Filestash 会话可见的绝对目录。FileStash API 只保证当前接口能
列目录和读文件；具体后端的列表完整性、时间戳精度、目录变化、吞吐和服务端
只读边界须在使用前单独验证。单目录列表达到 10,000 项或接口显式提示后续页面时，
当前工具拒绝继续，避免把不完整列表误判为删除。

## 操作边界

`--exclusive` 表示运维已隔离目标资料库的其他写入者。现有原生上传接口没有让
`cf-import` 对整个资料库执行原子条件提交；HEAD 检查与文件发布之间仍有竞争窗口，
因此不能在开放给业务用户持续写入的资料库上运行。目标有外部提交时任务停止，
不会尝试合并或覆盖；源目录也必须来自冻结目录或一致性快照。
增量 `check` 先按路径、类型、大小与修改时间比较；来源在两次扫描之间即使内容变化
但这些元数据保持不变，当前工具不会发现。Filestash 时间精度和列表语义取决于后端。

正常中断可沿同一任务目录继续 `apply`。如果进程恰好在目标已经提交、但本地
进度尚未持久化时停止，HEAD 会不一致并拒绝自动重试，需要人工核验后另建任务；
工具不会猜测目标是否已正确写入。目录映射的目标路径须专用于该任务，不能与
其他导入任务交叉。对百万文件、数百 GB 或混合大小文件的首次导入，仍使用
`cf-migration`；当前 `cf-import` 的逐文件 API 上传与逐文件下载核验尚无该规模
的吞吐或恢复验收，不把它标为替代通道。

## 2026-09-30 验证范围

运行 `python3 -m unittest discover -s tests -p test_cf_import.py -q`：5 项通过，
覆盖本地映射和增量、FileStash `ls/cat` 模拟接口、分块 multipart 编码、
中断前未提交时续跑，以及目标已提交但响应丢失时拒绝盲目重试。

运行 `python3 tests/smoke_ce14_runtime.py --image cloudfile/cloudfile:14.0.8-cf.0-current --cf-import-runtime`：
在可销毁 CE14 库中通过真实 API/Go fileserver 导入。验证了选中目录映射、空目录、
排除非选中来源、原生下载内容、新增、修改、删除候选保留和目标 HEAD 漂移拒绝。
运行后容器与网络由夹具清理；结果记录在[验收证据](../releases/evidence/cf-import-2026-09-30.json)。

这次不构成 FileStash 实例与真实 SMB/NFS/SFTP 后端验收；FileStash 来源仅有接口模拟
测试。未进行百万文件、TB 数据、强杀恢复、并发写入或生产反向代理验证。普通业务写入
目标库、自动删除、冲突合并和无元数据变化的内容检测均不在当前适用范围内。
