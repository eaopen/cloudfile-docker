ARG CLOUDFILE_BASE=cloudfile-build-base:ce14-v2
FROM ${CLOUDFILE_BASE}
ARG server_version=
ENV SEAFILE_SERVER=seafile-server SEAFILE_VERSION=$server_version

# The base image owns Ubuntu, APT, Node and Python dependencies. This
# application image performs no network-dependent package installation.

# Scripts
COPY scripts/scripts_14.0 /scripts
COPY services /services

RUN mkdir -p /etc/ldap/ && echo "TLS_REQCERT     allow" >> /etc/ldap/ldap.conf && \
    echo "TLS_CACERT     /etc/ssl/certs/ca-certificates.crt" >> /etc/ldap/ldap.conf && \
    chmod u+x /scripts/* && rm /scripts/cluster* && \
    mkdir -p /etc/my_init.d && \
    rm -f /etc/my_init.d/* && \
    cp /scripts/create_data_links.sh /etc/my_init.d/01_create_data_links.sh && \
    mkdir -p /etc/service/nginx && \
    mkdir -p /etc/nginx/sites-enabled && mkdir -p /etc/nginx/sites-available && \
    rm -f /etc/nginx/sites-enabled/* /etc/nginx/conf.d/* && \
    mv /services/nginx.conf /etc/nginx/nginx.conf && \
    mv /services/nginx.sh /etc/service/nginx/run && \
    mv /services/seafile.nginx.conf /etc/nginx/sites-enabled/seafile.nginx.conf
ENV MARIADB_TLS_DISABLE_PEER_VERIFICATION=1

# CloudFile
#
# The build tree keeps upstream's seafile-server-<version> directory name: the
# release layout, seafile.sh, seahub.sh and the bootstrap scripts all derive
# paths from SEAFILE_SERVER, and renaming it would mean patching all of them
# for no gain.
WORKDIR /opt/seafile
COPY --from=cloudfile_dist . /opt/seafile/seafile-server-${SEAFILE_VERSION}

# A background worker runs in a separate container. Keep the Seafile RPC
# socket in the shared data volume when SEAFILE_RPC_PIPE_PATH is supplied, so
# both containers can use the same server-side RPC endpoint.
RUN sed -i 's|seafile_rpc_pipe_path=${INSTALLPATH}/runtime|seafile_rpc_pipe_path=${SEAFILE_RPC_PIPE_PATH:-${INSTALLPATH}/runtime}|' \
      /opt/seafile/seafile-server-${SEAFILE_VERSION}/seafile.sh \
      /opt/seafile/seafile-server-${SEAFILE_VERSION}/seahub.sh \
      /opt/seafile/seafile-server-${SEAFILE_VERSION}/seafile-monitor.sh

EXPOSE 80

CMD ["/sbin/my_init", "--", "/scripts/enterpoint.sh"]
