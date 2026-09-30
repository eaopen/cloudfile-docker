# 目录分页正确性契约

修改原因：Server 在截取窗口后过滤 ACL，旧 Hub 对过滤后的长度做 limit+1 探测，会提前终止并把探测项混入当前页。

## 扫描与授权

- start 是固定目录对象、原生排序下的扫描位置；limit 是原始扫描窗口大小，不是可见项配额。
- Server 返回 scanned_count、scan_exhausted、next_scan_position、dir_revision 和 visible_items。无效对象和不可见对象仍占扫描位置。
- 非终止页 next_scan_position = start + scanned_count，且严格前进；终止页 next_scan_position 为 null。空的 visible_items 可以是非终止页。
- 每页重新应用现有库、父目录和条目权限，不缓存授权；目录 revision 不能作为授权凭证。
- Server 从当前路径解析目录对象，与 Hub 传入的 dir_revision 比较，然后读取同一目录对象；变化返回 DIR_REVISION_CHANGED，Hub 转为 HTTP 409。
- Hub 的 if_dir_id 保持原有可选校验；正确的续页调用必须传回首批 dir_id。Hub/Server 两处校验防止检查到 RPC 之间的变化。

## RPC 与 HTTP

新增 cf_list_dir_page(request_json) -> JSON 字符串。请求含 repo_id、path、user、dir_revision、start、limit（1–500），旧 list_dir_with_perm 不变。

HTTP 的 dirent_list 来自当前扫描窗口；dir_id = dir_revision，has_more = !scan_exhausted，next_start = next_scan_position。新增 scanned_count、scan_exhausted 为诊断字段。任何后续授权或类型过滤只修改条目，不重算分页状态。

升级顺序 Server 后 Hub。新 RPC 缺失、响应无效或读取失败返回 503；不回退到过滤后数量推断。保留不传 start/limit 的旧非分页响应。

修改原因：只验证分页 envelope 会让畸形条目进入展示层，返回错误的成功页或 HTTP 500。Hub 在构造任何展示对象前验证整页 item，任何违约统一抛出 DirectoryPageError 并返回 503，不修补字段或部分返回。

native `dirent_to_json` 固定返回 12 个 required 字段，无 optional 字段。`obj_id` 是 40 位小写十六进制字符串，`obj_name` 是字符串；`mode` 是非负 int32，POSIX kind 为目录或普通文件，`version` 是 int32；`size`、`mtime`、`lock_time` 是 signed int64；`is_locked`、`is_shared` 是 boolean；`modifier`、`permission`、`lock_owner` 是字符串或 null。nullable 字段仍必须存在，目录与旧版文件的合法 null 保留，不另加 `name`、`type` 或 `kind` 字段。

调试日志记录 scanned_count、visible_count、next_scan_position、scan_exhausted；不记录隐藏条目的名称。

## 性能边界与验收

仍读取并排序整个目录，不承诺 pageSize 级计算成本；本次不引入索引、目录缓存或跨请求权限缓存。

共享静态场景见 directory-pagination-cases.json。两端执行同一组窗口及完整遍历断言，另外验证 revision 变化、权限撤销、RPC 故障和旧非分页兼容。C 测试必须执行生产扫描函数和 RPC 实现，而不是另写一套分页算法。

## 修改文件

以下文件组成同一分页正确性修复，测试和规格的增加用于防止跨层语义漂移。

### cloudfile-server

- [.github/workflows/cloudfile-checks.yml](../../cloudfile-server/.github/workflows/cloudfile-checks.yml)
- [README.testing.md](../../cloudfile-server/README.testing.md)
- [common/cf-dir-page.c](../../cloudfile-server/common/cf-dir-page.c)
- [common/cf-dir-page.h](../../cloudfile-server/common/cf-dir-page.h)
- [common/rpc-service.c](../../cloudfile-server/common/rpc-service.c)
- [include/seafile-rpc.h](../../cloudfile-server/include/seafile-rpc.h)
- [python/seafile/rpcclient.py](../../cloudfile-server/python/seafile/rpcclient.py)
- [python/seaserv/api.py](../../cloudfile-server/python/seaserv/api.py)
- [server/Makefile.am](../../cloudfile-server/server/Makefile.am)
- [server/repo-mgr.h](../../cloudfile-server/server/repo-mgr.h)
- [server/repo-perm.c](../../cloudfile-server/server/repo-perm.c)
- [server/seaf-server.c](../../cloudfile-server/server/seaf-server.c)
- [tests/cf-dir-page/compile-fixture.py](../../cloudfile-server/tests/cf-dir-page/compile-fixture.py)
- [tests/cf-dir-page/fixture.c](../../cloudfile-server/tests/cf-dir-page/fixture.c)
- [tests/cf-dir-page/run.sh](../../cloudfile-server/tests/cf-dir-page/run.sh)
- [tests/cf-dir-page/test-pages.py](../../cloudfile-server/tests/cf-dir-page/test-pages.py)
- [tests/cf-permission-many/build-native-inner.sh](../../cloudfile-server/tests/cf-permission-many/build-native-inner.sh)：同步复制分页依赖，保证已有 native 联测构建使用完整的当前 RPC 源码。

### cloudfile-hub

- [.github/workflows/cloudfile-checks.yml](../../cloudfile-hub/.github/workflows/cloudfile-checks.yml)
- [cloudfile_ext/directory_page.py](../../cloudfile-hub/cloudfile_ext/directory_page.py)
- [cloudfile_ext/tests/test_directory_page.py](../../cloudfile-hub/cloudfile_ext/tests/test_directory_page.py)
- [seahub/api2/endpoints/dir.py](../../cloudfile-hub/seahub/api2/endpoints/dir.py)

### cloudfile-docker

- [.github/workflows/dev.yml](../.github/workflows/dev.yml)
- [BRANCHING.md](../BRANCHING.md)
- [docs/directory-pagination-cases.json](../docs/directory-pagination-cases.json)
- [docs/directory-pagination.md](../docs/directory-pagination.md)
- [docs/upstream-patches/cloudfile-server.txt](../docs/upstream-patches/cloudfile-server.txt)
- [tools/run-checks.sh](../tools/run-checks.sh)

## 验证记录（2026-09-30）

- Linux C/Hub 分页测试：28 项通过，无跳过（8 项 native、6 项 Hub envelope、9 项 item schema、5 项 native→Hub 端点联测）；两端执行同一组 9 个静态场景，另测版本、撤权、无效对象、RPC 故障及旧接口。运行 `cloudfile-server/tests/cf-dir-page/run.sh`，并排存在 Hub 时自动联测。需要 cc、glib/gobject、jansson、valac 和 Python 3。
- C 用例执行生产扫描函数、JSON RPC 包装、实际 ACL 过滤/求解器和真实 Vala Dirent；存储、数据库及会话 I/O 使用夹具，Hub 执行当前端点与授权装饰器源码。此结果不是已部署进程间 RPC/E2E 的证明。
- Server 既有 ACL 门禁：84 checks / 0 failures；写操作门禁：159 checks / 0 failures，50 个调用点类型检查通过。
- 初次分页实现时的 Hub 扩展回归：522 passed / 5 skipped；这 5 个需要 C 动态库的用例已在 Linux 联测中全部执行通过。同次 Hub 契约：509 passed / 284 skipped（依赖外部服务的用例未运行），218 subtests passed。
- 隔离 Linux ARM64 完整 `autogen/configure/make -j2` 通过，生成 ELF seaf-server；二进制包含 cf_list_dir_page_json、seafile_cf_list_dir_page、seaf_repo_manager_list_dir_with_perm_page。使用已有构建镜像及本地 libsearpc/libevhtp，不修改部署；FUSE 禁用。
- 提交前补充验证：同步分页依赖后的 `tests/cf-permission-many/build-native.sh` 在隔离 Linux ARM64 容器中编译并链接通过，测试专用 seaf-server 含全部三个分页符号；permission-many 既有 6 项 transport 测试通过。带测试计数器的二进制不用于部署或发布。
- Shell/Python 语法与 git diff --check 通过。没有修改 EAP/Browser，没有运行部署或 push。

Server DEBUG 的终止游标日志使用 -1；RPC/HTTP 终止游标均为 null。Hub DEBUG 记录原生授权后、展示/外层授权裁剪前的 visible_count。
