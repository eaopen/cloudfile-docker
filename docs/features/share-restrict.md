# 外部分享管控（P2-11）

> **用途**：说明评审清单「外部分享」模块的落地面（review-share-cases.json 的
> share-002/003/004）。新增开关 `CF_ENABLE_SHARE_RESTRICT`，默认关闭；关闭时
> 外部分享为原生 CE 行为，开启后由 CloudFile 管控。
> **适用版本**：CloudFile `dev`，Seafile CE 14 参考基线。
> **状态**：验证中；容器 E2E 门禁见
> [`.github/workflows/review-share-e2e.yml`](../../.github/workflows/review-share-e2e.yml)
> 与 [`review_share_matrix.py`](../../tests/e2e/review_share_matrix.py)。

## 开关与语义

`CF_ENABLE_SHARE_RESTRICT`（默认 `false`）：

| 状态 | 行为 |
|---|---|
| `false`（默认） | 原生 CE：任何有权限的用户可创建外链，匿名可访问，与上游一致 |
| `true` | 外部分享管控：非系统管理员**创建外链被拒**（403）；**匿名访问任何旧外链被拒**（按不存在处理，404）；链接与历史数据**保留**，管理员仍可创建、列举与管理；前端分享入口隐藏（浏览器套件阶段验收） |

## 门禁面

创建（非管理员拒 403）：

- `POST /api/v2.1/share-links/`（`ShareLinks.post`）
- `PUT /api2/repos/{id}/file/shared-link/`（`FileSharedLinkView.put`）

匿名访问（开关开启一律按 404 处理，防止信息泄漏）：

- `view_shared_file`（`/f/{token}/` 页面与 `?dl=1` 下载）
- `view_shared_dir`（`/d/{token}/` 页面）
- `GET /api/v2.1/share-links/{token}/`（`ShareLink.get`，非管理员 404）
- `GET /api/v2.1/share-links/{token}/dirents/`（`ShareLinkDirents.get`）

保留面（不受影响）：

- `GET /api/v2.1/share-links/`、`GET /api2/repos/{id}/file/shared-link/` 等列表/查询端点
- 已存在链接数据不删除

## 验证

```bash
# 起栈时在 .env 加 CF_ENABLE_SHARE_RESTRICT=true，然后：
python3 tests/e2e/review_share_matrix.py --url https://127.0.0.1 --insecure \
    --admin admin@example.com --admin-password xxx
```

矩阵断言：rw 用户创建外链被拒（share-002）；管理员查询端点保留（share-003）；
管理员建链成功后匿名访问旧链接返回 403/404 而非内容（share-004）。
基线 smoke（开关全关）仍要求普通用户可建链并成功，保证默认行为与 CE 一致。
