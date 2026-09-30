# Legacy Search Bounded Permission Transport（Task 4B.2）

修改原因：legacy/native writers 没有共同 revision/guard，发布前第二轮检查不能删除。本次仅把跨进程调用合并；内部仍逐路径执行原 scalar permission engine，不复用最终授权结果，不修改新版 Search、EAP、annotations、lifecycle 或 writers。

## Internal RPC Contract

`cf_check_permissions_many(request_json) -> response_json`，注册于 `seafserv-threaded-rpcserver`。

```json
{"version":1,"repo_id":"11111111-1111-4111-8111-111111111111","user":"reader@example.test","paths":["/","/a","/a/file"]}
```

```json
{"version":1,"repo_id":"11111111-1111-4111-8111-111111111111","user":"reader@example.test","items":[{"path":"/","permission":"rw"},{"path":"/a","permission":"r"},{"path":"/a/file","permission":null}]}
```

- 每批一个 repo、一个 native identity；1–50 个 path；JSON UTF-8 最大 65,536 bytes；每个 path 最大 4,096 bytes；user 非空且最大 255 bytes。Hub 同时按数量和实际 JSON 字节分片。50 是内部 transport 上限，不是搜索分页/权限契约。
- 拒绝非绝对路径、NUL、重复分隔符、`.`/`..` 段、超过 130 个 split 项；规范化单个尾 `/`，保留 root。不做 URL decoding 或 Unicode 折叠。
- 请求的重复 path 保留重复槽位，并逐槽再次执行 scalar；Search 自己先去重。响应严格按输入位置、规范化 path、repo、identity、version 验证，不接受缺项、增项、错位、重复覆盖、非法 permission 或重复 JSON key。
- `r`/`rw` 是可读候选；其他 scalar permission 与旧 Search 一样收窄成 `null`。不存在默认 allow。
- 已上报的 `GError`、RPC 异常、超时、非法响应导致整批失败；后续分片失败也丢弃整页。native 每次 scalar 前后检查 10 秒预算，Hub 对整个请求预算复核。预算是协作式检查，不会中断正在阻塞的旧 provider/SQL。
- **旧 provider 的限制**：`CfPermFunc` 只返回 `char * / NULL`。未通过错误通道上报的内部故障，与拒绝一样成为 `null`；本次不改变这个 scalar 语义，不能声称能识别所有 provider 内部故障。显式错误不会被转换为部分成功。
- Server 与 Python binding 需先升级；Hub 遇到旧 Server 缺方法时 fail closed，不回退到 N 次 scalar transport。

## Two-Pass Publication

```text
fresh legacy snapshot
→ root + query directory 初始准入 batch
→ bounded candidate windows：规范化 / 去重
→ 收集 parent + exact path + 配置过的 ancestor boundaries
→ 按数量/字节分片 native multi-check
    每条仍调用 seafile_check_permission_by_path
    → repo qualification → registered C providers → C ACL resolver
→ 每条 Hub hooks + native folder rules + sparse rules + ancestor 可见性判断
→ current metadata（native fallback 复用原目录项）
→ response proof / cursor / DRF rendering，字节仅在内存中
→ fresh snapshot compare
→ 已通过路径与必要祖先：独立的第二轮 native multi-check + Hub hooks
→ fresh snapshot compare
→ repo/head compare
→ 返回已渲染 Response
```

第二轮不读取第一轮 `native_inputs`。仍检查原先被接受但后来发现 stale/missing 的路径，不缩小原有复核集合。单个对象不会使用父目录或首对象的授权结论。

`Response.render()` 在最后一轮复核前执行，DRF `finalize_response` 不再次渲染已生成字节。这个保证覆盖 metadata、DTO/cursor 生成与当前 renderer；不覆盖最终检查之后的 writers、middleware 修改、网络发送，不构成读写一致性 lease，也不能检测 ABA 撤权再恢复。

## Measured Structure

同 repo、同 parent `/a`、全部 allow、legacy ACL 启用且有一条 root rule，真实 Linux seaf-server + MySQL 8 + Unix-socket RPC；初始目录准入单独一批。

| Results | Path RPC Before → After | Scalar Before → After | C Resolve Before → After | Native ACL SQL | Membership SQL | Share Qualification SQL | Hub Hook |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 6 → 3 | 6 → 6 | 6 → 6 | 6 | 9 | 9 | 6 |
| 20 | 44 → 3 | 44 → 44 | 44 → 44 | 44 | 47 | 47 | 44 |
| 50 | 104 → 4 | 104 → 104 | 104 → 104 | 104 | 107 | 107 | 104 |
| 100 | 204 → 6 | 204 → 204 | 204 → 204 | 204 | 207 | 207 | 204 |

Path transport 数不包含原有 snapshot 的 identity/group/repo RPC、head 或 metadata RPC。Membership/Share SQL 包含 3 次 snapshot 刷新；native ACL SQL 是每路径 `load_repo_rules` 的查询，不含 Hub 自己的规则读取。计数取自测试构建的 C 入口日志与隔离 MySQL general_log（排除 PREPARE），没有加入生产 tracing。没有启用 ACL 或没有规则时，C resolver 次数可以少于 scalar 次数，不能把此列普遍视为固定公式。

## Validation And Remaining Debt

- Hub mock/协议测试覆盖 read/deny、file deny、hidden ancestor、native folder rules、mixed、duplicates、多 parent、不同 repo/identity、UTF-8/数量/字节预算、错位/缺项/增项/非法响应、provider/timeout/部分失败、hook 复核。
- Native 纯 C fixture 编译真实 RPC/scalar/provider/ACL 代码；IO 替身只用于可重复的错误、超时和计数注入。
- 独立真实 native 进程测 scalar/multi parity 与真实 SQL。四种 writer（ACL SQL 更新、share revoke RPC、group_remove_member RPC、update_emailuser RPC）分别在第一轮后、metadata 中、第二轮 RPC 内、第二轮后、serialization 时注入，20 例均 503 丢弃整页。
- 第二轮 RPC 内通过**测试专用** ACL table gate 确认 scalar 已进入后再提交 writer；生产没有增加锁。该用例证明丢页与边界复核，不能据此声称覆盖所有任意时序或存在 lease。
- 真实 fixture 明确使用 legacy `cf_dir_acl(subject)` schema；不将 4A `subject_id` schema 混入 scalar engine。Hub auth/ORM 初始化由测试适配器接线，未做完整浏览器/HTTP 登录链路或 Pro-only native folder writer 联验；后者由 Hub规则测试覆盖。
- SQL / membership / qualification / ACL 加载仍约 O(N)，两轮均保留；Meili dirent lookup 仍 O(N)，fallback 复用目录项。本次不是 internal authorization batch，后续不得用全局 revision/cache 或删复核掩盖这些成本。

建议状态：**transport optimization complete / internal batch debt accepted**。不继续修改 legacy writers 或 lifecycle。

测试入口：Server `tests/cf-permission-many/run.sh`、`build-native.sh`、`run-native.sh`；Hub `cloudfile_ext/search/tests/`。Native runner 只创建独立容器/网络，结束后自动清理，保留日志和 JSON 计数证据。
