# CloudFile 2.0 dev2 组装、冻结点与阶段门禁

> 2026-10-16 · DEV-only 初始化状态。此处的 `2.0.0-dev.1` **不代表发布、不代表已构建镜像、更不允许触碰现有生产部署**。

## 当前来源

- Server `dev2` @ `ed0cb02937c6246c579f650f870bd298d5c7876b`：继承 CE14 底层写入及已验证补丁；对共享根新增正向 ACL 的原生终判。
- Hub `dev2` @ `94ee2853c7827b2e5c5766982c473f58f0c2b24e`：继承 CE14 Web/API，输入侧正向 ACL + `share_mode` 校验及单元用例。
- Docker `dev2`：只由此仓 `release.yaml` 组装 Server/Hub 的 **固定提交**，不接受滚动的 `dev` 默默参与构建。旧 `dev` 保持 CloudFile v0.9。
- `jcetech/etech-eap` / `etech-eap-web` 固定使用已统一且包含 E0–E2 的 `dev`；不另起一条独立 Etech dev2 业务实现。

运行以下**本地**前提检验（需要三仓并排克隆、Linux 构建依赖与基础数据库时按测试说明设置）：

```bash
python3 tools/verify-v2-source-pins.py
python3 -m unittest discover -s tests -p test_dev2_source_pins.py -q
./tools/run-checks.sh
```

自动化：`.github/workflows/dev2.yml` 监听 Docker `dev2` 提交/手动启动，checkout 三仓各自的 `dev2`，但只有与上面已锁定 SHA 一致时继续测试，禁止误把 v0.9 源码组装成 2.0。后续 Server/Hub 提交必须更新 `release.yaml` pins，才可声称新的三仓快照已对齐。

## 首版完成的与未完成的

| 能力/层级 | 初版处理 | 后续真实门禁 |
| --- | --- | --- |
| CE14 底座与原生字节路径 | 沿用已验证 v0.9 接缝，未重写 | Server/Hub 原生回归 + Docker 独立新装 |
| 共享根语义 | Hub/API 与原生 Server 双层拒绝非正向共享授权 | MySQL 紧缩/撤权、跨路径 C/Go 最终提交真实验收 |
| 身份与动态组 | 沿用已有能力，未称完成 2.0 通用双标识收敛 | Authentik 旁路失效不影响 Etech 登录、稳定 UID、TTL 失效关门 |
| 单一 `cf_dir_acl` | v0.9 的统一 ACL 成果复用；不恢复 `cf_dir_share` | 旧 schema 迁移、失效回滚、内容拒绝与共享根 3 场景 |
| 两张核心新表 | `cf_library_storage_key` 已有；`cf_dir_acl` 已有 | **精简 2.0 新装 Schema 尚未实现**，含移除旧 `cf_managed_library*` 与 `cf_dir_admin` 的安全替代 |
| 与 Etech 两表配置和 BPM | 保持 Etech 已完成的 E0–E2 API 约定 | 已固定 Etech DEV 的真实授权发布/回执/CRUD 测试 |
| 上传下载直连 EAP 解耦 | MVP 后最高优先，不在此阶段冒险改造 | 真实 SSO、短票据、Fileserver 上传下载及原生最终授权 |
| 镜像/运行/生产切换 | **尚未构建、未部署、未验证** | M1+M2 和回滚全部实测后才考虑发布 |

注意：`release.yaml` 的 `database_schema: 3` 暂时保留旧部署兼容数值，**不是 2.0 精简 Schema 完成标志**。现有 001–042 的 legacy schema、`cf_managed_library` 读写保护尚在，不能只删表、改开关或靠 Nginx 隐藏入口宣称实现 2.0。

DEV Etech 单入口先允许 `/seafile + /seafhttp`，别名 `/cfile + /cfhttp` 属可延期能力；Etech SSO 是主系统之外的旁路，不能反向影响 PLM 主登录。2.0 首批优先验证浏览、目录内容授权、共享根和原生字节提交真实一致性。

本次机器环境限制：上海开发机 RDC 未连接，Docker/C/Go/DB/Etech DEV 现场联验未实际执行；静态文件和 GitHub 提交不代表通过它们。
