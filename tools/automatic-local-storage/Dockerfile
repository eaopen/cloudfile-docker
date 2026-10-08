ARG CLOUDFILE_BASE
FROM ${CLOUDFILE_BASE}
# Keep the existing OAuth/search/frontend layers. Only replace the native
# storage consumers and the corresponding Python routing surface.
COPY payload /tmp/automatic-local-storage
RUN python3 /tmp/automatic-local-storage/apply.py && rm -rf /tmp/automatic-local-storage
LABEL com.sec.etech.automatic-storage="key-root-v1"
