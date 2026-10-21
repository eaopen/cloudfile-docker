-- Development release SQL: reviewed 029/042 layout -> four-table V2 baseline.
-- Execute OFFLINE in the explicitly selected native Seafile database.
-- Set @cf_upgrade_writers_stopped=1 after stopping ALL writers.
-- If old lifecycle-bound ACLs exist, separately review/acknowledge the target
-- path-based semantics with @cf_upgrade_accept_path_acl=1.
-- Back up the database first. Never use mysql --force or automatic startup.
-- A single RENAME retains original tables; no DROP or automatic rollback.
DELIMITER $$
DROP PROCEDURE IF EXISTS cfv2_manual_upgrade_20261021$$
CREATE PROCEDURE cfv2_manual_upgrade_20261021()
main: BEGIN
 DECLARE acquired INT DEFAULT 0;
 DECLARE EXIT HANDLER FOR SQLEXCEPTION
 BEGIN
  DO RELEASE_LOCK('cloudfile.schema.manual.v2');
  RESIGNAL;
 END;
 IF DATABASE() IS NULL OR COALESCE(@cf_upgrade_writers_stopped,0) <> 1 THEN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Select the database, back up and stop all writers before manual SQL';
 END IF;
 IF COALESCE(@cf_upgrade_archive_database,'') NOT REGEXP '^[A-Za-z][A-Za-z0-9_]{0,63}$'
 OR @cf_upgrade_archive_database=DATABASE()
 OR NOT EXISTS(SELECT 1 FROM information_schema.schemata WHERE schema_name=@cf_upgrade_archive_database) THEN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Create and select a separate controlled archive database first';
 END IF;
 SELECT GET_LOCK('cloudfile.schema.manual.v2',0) INTO acquired;
 IF acquired <> 1 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Another manual schema operation is running'; END IF;
 -- No implicit conversion of unknown or already-upgraded schemas.
 IF (SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='cf_library_storage')<>3
 OR (SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='cf_sso_group_map')<>10
 OR (SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='cf_dir_acl')<>15
 OR (SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='cf_edit_guard')<>16
 OR NOT EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='cf_edit_guard' AND column_name='resource_uid')
 OR NOT EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='cf_dir_acl' AND column_name='subject_hash') THEN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Unsupported source layout or already upgraded; inspect instead of replaying';
 END IF;
 IF EXISTS(SELECT 1 FROM information_schema.key_column_usage WHERE referenced_table_schema=DATABASE() AND referenced_table_name IN ('cf_library_storage','cf_sso_group_map','cf_dir_acl','cf_edit_guard')) THEN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Foreign key dependency requires a separately reviewed migration';
 END IF;
 IF EXISTS(SELECT 1 FROM information_schema.tables WHERE (table_schema=DATABASE() AND table_name LIKE 'stage\_20261021\_cf\_%') OR (table_schema=@cf_upgrade_archive_database AND table_name LIKE 'backup\_20261021\_cf\_%')) THEN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Candidate or backup exists; inspect partial state and do not overwrite';
 END IF;
 IF EXISTS(SELECT 1 FROM cf_edit_guard) THEN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Guard data is not empty; preserve generation and design explicit lease conversion';
 END IF;
 IF EXISTS(SELECT 1 FROM cf_dir_acl WHERE kind<>'dir' OR CHAR_LENGTH(path)>4096 OR CHAR_LENGTH(namespace)>128 OR CHAR_LENGTH(external_id)>225 OR BINARY path_hash<>BINARY SHA2(path,256))
 OR EXISTS(SELECT 1 FROM cf_sso_group_map WHERE CHAR_LENGTH(namespace)>128 OR CHAR_LENGTH(external_id)>225 OR subject_type NOT IN ('org','role') OR group_id<=0) THEN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Source rows do not fit the target contract; no truncation or identity inference';
 END IF;
 IF EXISTS(SELECT 1 FROM cf_dir_acl WHERE lifecycle_ref<>'') AND COALESCE(@cf_upgrade_accept_path_acl,0)<>1 THEN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Review lifecycle-bound ACL conversion to path semantics before continuing';
 END IF;
 CREATE TABLE stage_20261021_cf_library_storage (
    repo_key VARCHAR(80) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    repo_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    state VARCHAR(8) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    PRIMARY KEY (repo_key),
    UNIQUE KEY library_storage_repo (repo_id),
    CONSTRAINT library_storage_state CHECK (state IN ('reserved','active','retired'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
 CREATE TABLE stage_20261021_cf_sso_group_map (
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
 CREATE TABLE stage_20261021_cf_dir_acl (
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
 CREATE TABLE stage_20261021_cf_edit_guard (
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
 INSERT INTO stage_20261021_cf_library_storage (repo_key,repo_id,state) SELECT repo_key,repo_id,state FROM cf_library_storage;
 INSERT INTO stage_20261021_cf_sso_group_map (provider,subject_type,namespace,external_id,group_id) SELECT provider,subject_type,namespace,external_id,group_id FROM cf_sso_group_map;
 INSERT INTO stage_20261021_cf_dir_acl (repo_id,path_hash,path,subject_type,provider,namespace,external_id,permission,inherit,share_mode,revision) SELECT repo_id,UNHEX(path_hash),path,subject_type,provider,namespace,external_id,permission,inherit,share_mode,revision FROM cf_dir_acl;
 IF (SELECT COUNT(*) FROM cf_library_storage)<>(SELECT COUNT(*) FROM stage_20261021_cf_library_storage) THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Candidate row count mismatch'; END IF;
 IF (SELECT COUNT(*) FROM cf_sso_group_map)<>(SELECT COUNT(*) FROM stage_20261021_cf_sso_group_map) THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Candidate row count mismatch'; END IF;
 IF (SELECT COUNT(*) FROM cf_dir_acl)<>(SELECT COUNT(*) FROM stage_20261021_cf_dir_acl) THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Candidate row count mismatch'; END IF;
 IF (SELECT COUNT(*) FROM cf_edit_guard)<>(SELECT COUNT(*) FROM stage_20261021_cf_edit_guard) THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Candidate row count mismatch'; END IF;
 IF EXISTS(SELECT 1 FROM cf_library_storage s LEFT JOIN stage_20261021_cf_library_storage n ON n.repo_key=s.repo_key WHERE n.repo_key IS NULL OR NOT ((n.repo_key <=> s.repo_key) AND (n.repo_id <=> s.repo_id) AND (n.state <=> s.state))) THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Candidate data mismatch'; END IF;
 IF EXISTS(SELECT 1 FROM cf_sso_group_map s LEFT JOIN stage_20261021_cf_sso_group_map n ON n.provider=s.provider AND n.subject_type=s.subject_type AND n.namespace=s.namespace AND n.external_id=s.external_id WHERE n.provider IS NULL OR NOT ((n.provider <=> s.provider) AND (n.subject_type <=> s.subject_type) AND (n.namespace <=> s.namespace) AND (n.external_id <=> s.external_id) AND (n.group_id <=> s.group_id))) THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Candidate data mismatch'; END IF;
 IF EXISTS(SELECT 1 FROM cf_dir_acl s LEFT JOIN stage_20261021_cf_dir_acl n ON n.repo_id=s.repo_id AND n.path_hash=UNHEX(s.path_hash) AND n.subject_type=s.subject_type AND n.provider=s.provider AND n.namespace=s.namespace AND n.external_id=s.external_id WHERE n.repo_id IS NULL OR NOT ((n.repo_id <=> s.repo_id) AND (n.path_hash <=> UNHEX(s.path_hash)) AND (n.path <=> s.path) AND (n.subject_type <=> s.subject_type) AND (n.provider <=> s.provider) AND (n.namespace <=> s.namespace) AND (n.external_id <=> s.external_id) AND (n.permission <=> s.permission) AND (n.inherit <=> s.inherit) AND (n.share_mode <=> s.share_mode) AND (n.revision <=> s.revision))) THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Candidate data mismatch'; END IF;
 -- All four names move atomically; old rows remain available for inspection.
 SET @cfv2_cutover_sql=CONCAT('RENAME TABLE ','cf_library_storage TO `',@cf_upgrade_archive_database,'`.`backup_20261021_cf_library_storage`',', ','stage_20261021_cf_library_storage TO cf_library_storage',', ','cf_sso_group_map TO `',@cf_upgrade_archive_database,'`.`backup_20261021_cf_sso_group_map`',', ','stage_20261021_cf_sso_group_map TO cf_sso_group_map',', ','cf_dir_acl TO `',@cf_upgrade_archive_database,'`.`backup_20261021_cf_dir_acl`',', ','stage_20261021_cf_dir_acl TO cf_dir_acl',', ','cf_edit_guard TO `',@cf_upgrade_archive_database,'`.`backup_20261021_cf_edit_guard`',', ','stage_20261021_cf_edit_guard TO cf_edit_guard');
 PREPARE cfv2_cutover FROM @cfv2_cutover_sql;
 EXECUTE cfv2_cutover;
 DEALLOCATE PREPARE cfv2_cutover;
 DO RELEASE_LOCK('cloudfile.schema.manual.v2');
 SELECT 'four-table upgrade complete; originals archived; archive other legacy tables then run 50-verify.sql' AS result;
END$$
CALL cfv2_manual_upgrade_20261021()$$
DROP PROCEDURE cfv2_manual_upgrade_20261021$$
DELIMITER ;
