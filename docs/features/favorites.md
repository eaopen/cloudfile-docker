# 收藏对象 ID 化（P2-05）

> **用途**：说明 CloudFile 把收藏（starred items）从 `repo_id + path` 改为对象唯一 ID 的语义、迁移和验收边界。
> **适用版本**：CloudFile `14.0.0-cf.0`，基于 Seafile CE 14 源码重构。
> **状态**：验证中；开关 `CF_ENABLE_FAVORITES_ID` 默认关闭，关闭时保持原生 CE 行为。纯规则单测通过，移动/重命名与迁移的容器 E2E 待补（见 [review-cases.md](review-cases.md)）。
> **依赖**：P2-02（九模块用例集）；对象 ID 即 Seafile 文件 `obj_id` / 目录 `dir_id`。

## 问题

原生 Seafile 收藏以 `repo_id + path` 定位对象。移动或重命名后路径失效，收藏要靠
seafevents 与 `repos_batch.py` 的路径改写去追，路径改写对目录尾斜杠、批量重命名和
冲突改名都脆弱，遗漏一次收藏就指向已删除位置。评审清单（P2-02）的树结构与移动模块
正是覆盖这条链路。

## 方案

收藏改为按**对象唯一 ID** 标识：

- 身份 = `(email, org_id, obj_id)`。`obj_id` 是文件内容对象 ID 或目录 ID，移动/重命名
  不改变它，因此收藏跟随对象而不是路径。
- `repo_id + path` 退化为“当前位置”缓存，用于展示与导航；移动/重命名时按 `obj_id`
  重新落位，不再依赖脆弱的路径改写。
- 旧 `path` 记录通过迁移无损回填 `obj_id`（只补不删）。

| 层 | 文件 | 作用 |
|---|---|---|
| 开关 | `cloudfile_ext/features.py`、`settings_defaults.py` | `CF_ENABLE_FAVORITES_ID`，默认 `false` |
| 纯算法 | `cloudfile_ext/favorites/identity.py` | 无 Django/DB/Seafile 依赖的标识与重定位规则，单测 `test_identity.py` |
| 数据 | `seahub/base/models.py` `UserStarredFiles.obj_id` | 可空字符列（64），索引；列由 `apply_starred_obj_id_schema_compatibility()` 幂等补齐 |
| 逻辑 | `seahub/utils/star.py` | `star_file`/`unstar_file`/`is_file_starred` 按 `obj_id` 判存与去重；`get_dir_starred_obj_ids` 供目录列表打标 |
| 迁移 | `seahub/base/management/commands/backfill_starred_obj_ids.py` | 幂等回填 `obj_id`，不可解析的行保留不删 |
| API | `seahub/api2/endpoints/starred_items.py`、`api2/views.py`、`api2/utils.py` | 列表/详情返回 `obj_id`；目录列表与文件详情按 `obj_id` 打星标 |
| 落位 | `seahub/api2/endpoints/repos_batch.py` | 跨库移动回调先按 `obj_id` 重定位，再回退路径改写 |

## 语义与边界

- **内容寻址**：文件 `obj_id` 是内容哈希。内容相同的两个文件共享同一 `obj_id`，因此
  收藏“对象”等价于收藏“内容”——复制出的同内容文件也会命中同一收藏。这是对象 ID 化的
  固有语义，不是缺陷；对目录，`dir_id` 由其子项决定，重命名/移动不改变它。
- **跨库移动**：`obj_id` 不变，收藏跟随对象跨库迁移；`repo_id` 仅在移动回调中更新。
- **旧数据无损**：回填只写 `obj_id`，从不删除行。资料库或路径已不存在的行保留原样，
  继续按原生“已删除”展示，待数据恢复后可再次回填。
- **开关关闭 = 原生 CE**：`CF_ENABLE_FAVORITES_ID=false` 时全部逻辑走 `repo_id + path`，
  不写不读 `obj_id`。

## 迁移

```bash
python3 manage.py backfill_starred_obj_ids
```

- 幂等：只处理 `obj_id IS NULL` 的行。
- 无损：解析不到的路径跳过，不删除。
- 支持 `--limit N` 分批执行。

## 验收

1. 收藏文件/目录后，同库或跨库移动、重命名，收藏仍指向同一对象（星标与列表均跟随）。
2. 迁移前的 `repo_id + path` 记录全部保留，能解析的回填 `obj_id`，不能解析的不丢失。
3. `CF_ENABLE_FAVORITES_ID=false` 时，收藏行为与原生 CE 一致（`tree-001` 等用例仍绿）。
