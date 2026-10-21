-- Explicit target verification. Read-only against business tables.
-- A short-lived stored routine provides SIGNAL on mismatch, not a new ledger.
-- Run with the mysql/mariadb client in batch mode WITHOUT --force.
DELIMITER $$
DROP PROCEDURE IF EXISTS cfv2_verify_20261021$$
CREATE PROCEDURE cfv2_verify_20261021()
BEGIN
 IF DATABASE() IS NULL THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Select the native Seafile database'; END IF;
 IF EXISTS(SELECT 1 FROM information_schema.tables WHERE table_schema=DATABASE()
 AND LOWER(LEFT(table_name,2))='cf' AND table_name NOT IN
 ('cf_library_storage','cf_dir_acl','cf_sso_group_map','cf_edit_guard')) THEN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Historical CloudFile tables must be outside the runtime database';
 END IF;

 IF NOT ((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='cf_library_storage')=3
 AND EXISTS(SELECT 1 FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name='cf_library_storage' AND engine='InnoDB' AND table_collation='utf8mb4_bin')
 AND EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='cf_library_storage' AND column_name='repo_key' AND data_type='varchar' AND is_nullable='NO' AND character_maximum_length=80 AND collation_name='ascii_bin')
 AND EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='cf_library_storage' AND column_name='repo_id' AND data_type='char' AND is_nullable='NO' AND character_maximum_length=36 AND collation_name='ascii_bin')
 AND EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='cf_library_storage' AND column_name='state' AND data_type='varchar' AND is_nullable='NO' AND character_maximum_length=8 AND collation_name='ascii_bin')
 AND (SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name='cf_library_storage' AND index_name='PRIMARY')=1
 AND (SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name='cf_library_storage' AND index_name='PRIMARY' AND non_unique=0 AND sub_part IS NULL AND ((seq_in_index=1 AND column_name='repo_key')))=1
 AND (SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name='cf_library_storage' AND index_name='library_storage_repo')=1
 AND (SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name='cf_library_storage' AND index_name='library_storage_repo' AND non_unique=0 AND sub_part IS NULL AND ((seq_in_index=1 AND column_name='repo_id')))=1
 AND EXISTS(SELECT 1 FROM information_schema.table_constraints WHERE constraint_schema=DATABASE() AND table_name='cf_library_storage' AND constraint_name='library_storage_state' AND constraint_type='CHECK')) THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Target contract mismatch: cf_library_storage'; END IF;
 SELECT 'cf_library_storage verified' AS result;
 IF NOT ((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='cf_sso_group_map')=5
 AND EXISTS(SELECT 1 FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name='cf_sso_group_map' AND engine='InnoDB' AND table_collation='utf8mb4_bin')
 AND EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='cf_sso_group_map' AND column_name='provider' AND data_type='varchar' AND is_nullable='NO' AND character_maximum_length=32 AND collation_name='utf8mb4_bin')
 AND EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='cf_sso_group_map' AND column_name='subject_type' AND data_type='varchar' AND is_nullable='NO' AND character_maximum_length=4 AND collation_name='ascii_bin')
 AND EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='cf_sso_group_map' AND column_name='namespace' AND data_type='varchar' AND is_nullable='NO' AND character_maximum_length=128 AND collation_name='utf8mb4_bin')
 AND EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='cf_sso_group_map' AND column_name='external_id' AND data_type='varchar' AND is_nullable='NO' AND character_maximum_length=225 AND collation_name='utf8mb4_bin')
 AND EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='cf_sso_group_map' AND column_name='group_id' AND data_type='bigint' AND is_nullable='NO')
 AND (SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name='cf_sso_group_map' AND index_name='PRIMARY')=4
 AND (SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name='cf_sso_group_map' AND index_name='PRIMARY' AND non_unique=0 AND sub_part IS NULL AND ((seq_in_index=1 AND column_name='provider') OR (seq_in_index=2 AND column_name='subject_type') OR (seq_in_index=3 AND column_name='namespace') OR (seq_in_index=4 AND column_name='external_id')))=4
 AND (SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name='cf_sso_group_map' AND index_name='sso_native_group')=1
 AND (SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name='cf_sso_group_map' AND index_name='sso_native_group' AND non_unique=0 AND sub_part IS NULL AND ((seq_in_index=1 AND column_name='group_id')))=1
 AND EXISTS(SELECT 1 FROM information_schema.table_constraints WHERE constraint_schema=DATABASE() AND table_name='cf_sso_group_map' AND constraint_name='sso_group_type' AND constraint_type='CHECK')
 AND EXISTS(SELECT 1 FROM information_schema.table_constraints WHERE constraint_schema=DATABASE() AND table_name='cf_sso_group_map' AND constraint_name='sso_group_id' AND constraint_type='CHECK')) THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Target contract mismatch: cf_sso_group_map'; END IF;
 SELECT 'cf_sso_group_map verified' AS result;
 IF NOT ((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='cf_dir_acl')=11
 AND EXISTS(SELECT 1 FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name='cf_dir_acl' AND engine='InnoDB' AND table_collation='utf8mb4_bin')
 AND EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='cf_dir_acl' AND column_name='repo_id' AND data_type='char' AND is_nullable='NO' AND character_maximum_length=36 AND collation_name='ascii_bin')
 AND EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='cf_dir_acl' AND column_name='path_hash' AND data_type='binary' AND is_nullable='NO' AND character_maximum_length=32)
 AND EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='cf_dir_acl' AND column_name='path' AND data_type='varchar' AND is_nullable='NO' AND character_maximum_length=4096 AND collation_name='utf8mb4_bin')
 AND EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='cf_dir_acl' AND column_name='subject_type' AND data_type='varchar' AND is_nullable='NO' AND character_maximum_length=4 AND collation_name='ascii_bin')
 AND EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='cf_dir_acl' AND column_name='provider' AND data_type='varchar' AND is_nullable='NO' AND character_maximum_length=32 AND collation_name='utf8mb4_bin')
 AND EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='cf_dir_acl' AND column_name='namespace' AND data_type='varchar' AND is_nullable='NO' AND character_maximum_length=128 AND collation_name='utf8mb4_bin')
 AND EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='cf_dir_acl' AND column_name='external_id' AND data_type='varchar' AND is_nullable='NO' AND character_maximum_length=225 AND collation_name='utf8mb4_bin')
 AND EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='cf_dir_acl' AND column_name='permission' AND data_type='varchar' AND is_nullable='NO' AND character_maximum_length=9 AND collation_name='ascii_bin')
 AND EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='cf_dir_acl' AND column_name='inherit' AND data_type='tinyint' AND is_nullable='NO')
 AND EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='cf_dir_acl' AND column_name='share_mode' AND data_type='tinyint' AND is_nullable='NO')
 AND EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='cf_dir_acl' AND column_name='revision' AND data_type='char' AND is_nullable='NO' AND character_maximum_length=36 AND collation_name='ascii_bin')
 AND (SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name='cf_dir_acl' AND index_name='PRIMARY')=6
 AND (SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name='cf_dir_acl' AND index_name='PRIMARY' AND non_unique=0 AND sub_part IS NULL AND ((seq_in_index=1 AND column_name='repo_id') OR (seq_in_index=2 AND column_name='path_hash') OR (seq_in_index=3 AND column_name='subject_type') OR (seq_in_index=4 AND column_name='provider') OR (seq_in_index=5 AND column_name='namespace') OR (seq_in_index=6 AND column_name='external_id')))=6
 AND (SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name='cf_dir_acl' AND index_name='acl_shared_subject')=6
 AND (SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name='cf_dir_acl' AND index_name='acl_shared_subject' AND non_unique=1 AND sub_part IS NULL AND ((seq_in_index=1 AND column_name='provider') OR (seq_in_index=2 AND column_name='subject_type') OR (seq_in_index=3 AND column_name='namespace') OR (seq_in_index=4 AND column_name='external_id') OR (seq_in_index=5 AND column_name='share_mode') OR (seq_in_index=6 AND column_name='repo_id')))=6
 AND EXISTS(SELECT 1 FROM information_schema.table_constraints WHERE constraint_schema=DATABASE() AND table_name='cf_dir_acl' AND constraint_name='acl_subject_type' AND constraint_type='CHECK')
 AND EXISTS(SELECT 1 FROM information_schema.table_constraints WHERE constraint_schema=DATABASE() AND table_name='cf_dir_acl' AND constraint_name='acl_permission' AND constraint_type='CHECK')
 AND EXISTS(SELECT 1 FROM information_schema.table_constraints WHERE constraint_schema=DATABASE() AND table_name='cf_dir_acl' AND constraint_name='acl_inherit' AND constraint_type='CHECK')
 AND EXISTS(SELECT 1 FROM information_schema.table_constraints WHERE constraint_schema=DATABASE() AND table_name='cf_dir_acl' AND constraint_name='acl_share' AND constraint_type='CHECK')) THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Target contract mismatch: cf_dir_acl'; END IF;
 SELECT 'cf_dir_acl verified' AS result;
 IF NOT ((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='cf_edit_guard')=15
 AND EXISTS(SELECT 1 FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name='cf_edit_guard' AND engine='InnoDB' AND table_collation='utf8mb4_bin')
 AND EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='cf_edit_guard' AND column_name='repo_id' AND data_type='char' AND is_nullable='NO' AND character_maximum_length=36 AND collation_name='ascii_bin')
 AND EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='cf_edit_guard' AND column_name='path_hash' AND data_type='binary' AND is_nullable='NO' AND character_maximum_length=32)
 AND EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='cf_edit_guard' AND column_name='path' AND data_type='varchar' AND is_nullable='NO' AND character_maximum_length=4096 AND collation_name='utf8mb4_bin')
 AND EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='cf_edit_guard' AND column_name='guard_id' AND data_type='char' AND is_nullable='YES' AND character_maximum_length=36 AND collation_name='ascii_bin')
 AND EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='cf_edit_guard' AND column_name='generation' AND data_type='bigint' AND is_nullable='NO' AND column_type LIKE '%unsigned%')
 AND EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='cf_edit_guard' AND column_name='owner_uid' AND data_type='varchar' AND is_nullable='YES' AND character_maximum_length=225 AND collation_name='utf8mb4_bin')
 AND EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='cf_edit_guard' AND column_name='owner_native_user' AND data_type='varchar' AND is_nullable='YES' AND character_maximum_length=255 AND collation_name='utf8mb4_bin')
 AND EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='cf_edit_guard' AND column_name='terminal_type' AND data_type='varchar' AND is_nullable='YES' AND character_maximum_length=16 AND collation_name='ascii_bin')
 AND EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='cf_edit_guard' AND column_name='terminal_name' AND data_type='varchar' AND is_nullable='YES' AND character_maximum_length=128 AND collation_name='utf8mb4_bin')
 AND EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='cf_edit_guard' AND column_name='checkout_ip' AND data_type='varchar' AND is_nullable='YES' AND character_maximum_length=45 AND collation_name='ascii_bin')
 AND EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='cf_edit_guard' AND column_name='proof_digest' AND data_type='char' AND is_nullable='YES' AND character_maximum_length=64 AND collation_name='ascii_bin')
 AND EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='cf_edit_guard' AND column_name='base_file_id' AND data_type='char' AND is_nullable='YES' AND character_maximum_length=40 AND collation_name='ascii_bin')
 AND EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='cf_edit_guard' AND column_name='lease_expires_at' AND data_type='datetime' AND is_nullable='YES' AND datetime_precision=6)
 AND EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='cf_edit_guard' AND column_name='created_at' AND data_type='datetime' AND is_nullable='NO' AND datetime_precision=6)
 AND EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='cf_edit_guard' AND column_name='updated_at' AND data_type='datetime' AND is_nullable='NO' AND datetime_precision=6)
 AND (SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name='cf_edit_guard' AND index_name='PRIMARY')=2
 AND (SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name='cf_edit_guard' AND index_name='PRIMARY' AND non_unique=0 AND sub_part IS NULL AND ((seq_in_index=1 AND column_name='repo_id') OR (seq_in_index=2 AND column_name='path_hash')))=2
 AND (SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name='cf_edit_guard' AND index_name='cf_edit_guard_id')=1
 AND (SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name='cf_edit_guard' AND index_name='cf_edit_guard_id' AND non_unique=0 AND sub_part IS NULL AND ((seq_in_index=1 AND column_name='guard_id')))=1
 AND (SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name='cf_edit_guard' AND index_name='cf_edit_guard_active')=2
 AND (SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name='cf_edit_guard' AND index_name='cf_edit_guard_active' AND non_unique=1 AND sub_part IS NULL AND ((seq_in_index=1 AND column_name='repo_id') OR (seq_in_index=2 AND column_name='guard_id')))=2
 AND (SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name='cf_edit_guard' AND index_name='cf_edit_guard_owner')=2
 AND (SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name='cf_edit_guard' AND index_name='cf_edit_guard_owner' AND non_unique=1 AND sub_part IS NULL AND ((seq_in_index=1 AND column_name='owner_uid') OR (seq_in_index=2 AND column_name='guard_id')))=2
 AND EXISTS(SELECT 1 FROM information_schema.table_constraints WHERE constraint_schema=DATABASE() AND table_name='cf_edit_guard' AND constraint_name='cf_edit_terminal_type' AND constraint_type='CHECK')
 AND EXISTS(SELECT 1 FROM information_schema.table_constraints WHERE constraint_schema=DATABASE() AND table_name='cf_edit_guard' AND constraint_name='cf_edit_active_shape' AND constraint_type='CHECK')) THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Target contract mismatch: cf_edit_guard'; END IF;
 SELECT 'cf_edit_guard verified' AS result;
END$$
CALL cfv2_verify_20261021()$$
DROP PROCEDURE cfv2_verify_20261021$$
DELIMITER ;
