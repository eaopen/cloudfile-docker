# 当前存储构建与验收

当前唯一实现为 `release.yaml` + `build/cloudfile_14.0/cloudfile-build.sh`。
`build-in-docker.sh` 只包装同一实现，使用已有 CE14 Linux 工具链与持久缓存；
`image/cloudfile_14.0/docker-build.sh` 验证同一收据及产物后构建测试镜像，不推送或部署。

```sh
bash build/cloudfile_14.0/build-in-docker.sh 14.0.8-storage-test
bash image/cloudfile_14.0/docker-build.sh 14.0.8-storage-test
```

构建开始对三仓分支各执行一次远端 `git ls-remote --exit-code`，默认均为 `dev`。
远端失败即停止，不采用缓存分支或历史锁。随后仅按生成的 40 位 SHA 获取源码，
已缓存的同 SHA 对象与工具链可复用。PR 测试可显式设置 `CF_SERVER_REF`、
`CF_HUB_REF`、`CF_DOCKER_REF` 为对应短分支；当前 Docker 工作树必须干净且
恰好等于解析出的 Docker SHA。

`build/cloudfile_14.0/build-receipt.json` 包括三仓 SHA、五项 CE 依赖 SHA、
执行命令/状态/日志 SHA256 和镜像摘要。原 `build/seafile_14.0/release.json`
从同一收据生成，不再手工维护或用其旧 pin 校验当前构建。
已解析收据可通过 `CF_BUILD_RECEIPT=/absolute/path/build-receipt.json` 供后续阶段消费；
此时不得重新解析浮动分支。收据与编译日志都属于构建产物，不提交 Git。

镜像未推送注册表时，`image.digest` 是本地 image config 的 SHA256，
`digest_kind=local-image-config`；`repo_digests` 原样记录已存在的注册表摘要。
不把本地 image ID 冒称注册表 manifest digest。

完整构建在编译前执行 `bash tests/local_storage/run.sh` 与
`cd fileserver && go test -v ./objstore/... -count=1`；失败写入收据并停止。
缓存命中也需要本次测试证据，旧产物必须通过原有字节记录才能继续组装。
`workflow_dispatch` 的 `CloudFile receipt build` 单独运行完整编译和 Linux
特权挂载任务，push/PR 只跑轻量源码检查。

Linux 特权任务使用临时挂载命名空间和 `CF_TEST_BIND_MOUNTS=1`，覆盖存储类、
库、分片三层挂载。数据、Repo ID、原生对象格式与旧存储登记表均不在构建中变更。

旧白名单组装及独立 DEV 启动器归档于
`docs/history/storage-build-20261020/`。旧 feature 分支的配置块位置保留、Web
console 启动文件检查在当前 dev 重新实现；旧 release pin 与平行 native permission
API 不搬入。旧 feature 分支不会自动合并或更名。

DEV 真实数据核对与旧库上传、下载、历史、恢复、回收站、GC dry-run、fsck
按用户后续指示在发布后单独验收；构建和隔离测试不能替代该验收。
