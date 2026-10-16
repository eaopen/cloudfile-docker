# CloudFile V2 repository working rules

The official upstream CE14 source is the baseline; keep the smallest reviewed CloudFile extension surface.

## CloudFile dev branch: V2.0 only (2026-10-16)

- `dev` is the active **fresh CE14-based CloudFile V2.0** development line. The former v0.9 `dev` source was preserved at `archive/v0.9-dev-20261016` and is no longer an active feature-development baseline. `dev2-clean` remains the explicit source of the V2 promotion.
- Work **only on explicitly approved MVP tasks and directly blocking, minimal correctness/build/test fixes**. Discoveries, performance ideas, extra compatibility, optional API features, additional tables, refactors or improvements **must be recorded for separate user confirmation, not implemented opportunistically**. Existing roadmaps are not development authorization.
- Native Seafile CE14 data and APIs are primary. Exactly three V2 core extension tables have been approved: `cf_library_storage`, `cf_dir_acl`, and `cf_sso_group_map`. No other custom table is pre-approved. Never restore v0.9's 001–042 extension migrations, managed-library guard, independent directory-share/admin tables, legacy task/outbox or old synchronous sharing ledger merely to satisfy an old caller.
- Preserve the source SHA pins in Docker `build/v2/source-set.json`, and keep tests honest: isolated schema/identity and native C/Go byte tests do **not** certify full Seahub Web, OIDC/SSO, scoped ACL final-commit checks, or external application integration.
- The Git branch promotion changes **no databases, file objects, existing containers, registry tags, or deployed hosts**. A new DEV deployment must use a separate backed-up data/config environment and explicit operational validation; do not reuse or overwrite existing v0.9 production volumes by inference.


## Search feature branch exception (2026-10-16)

- The user explicitly authorized `feature/v2-meilisearch` for independent Search development **on this branch only**. `dev` continues the existing Etech MVP and must not receive Search code or deployments before real DEV MVP acceptance.
- Follow the internal [Search feature-branch gate](https://github.com/eaopen/eap-cloudfile/blob/dev/docs/v2.0/meilisearch-feature-branch-20261016.md) (private planning reference). Search may reuse native CE Repo/FS/Tag data, the existing V2 authorization boundary, and a single disposable Meilisearch index. No new SQL tables, `cf_resource`, legacy index/task/outbox schema, or Etech-specific microservice.
- Development may run isolated offline unit tests and separate integration environments. Never point a development Meilisearch job at current DEV/PROD data or containers without separate explicit authorization.
- Keep a clear distinction between isolated tests and genuine CE14/SSO/scoped ACL/Etech integration. Before any eventual merge to `dev`, verify Etech DEV MVP acceptance, test the feature against the now-current base, review schema invariants and obtain explicit merge approval. Do not enable automatic merging.
