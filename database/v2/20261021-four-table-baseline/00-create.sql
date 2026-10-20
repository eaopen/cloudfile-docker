-- New installation only. Select the native Seafile database explicitly.
-- Do not use IF NOT EXISTS: a colliding old layout must stop installation.
-- CloudFile V2 fresh schema. Native CE tables remain the authoritative facts.
-- This file is independent of cloudfile.sql and the legacy migration chain.

CREATE TABLE cf_library_storage (
    repo_key VARCHAR(80) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    repo_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    state VARCHAR(8) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    PRIMARY KEY (repo_key),
    UNIQUE KEY library_storage_repo (repo_id),
    CONSTRAINT library_storage_state CHECK (state IN ('reserved','active','retired'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE cf_sso_group_map (
    provider VARCHAR(32) COLLATE utf8mb4_bin NOT NULL,
    subject_type VARCHAR(4) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    namespace VARCHAR(128) COLLATE utf8mb4_bin NOT NULL,
    external_id VARCHAR(225) COLLATE utf8mb4_bin NOT NULL,
    group_id BIGINT NOT NULL,
    PRIMARY KEY (provider,subject_type,namespace,external_id),
    UNIQUE KEY sso_native_group (group_id),
    CONSTRAINT sso_group_type CHECK (subject_type IN ('org','role')),
    CONSTRAINT sso_group_id CHECK (group_id > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE cf_dir_acl (
    repo_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    path_hash BINARY(32) NOT NULL,
    path VARCHAR(4096) COLLATE utf8mb4_bin NOT NULL,
    subject_type VARCHAR(4) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    provider VARCHAR(32) COLLATE utf8mb4_bin NOT NULL,
    namespace VARCHAR(128) COLLATE utf8mb4_bin NOT NULL,
    external_id VARCHAR(225) COLLATE utf8mb4_bin NOT NULL,
    permission VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    inherit TINYINT NOT NULL,
    share_mode TINYINT NOT NULL,
    revision CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    PRIMARY KEY (repo_id,path_hash,subject_type,provider,namespace,external_id),
    KEY acl_shared_subject (provider,subject_type,namespace,external_id,share_mode,repo_id),
    CONSTRAINT acl_subject_type CHECK (subject_type IN ('user','org','role')),
    CONSTRAINT acl_permission CHECK (permission IN ('r','rw','invisible')),
    CONSTRAINT acl_inherit CHECK (inherit IN (0,1)),
    CONSTRAINT acl_share CHECK (share_mode IN (0,1) AND
        (share_mode=0 OR (permission IN ('r','rw') AND path <> '/')))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- CloudFile V2 optional Rust local editing. Fresh isolated CF-EDIT installations ONLY.
-- The three-table V2 MVP remains unchanged unless editing is explicitly enabled.
-- There is NO server-side Intent or editing Session table. Seafile keeps native
-- File/Block/Commit/Branch versions; Agent Rust keeps its local pending Journal.
-- One row per physical file path preserves generation across Checkout cycles.
CREATE TABLE cf_edit_guard (
    repo_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    path_hash BINARY(32) NOT NULL,
    path VARCHAR(4096) COLLATE utf8mb4_bin NOT NULL,
    guard_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NULL,
    generation BIGINT UNSIGNED NOT NULL DEFAULT 0,
    owner_uid VARCHAR(225) COLLATE utf8mb4_bin NULL,
    owner_native_user VARCHAR(255) COLLATE utf8mb4_bin NULL,
    terminal_type VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NULL,
    terminal_name VARCHAR(128) COLLATE utf8mb4_bin NULL,
    checkout_ip VARCHAR(45) CHARACTER SET ascii COLLATE ascii_bin NULL,
    proof_digest CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL,
    base_file_id CHAR(40) CHARACTER SET ascii COLLATE ascii_bin NULL,
    lease_expires_at DATETIME(6) NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (repo_id, path_hash),
    UNIQUE KEY cf_edit_guard_id (guard_id),
    KEY cf_edit_guard_active (repo_id, guard_id),
    KEY cf_edit_guard_owner (owner_uid, guard_id),
    CONSTRAINT cf_edit_terminal_type CHECK (
        terminal_type IS NULL OR terminal_type IN ('windows','macos','linux','other')
    ),
    CONSTRAINT cf_edit_active_shape CHECK (
        (guard_id IS NULL AND owner_uid IS NULL AND owner_native_user IS NULL
         AND proof_digest IS NULL AND base_file_id IS NULL AND lease_expires_at IS NULL)
        OR
        (guard_id IS NOT NULL AND owner_uid IS NOT NULL AND owner_native_user IS NOT NULL
         AND proof_digest IS NOT NULL AND base_file_id IS NOT NULL AND lease_expires_at IS NOT NULL)
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
