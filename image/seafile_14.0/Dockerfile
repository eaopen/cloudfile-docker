ARG CLOUDFILE_RUNTIME_BASE=cloudfile/runtime-base:14.0.8-local
FROM ${CLOUDFILE_RUNTIME_BASE}
ARG server_version=
ENV SEAFILE_SERVER=seafile-server SEAFILE_VERSION=$server_version

# CE14 system/Python dependencies belong to Dockerfile.runtime-base.
# Daily application image assembly performs no APT/pip installation.

# Scripts
COPY scripts_14.0 /scripts
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

# Seafile
WORKDIR /opt/seafile
COPY seafile-server-${SEAFILE_VERSION} /opt/seafile/seafile-server-${SEAFILE_VERSION}

EXPOSE 80

CMD ["/sbin/my_init", "--", "/scripts/enterpoint.sh"]
