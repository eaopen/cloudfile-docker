# Task 4C：Legacy FileTag 批量读取

日期：2026-09-30。仅优化 legacy FileTag 读取；不修改 Search、4A annotations、lifecycle 或 native scalar permission engine。

## 契约与部署

- Hub 新端点：`GET/POST /api/v2.1/cloudfile/legacy-file-tags/batch/`，沿用 `CF_ENABLE_TAGS` 开关和当前用户 Token/Session 认证。GET 返回能力，不缓存。
- GET：`{version:1, model:"legacy-file-tag", max_items:50, max_bytes:65536, max_path_bytes:4096}`。
- POST：`{version:1, repo_id:"UUID", items:[{path:"/a/f", is_dir:false}]}`；每次只能一个 repo、当前登录身份。限制按 UTF-8 字节计算，50 项为实现预算。
- 响应：`{version:1, model:"legacy-file-tag", repo_id:"UUID", items:[{path:"/a/f", is_dir:false, status:"OK", tags:[{id:1,name:"tag",creator:"user"}]}]}`。
- 单项状态为 `OK / DENIED / NOT_FOUND / FAILED`，失败项 `tags:null`，成功无标签为 `[]`。授权/provider/SQL 共享故障丢弃整个 HTTP 分片并返回 503；对象存在性查询失败只标记该项 FAILED。非法请求返回 400。
- 仅使用 `seahub.tags.FileUUIDMap / FileTag / Tags`。不使用另一套 `seahub.file_tags.FileTags / RepoTags` 或 `cf_tag`；本模型没有 color/label 字段。
- 部署顺序：已有 4B.2 native multi-check → Hub（开启 TAGS，验证 GET 和 POST）→ EAP。新 EAP 遇旧 Hub/协议不匹配时逐项 UNAVAILABLE，不回退 N 次 scalar HTTP。旧单项 URL 和旧客户端保留。

EAP 现有 Browser 路由仍为 `/libraries/{repoId}/file-tags/batch`，最多 200 个唯一对象；跨 repo 使用各自现有路由，不能在 item 覆盖 repo。维持首次出现去重及顺序、库级业务拒绝整批失败、对象级失败逐项返回；Hub 本身保持重复输入槽位并深复制 DTO。保留原 8 秒总预算、TIMEOUT/partial 语义。响应缺项、错位、重复键、尾随 JSON、错误 model/版本、失败项附带标签均拒绝。

## 数据流与安全边界

旧：Browser → EAP → 线程池逐项 effective HTTP → 逐项 legacy tags HTTP → UUID 查询 → binding 查询 → 每标签 definition 查询。

新：Browser → EAP 库级业务门禁 → capability → 按数量/实际 JSON 字节分片 → Hub 规范化/去重 → 复用 4B SearchAccess/NativePermissionMany（代码不变）→ parent/exact/configured ancestor 独立判断 → native 存在性查询 → UUID 集合查询 → binding/definition JOIN → 恢复顺序 → render → snapshot/native 第二轮/snapshot/head 复核 → 返回。

4A OIDC 一致性 scope 不能覆盖 legacy native writers，因此不强接 consume_many。每对象继续判断；parent 只作附加边界，不能代表对象。两轮 native permission engine/hook 独立执行。最终检查覆盖实际 DRF rendering 后的边界，但没有 writer lease，最后检查至 socket 写出仍是有限复核窗口。

UUID 以 repo/parent hash、filename、is_dir 的参数化 OR/IN 集合查询加载；虚拟库使用既有 origin 映射，root 使用 legacy 空 parent/name identity。只查询授权对象，不生成 UUID。bindings 使用 `select_related('tag')`，按 binding PK 保持既有插入顺序；最多 2000 bindings，超过返回错误而非截断。UUID 最多探测 51 行；响应最多 2 MiB。无授权对象不读取标签表，无 UUID 不执行 binding 查询。

## 结构计数

单 repo、同非根 parent、全部允许、短路径、唯一对象；B=ceil(N/50)。C 为保留的库级业务门禁 HTTP。真实本地 HTTP server 验证了新 EAP transport；旧 HTTP/native 数来自实际 scalar 调用链。native 新计数通过真实 adapter + RPC fixture 验证，未宣称运行了生产 C engine。

| N | Browser HTTP | EAP→Hub 旧 | EAP→Hub 新（含能力探测） | native path RPC 旧→新 | repo qualification RPC 旧→新 | 新 path engine 输入数（两轮） |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 1 | 2+C | 2+C | 1→2 | 1→3 | 6 |
| 20 | 1 | 40+C | 2+C | 20→2 | 20→3 | 44 |
| 50 | 1 | 100+C | 2+C | 50→4 | 50→3 | 104 |
| 100 | 1 | 200+C | 3+C | 100→8 | 100→6 | 208 |
| 200 | 1 | 400+C | 5+C | 200→16 | 200→12 | 416 |

repo qualification 列不含库级门禁常量：旧逐项 effective endpoint 调用 repo permission，新 snapshot 三次/分片。不要把 repo permission、path engine 和 C evaluate 混为一个计数。新 path engine 输入为 `2(N+2B)`，包括 root/parent；两轮安全复核增加内部判定次数，减少的是跨层 transport。多 parent/长 UTF-8 路径或配置祖先边界会增加 native 分片数。

真实 Django ORM + MariaDB 10.11，测试每对象两标签。只统计标签 SELECT，不混入事务控制语句、ACL/identity SQL。

| N | UUID 旧→新 | bindings 旧→新 | definitions 旧→新额外 SQL | 标签 SELECT 总数旧→新 |
|---:|---:|---:|---:|---:|
| 1 | 1→1 | 1→1 JOIN | 2→0 | 4→2 |
| 20 | 20→1 | 20→1 JOIN | 40→0 | 80→2 |
| 50 | 50→1 | 50→1 JOIN | 100→0 | 200→2 |
| 100 | 100→2 | 100→2 JOIN | 200→0 | 400→4 |
| 200 | 200→4 | 200→4 JOIN | 400→0 | 800→8 |

一般形式：旧 N UUID + N bindings + T definitions，新 B UUID + B binding/definition JOIN。definitions 未取消读取，只合并到 JOIN。

## 验证与后续

- EAP：JDK/Maven 17 编译及专项测试；mock 计数、本地真实 HTTP Cookie/JSON/UTF-8、旧 scalar、capability、超时、异常协议、跨 repo 分开请求。
- Hub：cloudfile_ext 回归；纯 batch 测试以及隔离进程真实 legacy ORM/DRF 测试；SQLite 和 MariaDB 均验证 scalar/batch 等价、root/virtual repo、多 parent、deny/hidden/native folder、mixed、missing、重复 DTO 隔离、0/1/多标签、查询/返回行数限制、DB 异常回滚、native timeout/provider/坏响应、撤权与 head 改变丢弃结果。
- 未执行部署中完整 EAP→Hub→真实 native server 链路，未测 native C/会员/ACL 内部 SQL；ORM 的 native API、身份与 ACL snapshot 使用 fixture。没有毫秒级延迟承诺。
- 保留 O(N) 的对象存在性 RPC、两轮最终权限判断、native scalar 内部 SQL/hook；legacy writer 仍无统一 revision/lease。EAP 8 秒总预算在大 ACL/多组身份场景下需要现场确认。
- 建议先现场 profiling，核对真实网络、identity/ACL SQL、存在性 RPC 和超时占比，再决定 Task 4D lifecycle；本任务没有继续实施 4D。
