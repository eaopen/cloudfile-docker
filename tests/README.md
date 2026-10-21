# tests 分层与用例集

`cloudfile-docker/tests` 里放的不只是"测试文件"，而是几层依赖完全不同的东西。混着看会得出错误结论——最典型的是把根级静态契约当成服务已验证，或者为了跑一条 Schema 检查去起 Docker。先按层问问题，再选命令。

目录分工的规则来源见 [AGENTS.md](../AGENTS.md) 的"tools / tests 的固定分区"。以下命令默认都在 `cloudfile-docker` 仓根目录执行。

## 分层一览

| 层 | 位置 | 由谁跑 | 依赖 | 回答的问题 |
| --- | --- | --- | --- | --- |
| 根级单元与契约 | `test_*.py` | `tools/gates/run-checks.sh`（一次 `unittest discover`） | 纯 Python，无镜像、无 DB | 静态契约、清单、Schema 盘点、配置生成是否仍然自洽 |
| Shell 契约 | `tools/test-*.sh` | 同上（逐条 `run`） | bash + git | 构建/发布脚本与 workflow 的契约没漂移 |
| 冒烟 E2E（默认） | `e2e/smoke.py` | `tools/gates/verify-local.sh e2e` | 已构建镜像 + 本机栈 | 起得来吗？登录、上传下载、目录列表主路径还通吗？ |
| 能力矩阵（参考） | `e2e/full/` | `verify-local.sh e2e-full` / `verify-local.sh cap <名>` | 同上，且每项带开关重启一次栈 | 开着某个开关时，每个入口是否真的执行了那条规则？ |
| 跨仓用例集 | `cases/*.json` | 各仓的测试脚本读取 | 无（纯数据） | 同一份契约在 C / Go / Python 三端是否表现一致 |
| 停机运行时 | `v2/native_runtime.py` | 当前无门禁 | 见第 5 节 | —— 待决策 |
| 夹具 | `fixtures/` | 清单类测试读取 | 无 | 上游源码锁基准 |

## 1. 根级单元与契约测试

```bash
cd cloudfile-docker
python3 -m unittest discover -s tests -p 'test_*.py' -q
```

一次跑完全部根级 `test_*.py`（上百条，数秒），`tools/gates/run-checks.sh` 用的就是这一条。`tests/` 没有 `__init__.py`，所以 discovery 只收根级文件，不会递归进 `e2e/`、`cases/`、`tools/`、`v2/`——那些需要活栈或外部运行时，不属于这条秒级门禁。新增根级测试放在这里就会被自动收进来，不必再改门禁脚本。

两个例外单列，不能并进上面的发现：

```bash
python3 -m pytest tests/test_automatic_local_storage.py -q   # pytest 风格（parametrize），unittest 收不到
python3 tests/test_v2_authorization_contract.py              # .github/workflows/dev.yml 按名字跑这一条
```

## 2. Shell 契约测试

`tests/tools/` 下的 `test-*.sh` 校验构建、镜像、发布脚本与 workflow 的契约（基础镜像、平台规范化、缓存、产物完整性、上游改动登记），不碰 Docker 守护进程。

```bash
bash tools/gates/run-checks.sh            # 全量快速检查（含本层）
bash tests/tools/test-release-artifact.sh # 单跑一份
```

## 3. E2E：冒烟是默认，矩阵是参考

```bash
./tools/gates/verify-local.sh build     # 先有镜像：preflight + 发行包 + 应用镜像
./tools/gates/verify-local.sh e2e       # 默认冒烟（不重启容器，几分钟内出结论）
./tools/gates/verify-local.sh e2e-full  # 全量矩阵，约一小时，只作参考
./tools/gates/verify-local.sh cap acl   # 只跑一个能力
```

能力清单登记在 `tools/gates/verify-local.sh` 的 `CAPABILITIES`（`能力名|要打开的开关|矩阵脚本`）；需要额外配置或不止跑一遍的能力用 `cap_<名>_env` / `cap_<名>_run` 钩子表达。分层理由与失败时的判读顺序见 [e2e/README.md](e2e/README.md)。

## 4. 用例集（`cases/`）

这些 JSON 是**跨仓契约**，不是本仓私有夹具。改字段要同步改消费方，只在本仓改 schema 会让另一端的解析静默失效（尤其 FileOps 的 C 头文件由脚本生成）。

| 用例集 | 消费方 |
| --- | --- |
| `fileop-cases.json` | `cloudfile-server/tests/cf-fileop/run.sh`、`gen-cases.py`、`test-cf-fileop.c`；`cloudfile-server/fileserver/cf_fileop_test.go`（同一份用例驱动 C 与 Go 两端） |
| `automatic-local-storage-cases.json` | `cloudfile-server/tests/cf-auto-storage/run.sh`；`cloudfile-server/fileserver/objstore/cf_auto_local_test.go`；`tests/test_automatic_local_storage.py`；`build/cloudfile_14.0/run-storage-tests.sh` 用 `CF_AUTO_STORAGE_CASES` 指向它 |
| `system-admin-content-cases.json` | `cloudfile-server/tests/cf-system-admin/test-qualification.py` |
| `review-<模块>-cases.json`（tree / icon / copy / move / tags / search / history / recycle / share，共 9 份） | `tests/e2e/full/review_harness.py` 的 `load_cases()` + 各 `*_matrix.py`；其中 channel=ui 用例在 API 矩阵里报 skipped，由 `e2e/full/review_ui_*.py` 在浏览器里真正断言（脚本头注释对照同一份 JSON）。schema 由 `tools/gates/validate-review-cases.py` 校验（`run-checks.sh` 已接入） |
| `review-favorites-cases.json` | `tests/e2e/full/favorites_matrix.py`（同样经 `review_harness.load_cases()`） |

查一份用例集还有没有读取方，用索引级搜索，别只看本仓：

```bash
# 在 cloudfile-docker 根目录执行；三仓并排检出由 workspace 根决定
workspace=$(dirname "$(git rev-parse --show-toplevel)")
for repo in cloudfile-docker cloudfile-hub cloudfile-server; do
    git -C "$workspace/$repo" grep -n -I -- '<用例集文件名>'
done
```

## 5. 停机：`v2/native_runtime.py`

这个文件不是死的，但**没有被任何当前门禁调用**，属于已停机待决策：

- 它要真实 CE14 C/Go 构建树与真实 MySQL/Redis：`CF_V2_SOURCE`、`CF_V2_PREFIX`、`CF_TEST_DB_HOST`（`CF_TEST_DB_PORT` 可选，默认 3306），并且要同时检出 `cloudfile-hub`——`cloudfile_ext.v2` 的 `identity` / `memberships` / `schema` / `native_discovery` 都在那边。
- 指标都对得上：这些模块在 Hub 侧仍然存在，所以它一旦接回门禁就能跑，不是依赖已消失的死代码。
- 它唯一的引用是 eap-cloudfile 历史文档里归档的 workflow；当前 `run-checks.sh`、`verify-local.sh` 与 CI 都不跑它。
- 因此**先记录、不删除**：删掉等于把一份已验证过的字节级真实启停测试静默丢掉。是否接回门禁是待决策项，不是已完成项。

## 6. 夹具（`fixtures/`）

`fixtures/source-lock.json` 是上游源码锁，`test_package_provenance.py`、`test_source_manifest.py` 等清单类测试读它。它不是用例集，不要往里加业务数据。

## 删除记录

**2026-10-22**，删除四份没有代码消费方的历史用例集：

| 用例集 | 删除原因 |
| --- | --- |
| `cases/acl-cases.json` | 三仓源码与索引里都没有读取方；当前 ACL 语义由能力门禁 `acl_matrix.py` 与文档契约 `tests/test_v2_authorization_contract.py` 覆盖，都不读这份 JSON |
| `cases/directory-access-v09-cases.json` | 同上；它服务的是已不在当前 V2 主线上的旧 V0.9 目录资格适配层（现行权限链见 AGENTS.md），无读取方 |
| `cases/directory-pagination-cases.json` | 同上；原消费方（Server C / Hub ctypes 适配测试）当前都不再引用它 |
| `cases/device-edit-upload-cases.json` | 同上；Agent2 本地编辑的当前边界由 AGENTS.md 规定，不由这份 JSON 驱动 |

判据：在 `cloudfile-docker`、`cloudfile-hub`、`cloudfile-server` 三个仓的工作树与索引里用 `git grep` 搜文件名，均 0 命中。仍提到这四个名字的只有 eap-cloudfile 的文档（`docs/docker/` 的现行文档与 `docs/history/` 的历史副本）；那些是相对链接，指向它自己并不存在的副本（`eap-cloudfile/docs/docker/acl-cases.json`、`eap-cloudfile/docs/history/acl-cases.json` 等），在本仓删除之前就已经是悬空链接，且没有任何一处指向 `cloudfile-docker/tests/cases/`。所以本次删除没有打断任何引用，本仓也不再保留一份会被误当作当前契约的 JSON。

保留并**不要删**的：`fileop-cases.json`、`automatic-local-storage-cases.json`、`system-admin-content-cases.json`，以及十份 `review-*-cases.json`——它们都有活的消费方（见第 4 节）。
