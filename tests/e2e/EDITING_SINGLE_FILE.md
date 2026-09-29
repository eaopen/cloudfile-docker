# 单文件 Editing 验收

独立 Seafile native E2E 已通过，证据和限制见 [原生验收报告](EDITING_NATIVE_ACCEPTANCE.md)。下面是**尚未执行的完整产品 HTTP E2E**命令，不能将 native 验收替代真实 HTTPS/OIDC、CloudFile policy/resource runtime、浏览器或 Agent 验收。

复现原生验收（先完整构建 native backend；脚本只创建专用 MySQL/Redis/Server 实例，结束后移除测试容器）：

```bash
CF_NATIVE_BACKEND='/绝对路径/cloudfile-backend' \
CF_NATIVE_REPORT_DIR='/tmp/cloudfile-native-evidence' \
bash tests/e2e/native_editing.sh
```

要求 Docker、`cloudfile-build-base:ce14-v2`、已编译的 C Server/Go Fileserver，以及同一 workspace 的 Server/Hub 源码。测试身份、subject 和 session 为受信夹具；真实文件由原生 RPC 发布并通过 `/cloudfile/read` 下载。`native-result.json`、`build-info.txt` 和运行日志保留于报告目录。每次使用新的报告目录；无本次 production schema/RPC 时应 fail closed，不采用普通上传替代。

只在隔离的、已加载本次 Server/Hub 构建的 Seafile 测试栈执行。当前本地 `cloudfile-local-reference` 栈仍用旧镜像，且 `.env` / `.env.local-reference` 没有 `CLOUDFILE_OIDC_ENABLED`、`CLOUDFILE_POLICY_CONFIG_JSON`、`CLOUDFILE_POLICY_WORKER_HOOKS`、`CLOUDFILE_RESOURCE_SECRET`；因此不能把它当成本次真实 E2E 的通过证据，也不要在其中改写用户文件。

启用前确认迁移 `029_editing_core` 已应用、`CF_ENABLE_FILE_LOCK=true`、`CF_LOCK_BACKEND=cloudfile`、原生 OIDC 和策略 worker 可用，再在隔离栈设置 `CLOUDFILE_EDITING_ENABLED=true`。选择非虚拟、可写库里一份专用测试文件；两个 OIDC 用户都需有普通写权限。准备用户 A 的已登录 HTTPS Cookie 文件、CSRF 值，以及用户 A/B 的普通 Seafile API token。下面的变量和命令在**隔离栈**里运行：

```bash
export BASE_URL='https://isolated-cloudfile.example.test'
export REPO_ID='填入测试库 UUID'
export FILE_PATH='/editing-golden.txt'
export COOKIE_FILE='/tmp/cloudfile-editing-user-a.cookie'
export CSRF='填入用户 A 会话的 csrftoken'
export TOKEN_A='填入用户 A 普通 API token'
export TOKEN_B='填入用户 B 普通 API token'
export EDIT_URL="$BASE_URL/api/v2.1/cloudfile/extensions/editing/v1"
export PROOF="$(openssl rand -hex 32)"
printf 'editing second version\n' > /tmp/cloudfile-edit-S2.txt
printf 'editing third version\n' > /tmp/cloudfile-edit-S3.txt

export HEAD1="$(curl -fsS -b "$COOKIE_FILE" "$BASE_URL/api2/repos/$REPO_ID/" | jq -r .head_commit_id)"
export F1="$(curl -fsS -b "$COOKIE_FILE" --get --data-urlencode "p=$FILE_PATH" \
  "$BASE_URL/api2/repos/$REPO_ID/file/detail/" | jq -r .id)"
test "${#HEAD1}" -eq 40 && test "${#F1}" -eq 40

jq -n --arg repo "$REPO_ID" --arg path "$FILE_PATH" --arg base "$F1" --arg token "$PROOF" \
  '{reference:{repo_id:$repo,path:$path,kind:"file"},base_file_id:$base,token:$token}' \
  | curl -fsS -b "$COOKIE_FILE" -H "X-CSRFToken: $CSRF" -H 'Content-Type: application/json' \
      -H 'Idempotency-Key: checkout-1' --data-binary @- "$EDIT_URL/checkout/" \
  | tee /tmp/cloudfile-edit-checkout.json
export GUARD="$(jq -r .current_guard.guard_id /tmp/cloudfile-edit-checkout.json)"
export GENERATION="$(jq -r .current_guard.generation /tmp/cloudfile-edit-checkout.json)"
export EPOCH="$(jq -r .current_guard.credential_epoch /tmp/cloudfile-edit-checkout.json)"
export I1="$(python3 -c 'import uuid; print(uuid.uuid4())')"

curl -fsS -b "$COOKIE_FILE" -H "X-CSRFToken: $CSRF" -H 'Idempotency-Key: commit-1' \
  -F "repo_id=$REPO_ID" -F "path=$FILE_PATH" -F "guard_id=$GUARD" \
  -F "generation=$GENERATION" -F "credential_epoch=$EPOCH" -F "token=$PROOF" \
  -F "intent_id=$I1" -F "base_file_id=$F1" -F "head_id=$HEAD1" \
  -F 'action=commit' -F 'file=@/tmp/cloudfile-edit-S2.txt' \
  "$EDIT_URL/commit-file/" | tee /tmp/cloudfile-edit-I1.json
export F2="$(jq -r .intent.result_file_id /tmp/cloudfile-edit-I1.json)"
export HEAD2="$(jq -r .intent.result_commit_id /tmp/cloudfile-edit-I1.json)"
test "$(jq -r .intent.state /tmp/cloudfile-edit-I1.json)" = published
test "$F2" != "$F1"
export DOWNLOAD_S2="$(curl -fsS -b "$COOKIE_FILE" --get --data-urlencode "p=$FILE_PATH" \
  "$BASE_URL/api2/repos/$REPO_ID/file/" | jq -r .)"
curl -fsSL -b "$COOKIE_FILE" "$DOWNLOAD_S2" -o /tmp/cloudfile-edit-downloaded-S2.txt
cmp /tmp/cloudfile-edit-S2.txt /tmp/cloudfile-edit-downloaded-S2.txt

export I2="$(python3 -c 'import uuid; print(uuid.uuid4())')"
curl -fsS -b "$COOKIE_FILE" -H "X-CSRFToken: $CSRF" -H 'Idempotency-Key: commit-2' \
  -F "repo_id=$REPO_ID" -F "path=$FILE_PATH" -F "guard_id=$GUARD" \
  -F "generation=$GENERATION" -F "credential_epoch=$EPOCH" -F "token=$PROOF" \
  -F "intent_id=$I2" -F "base_file_id=$F2" -F "head_id=$HEAD2" \
  -F 'action=commit' -F 'file=@/tmp/cloudfile-edit-S3.txt' \
  "$EDIT_URL/commit-file/" | tee /tmp/cloudfile-edit-I2.json
export F3="$(jq -r .intent.result_file_id /tmp/cloudfile-edit-I2.json)"
export HEAD3="$(jq -r .intent.result_commit_id /tmp/cloudfile-edit-I2.json)"
test "$(jq -r .intent.state /tmp/cloudfile-edit-I2.json)" = published
test "$F3" != "$F2"

export I3="$(python3 -c 'import uuid; print(uuid.uuid4())')"
jq -n --arg repo "$REPO_ID" --arg path "$FILE_PATH" --arg guard "$GUARD" \
  --arg generation "$GENERATION" --arg epoch "$EPOCH" --arg token "$PROOF" \
  --arg intent "$I3" --arg base "$F3" --arg head "$HEAD3" \
  '{repo_id:$repo,path:$path,guard_id:$guard,generation:$generation,credential_epoch:$epoch,token:$token,intent_id:$intent,base_file_id:$base,head_id:$head}' \
  | curl -fsS -b "$COOKIE_FILE" -H "X-CSRFToken: $CSRF" -H 'Content-Type: application/json' \
      -H 'Idempotency-Key: checkin-3' --data-binary @- "$EDIT_URL/checkin/" \
  | tee /tmp/cloudfile-edit-I3.json
test "$(jq -r .intent.state /tmp/cloudfile-edit-I3.json)" = published
test "$(jq -r .intent.result_file_id /tmp/cloudfile-edit-I3.json)" = "$F3"

export FINAL_FILE_ID="$(curl -fsS -b "$COOKIE_FILE" --get --data-urlencode "p=$FILE_PATH" \
  "$BASE_URL/api2/repos/$REPO_ID/file/detail/" | jq -r .id)"
test "$FINAL_FILE_ID" = "$F3"
export DOWNLOAD_URL="$(curl -fsS -b "$COOKIE_FILE" --get --data-urlencode "p=$FILE_PATH" \
  "$BASE_URL/api2/repos/$REPO_ID/file/" | jq -r .)"
curl -fsSL -b "$COOKIE_FILE" "$DOWNLOAD_URL" -o /tmp/cloudfile-edit-final.txt
cmp /tmp/cloudfile-edit-S3.txt /tmp/cloudfile-edit-final.txt
```

分别在 Checkout 后、两次 Commit 后和 Checkin 后查询数据库。使用与 Seafile 同一库的只读账号执行，`published` 即 API 里的 COMMITTED 结果；两次 Commit 的 `result_commit_id` 应分别为 HEAD2/HEAD3，Checkin 无新内容时保持 HEAD3：

```sql
SELECT commit_id FROM Branch WHERE repo_id = '<REPO_ID>' AND name = 'master';
SELECT r.uid,g.guard_id,g.generation,g.mode,g.base_file_id,g.pending_intent
  FROM cf_resource r JOIN cf_edit_guard g ON g.resource_uid=r.uid
  WHERE r.repo_id='<REPO_ID>' AND r.path='<FILE_PATH>' AND r.state='active';
SELECT intent_id,action,state,expected_file_id,result_file_id,result_commit_id
  FROM cf_commit_intent WHERE intent_id IN ('<I1>','<I2>','<I3>');
```

期望状态：Checkout 后 `mode=checkout,base_file_id=F1`；I1 后 `state=published,base_file_id=F2,pending_intent=NULL,guard_id` 未变；I2 后基线为 F3；I3 后 `state=published,result_file_id=F3,guard_id=NULL,pending_intent=NULL`。所有回执的 commit/file ID 必须与 Seafile 当前下载及 Branch 可见版本一致。block/fs/commit 预写对象在 Branch 拒绝时允许不可达，由 GC 清理。

在 I1 前分别用用户 A/B 的普通 update-link 覆盖同一文件，应均被拒绝；可沿用 `tests/e2e/fileop_matrix.py` 的 `update()` 请求格式。另用旧 F1 对 I2 的 Commit 发起请求，预期冲突且原 guard/未决 intent 保留。最后在一次真实 Commit 已成功但 HTTP 客户端主动断开后，以同一 `intent_id` 调用 `status/`，核对原 `result_file_id/result_commit_id`；重发相同内容和 `Idempotency-Key` 不得产生第二个 Branch 版本。Checkin 响应丢失也以同一 I3 查询和重试，应该返回原回执。若任一项不能实际核验，记录其具体失败响应和对应数据库/Branch 状态，不标记 foundation frozen。
