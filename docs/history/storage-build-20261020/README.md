# 历史构建链归档

此目录保留旧 CE14 白名单叠加组装、独立 V2 DEV 启动器和旧原生构建入口，供追溯。
它们不再是可执行的当前构建流程，移动后的相对路径也不作为运行合同。
其中 source-set.json 的原 SHA 原样保留，未通过改旧 pin 修复当前构建。

当前唯一实现为根目录 release.yaml 与 build/cloudfile_14.0/cloudfile-build.sh；
容器包装器 build-in-docker.sh 和镜像包装器 docker-build.sh 使用同一份生成收据。
旧 build/seafile_14.0/release.json 从 Git 删除，构建按收据生成，禁止手工维护。
