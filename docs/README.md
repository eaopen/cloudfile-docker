# cloudfile-docker 文档入口

> 用途：说明本仓保留哪些文档
> 适用版本：Seafile CE 14 扩展版 / CloudFile V2
> 当前状态：有效（2026-10-21 起）

本仓是构建与部署实现仓，不承载产品文档。2026-10-21 起：

- 产品、部署、能力与历史文稿**不在本仓维护**；本仓只保留代码与约定本身。
- 测试用例数据（`*-cases.json`）放在 `tests/cases/`，属于测试夹具，不是文档。
- `docs/` 只保留 dev CI 机器校验的三份权限契约与上游改动登记；新增文档会被
  `tools/gates/preflight-checks.py` 的边界检查拒绝。

## 保留的文件

| 文件 | 作用 |
|---|---|
| [权限终判契约](permission-adjudication-contract.md) | 库/目录/共享根/最终写入共用同一 V2 授权结果 |
| [五表权限事实](permission-tables.md) | `cf_library_storage`、`cf_dir_acl`、`cf_sso_group_map`、`cf_edit_guard`、`cf_audit_event` |
| [ACL 语义](acl-semantics.md) | 路径规则、共享根与继承 |
| [`upstream-patches/`](upstream-patches/) | 对上游文件所做改动的登记，供同步上游时核对 |

## 其余入口

| 需要什么 | 看哪里 |
|---|---|
| 开发约束、构建入口、禁止事项 | 根目录 [`AGENTS.md`](../AGENTS.md) |
| 容器配置与运行行为 | 根目录 [`CLOUDFILE.md`](../CLOUDFILE.md) |
| 分支与上游同步 | 根目录 [`BRANCHING.md`](../BRANCHING.md) |
| 部署怎么跑 | [`deploy/compose/README.md`](../deploy/compose/README.md) + `.env.example` |
| 来源 SHA 与镜像 | [`release.yaml`](../release.yaml)、`build/cloudfile_14.0/`、`image/cloudfile_14.0/` |
| 测试怎么跑 | `tools/gates/verify-local.sh`（默认冒烟 `e2e`；全量矩阵 `e2e-full`，参考用） |
| 目录分工（上游 / CloudFile / tools / tests） | 根目录 [`AGENTS.md`](../AGENTS.md) 的「目录分工」与「tools / tests 的固定分区」 |
