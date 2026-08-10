#!/bin/bash
#
# 鍦?Ubuntu 瀹瑰櫒閲岃窇 cloudfile-build.sh锛屼笉鍦ㄥ涓绘満涓婅浠讳綍涓滆タ銆?
#
# cloudfile-build.sh 浼?apt-get install 涓€鏁村 C/Go 宸ュ叿閾撅紝鍙兘鍦?Ubuntu 涓婅窇銆?
# 鎶婂畠鏀捐繘瀹瑰櫒锛宮acOS / 浠绘剰鍙戣鐗堥兘鑳芥瀯寤猴紝涓斿涓绘満淇濇寔骞插噣銆?
#
#   ./build-in-docker.sh 14.0.0-cf.0
#   CF_HUB_REF=feature/x ./build-in-docker.sh 14.0.0-cf.0-dev
#   CF_PLATFORM=linux/amd64 ./build-in-docker.sh 14.0.0-cf.0
#
# 浜х墿钀藉湪 build/cloudfile_14.0/seafile-server-<version>/锛屾帴鐫€鍙互锛?
#   ../../image/cloudfile_14.0/docker-build.sh <version>
#
# 鏋舵瀯璇存槑锛氶粯璁よ窡闅忓涓绘満銆侫pple Silicon 涓婂師鐢熸瀯寤?arm64 寰堝揩锛涜鍑?amd64
# 闀滃儚灏辫 CF_PLATFORM=linux/amd64锛岃蛋 QEMU 妯℃嫙锛屾參寰堝浣嗗彲鐢ㄣ€備笂娓哥殑 arm
# 涓?x86 Dockerfile 瀹屽叏鐩稿悓锛屾墍浠ラ暅鍍忓眰闈笉闇€瑕佸尯鍒嗐€?

set -e

if [[ $# != 1 ]]; then
    echo ''
    echo 'Usage: ./build-in-docker.sh $version'
    echo ''
    exit 1
fi

version=$1
here=$(cd "$(dirname "$0")" && pwd)
repo_root=$(cd "$here/../.." && pwd)

# 蹇呴』鏄惧紡鎸囧畾骞冲彴銆備笉鎸囧畾鐨勮瘽 docker 浼氭部鐢ㄦ湰鍦扮宸х紦瀛樼殑 ubuntu:24.04鈥斺€?
# 濡傛灉閭ｆ槸 amd64 鑰屽涓绘槸 Apple Silicon锛屾瀯寤哄氨浼氶潤榛樺湴璺戝湪 QEMU 妯℃嫙涓嬶紝
# 鎱竴涓暟閲忕骇鍗存病鏈変换浣曟彁绀恒€傞粯璁よ窡闅忓涓绘満銆?
if [[ -z ${CF_PLATFORM:-} ]]; then
    case "$(uname -m)" in
        arm64|aarch64) CF_PLATFORM=linux/arm64 ;;
        x86_64)        CF_PLATFORM=linux/amd64 ;;
        *) echo "鏃犳硶璇嗗埆鐨勫涓绘灦鏋勶細$(uname -m)锛岃鏄惧紡璁剧疆 CF_PLATFORM" >&2; exit 2 ;;
    esac
fi
platform=$CF_PLATFORM
platform_arg=(--platform "$platform")

if ! docker info >/dev/null 2>&1; then
    echo "Docker 涓嶅彲鐢ㄣ€傝鍏堝惎鍔?Docker Desktop / OrbStack / colima銆? >&2
    exit 2
fi

# 鎶婂彲瑕嗙洊鐨?ref 閫忎紶杩涘鍣紝鏂逛究鏋勫缓鐗规€у垎鏀€?
env_args=()
for v in CF_SERVER_REF CF_HUB_REF CF_SERVER_URL CF_HUB_URL \
         CF_SEAFOBJ_REF CF_SEAFDAV_REF CF_SEAFEVENTS_REF \
         CF_LIBSEARPC_REF CF_LIBEVHTP_REF; do
    [[ -n ${!v:-} ]] && env_args+=(-e "$v=${!v}")
done

# 鏈湴婧愮爜鐩綍锛氭妸瀹冩寕杩涘鍣紝鍚﹀垯瀹瑰櫒閲屽彧鏈?cloudfile-docker銆?
#
# 娌℃湁杩欎竴娈电殑璇濓紝**灏氭湭 push 鐨勫垎鏀牴鏈棤娉曞湪鏈湴楠岃瘉**鈥斺€旀瀯寤哄彧浼氬幓
# GitHub 涓婃壘閭ｄ釜涓嶅瓨鍦ㄧ殑鍒嗘敮銆傝€?鍏堝湪鏈湴璺戜竴閬嶅畬鏁撮棬绂侊紝鍒嬁 CI 褰撹皟璇曞櫒"
# 姝ｆ槸 verify-local.sh 瀛樺湪鐨勫叏閮ㄧ悊鐢憋紝鎵€浠ヨ繖涓己鍙ｅ繀椤昏ˉ涓娿€?
#
#   CF_SERVER_URL=../../cloudfile-server CF_HUB_URL=../../cloudfile-hub \
#     ./build-in-docker.sh 14.0.0-cf.0-local
#
# 鐢?file:// 鑰屼笉鏄８璺緞锛歡it clone 瀵规湰鍦拌矾寰勯粯璁よ蛋纭摼鎺ワ紝鑰屾簮鐩綍鏄彧璇?
# 鎸傝浇锛岃法鎸傝浇杈圭晫寤虹‖閾炬帴浼氬け璐ャ€俧ile:// 寮哄埗璧版甯哥殑瀵硅薄鎷疯礉銆?
#
# 鍓綔鐢ㄦ槸**鍙湁宸叉彁浜ょ殑浠ｇ爜浼氳繘鏋勫缓**鈥斺€斿伐浣滃尯閲屾病 commit 鐨勬敼鍔ㄤ笉鍙備笌銆?
# 杩欐槸濂戒簨锛氭瀯寤虹粨鏋滀笌鏌愪釜 commit 涓€涓€瀵瑰簲锛屽惁鍒?杩欎釜闀滃儚鏄摢鏉ョ殑"鏃犳硶鍥炵瓟銆?
mount_args=()
for v in CF_SERVER_URL CF_HUB_URL; do
    src=${!v:-}
    [[ -n $src && -d $src ]] || continue
    abs=$(cd "$src" && pwd)
    name=$(basename "$abs")
    mount_args+=(-v "$abs:/src/$name:ro")
    # 瑕嗙洊鍓嶉潰閭ｄ竴杞杩涘幓鐨勫涓绘満璺緞
    env_args+=(-e "$v=file:///src/$name")
    echo "鏈湴婧愮爜锛?v = ${abs}锛堝鍣ㄥ唴 /src/${name}锛屽彧璇伙級"
done

echo "鍦ㄥ鍣ㄥ唴鏋勫缓 CloudFile ${version}${platform:+ (${platform})}"
echo "瀹夸富鏈轰笉浼氳鏀瑰姩锛涗骇鐗╁啓鍥?build/cloudfile_14.0/"
echo

# 鎸傝浇鏁翠釜浠撳簱锛氭瀯寤鸿剼鏈璇?release.yaml锛屼骇鐗╀篃瑕佸啓鍥?build/cloudfile_14.0/銆?
# git 闇€瑕佹妸鎸傝浇杩涙潵鐨勭洰褰曟爣璁颁负 safe锛屽惁鍒欎細鍥?owner 涓嶄竴鑷存嫆缁濇搷浣溿€?
docker run --rm -i \
    "${platform_arg[@]}" \
    "${env_args[@]}" \
    "${mount_args[@]+"${mount_args[@]}"}" \
    -v "$repo_root:/work" \
    -w /work/build/cloudfile_14.0 \
    ubuntu:24.04 \
    bash -c "
        set -e
        export DEBIAN_FRONTEND=noninteractive
        export TZ=Etc/UTC
        apt-get update -qq
        apt-get install -y -qq git python3 ca-certificates >/dev/null
        git config --global --add safe.directory '*'
        ./cloudfile-build.sh '$version'
    "

echo
echo "瀹屾垚锛?here/seafile-server-${version}"
echo "涓嬩竴姝ワ細$repo_root/image/cloudfile_14.0/docker-build.sh $version"
