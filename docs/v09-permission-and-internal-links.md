# CloudFile v0.9: library, directory, lightweight sharing, internal links

CloudFile has one permission model. No virtual repositories, standalone
directory-share grants, link bearer tokens, additional ACL tables, or
Etech-specific policy mode are needed for directory entry authorization.

## Permissions

| Layer | Authority | Rule |
| --- | --- | --- |
| Library | Native Seafile CE owner, user/group sharing and library administration | Preserve Seafile API and r/rw semantics; CloudFile system_admin implicit rw remains separately gated by account status and directory ACL |
| Subdirectory | Versioned cf_dir_acl | Pro-like path inheritance/override: r, rw, none, invisible, user and department/group subjects |
| Lightweight share | The same cf_dir_acl row with share_mode=1 | Allows directory qualification without library membership, not a separate permission grant or virtual repo; actual r/rw/inherit and account/lifecycle rules still decide access |
| Internal link | Existing authenticated Seafile Smart Link (FileUUIDMap) | Location only. Opening re-evaluates current library/directory qualification; link possession never gives permission |

Library-qualified users browse from / (if their current ACL permits).
Directory-only users browse from the narrowest applicable shared root; the
server returns root_path, initial_path and effective permission. Parent
and sibling folders remain unavailable. A real invisible ancestor denies
direct access. Sharing can be disabled without erasing the ordinary ACL;
removing the ACL also revokes the associated sharing. Deleting/recreating a
directory invalidates lifecycle-bound sharing.

## Current implementation

- Shared discovery: GET /api/v2.1/cloudfile/extensions/authorization/v1/shared-directories/
- Address resolution: GET /api/v2.1/cloudfile/extensions/authorization/v1/directory-address/?repo_id=...&path=...&kind=dir
- Scoped paging: GET /api/v2.1/cloudfile/extensions/authorization/v1/directory-entries/
- These read-only endpoints are exposed under both current native OAuth
  adapter and hosted policy adapter. No new Etech login/configuration required.
- The existing Seafile GET /api/v2.1/smart-link/ remains the locator creator.
  Directory creation and GET /api/v2.1/smart-links/{token}/ now use scoped ACL
  when native CE permission is denied. Token lookup adds root_path,
  initial_path, permission without altering repo_id, path or is_dir fields.
  Plain CE libraries and ordinary file links retain previous behavior.
- CloudFile directory-rule UI defaults non-root ACL entry to share_mode=1,
  suitable for Etech. Generic API writes omitting the field default to 0 and
  edits preserve the previous choice. Other deployments may disable per rule.
- Native cf_acl_evaluate_scoped is final directory evaluator. Do not
  resurrect retired v0.8 resolution or independent cf_dir_share implementation.

## RC boundary: not yet accepted

This patch connects URL/API metadata and current authentication adapters,
not a new FileServer authorization proof. Legacy native guards still
refuse unverifiable file reads/writes after cf_managed_library enrollment.
Old smart-link browser navigation may still need root-aware UI when the
recipient lacks library membership. The token API supplies the narrow root,
but does not by itself make the old Seafile library-page UI usable.

Do not disable legacyLibraryAllowed or cf_policy_check_legacy_library,
or remove managed-library markers to make old uploads/downloads pass.
Server-owned proof, native final writes/bytes and DEV E2E are RC P0,
tracked by docs/rc-unified-authorization.md.
