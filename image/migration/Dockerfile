FROM ubuntu:24.04

# The official CLI AppImage contains the sync daemon. Extracting it at build
# time avoids FUSE/device privileges in the migration container.
ENV DEBIAN_FRONTEND=noninteractive TZ=Etc/UTC
RUN apt-get update && apt-get install -y --no-install-recommends \
      bash ca-certificates python3 util-linux && \
    rm -rf /var/lib/apt/lists/*

ADD --checksum=sha256:5dc112e99fd0daaafc06f284958ebf587613fecc15366c0017b9f0116b7a74af \
    https://sos-ch-dk-2.exo.io/seafile-downloads/Seafile-cli-x86_64-9.0.21.AppImage \
    /tmp/seaf-cli.AppImage

RUN chmod +x /tmp/seaf-cli.AppImage && \
    cd /tmp && ./seaf-cli.AppImage --appimage-extract >/dev/null && \
    mv /tmp/squashfs-root /opt/seaf-cli && \
    rm /tmp/seaf-cli.AppImage && \
    ln -s /opt/seaf-cli/AppRun /usr/local/bin/seaf-cli

ENV APPDIR=/opt/seaf-cli \
    PATH=/usr/local/sbin:/usr/local/bin:/opt/seaf-cli/usr/bin:/usr/sbin:/usr/bin:/sbin:/bin

COPY image/migration/entrypoint.sh /usr/local/bin/cf-migration
RUN chmod +x /usr/local/bin/cf-migration

ENTRYPOINT ["/usr/local/bin/cf-migration"]
