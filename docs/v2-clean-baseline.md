# V2 clean work branch — Etech MVP selective port

CE14 upstream pins (2026-10-16): Server `b6179eb3d73b04c67a00412ebaf964153c4ad2c0`, Hub `15ec1aa7114c013929509e0aad756b5365a29ce6`, Docker `822c24c9908c4cc9f602987fcf8bc362d3f0454e`.

Historical `dev2` was preserved in `archive/dev2-m1-20261016` in each repository. This Docker branch starts from the exact upstream commit, not the historic CloudFile Docker tree. It copies **only** explicit V2 source assembly, isolated schema/identity tests, the native CE build script and reviewed documentation. The previous `dev2.yml`, legacy release.yaml, migration chain and v0.9 build scripts are **not** a V2 artifact.

V2 extension overlay pins: Server `7c32cd5bce0ec04e30b2494c8f9b9a4af7c2e01b`, Hub `dbc3c1f2d303bde9ebada950ff1b6c87d4c3f75d`. Locking is enforced by `prepare-v2-source.py`; the assembled source receipt gives the selected native and overlay SHAs and file hashes. No floating upstream refs are accepted.

**Implemented source:** Independent V2 DDL defining only `cf_library_storage`, `cf_dir_acl`, `cf_sso_group_map`; independent native UID/GroupUser TTL adapters; tests for native CE database compatibility and no dependency on legacy runtime. These are not yet installed as operational CloudFile services.

**Not implemented/accepted:** live Authentik login in the new Hub, real Server/Fileserver directory ACL hooks, automatic library storage routing, CloudFile-scoped read/write/final-Commit, Etech Web/BPM end-to-end operations, packaged 2.0 image or PROD rollout. The `dev2-clean` CI is an isolated source/schema gate; do not publish a release based on this alone.

Next select reviewed, small C/Go library-storage and ACL patches from archived `dev2` only after verifying their CE 14 diff; add a user-facing OIDC/Directory adapter; then run real Etech DEV full file-byte acceptance. Continue to leave v0.9 `dev` and old `dev2` unchanged.
