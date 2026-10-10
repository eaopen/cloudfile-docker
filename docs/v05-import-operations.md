# V05-03 cf-import 操作报告与恢复边界

`cf-import` 继续复用已有的 `create/check/plan/apply/status`、SQLite checkpoint、来源/目标 HEAD 冲突保护，不新增第二套导入引擎，也不做常驻目录同步。

新增 `python3 tools/cf-import report /absolute/job-directory`：只读 JSON，包含计划阶段、各类动作数量/字节数/已完成/待完成、保留的 `delete_candidate` 数量、是否需要人工核对、目标库/根及最近 HEAD。输出不含访问令牌和密钥。

操作顺序：`create`（首次）→ `check` → `plan` → `apply --exclusive` → `report`。同一目标再次增量导入前先 `check`，仅处理已知变化，来源删除只报告候选，绝不删除目标。如果某个传输在服务端**提交前**失败，且 HEAD 未变化，可从已完成 checkpoint 续跑；提交已生效但响应丢失时 HEAD 可能不一致，**必须停止并人工核对**，不能凭重试或本地报告推断未知结果成功。真实写入期间需操作方独占目标库。

验证：`python3 -m unittest discover -s tests -p test_cf_import.py -v` 与 `python3 -m unittest discover -s tests -p test_cf_import_report_v05.py -v`。本轮原有 5 项、报告 2 项通过；已有 `tests/cf_import_runtime.py` 为原生容器导入场景，尚未在本轮重新运行，真实部署版本组合仍须单列验证。
