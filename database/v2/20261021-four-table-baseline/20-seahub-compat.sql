-- Explicit compatibility columns formerly written by bootstrap.
-- Select the SEAHUB database, not the native Seafile database.
-- Apply offline only when adopting this CloudFile code onto CE14.
-- Existing model data remains unchanged; object-ID backfill requires RPC and
-- is a separate reviewed operation, never a fictitious SQL backfill.
DELIMITER $$
DROP PROCEDURE IF EXISTS cfv2_seahub_compat_20261021$$
CREATE PROCEDURE cfv2_seahub_compat_20261021()
BEGIN
 IF DATABASE() IS NULL OR COALESCE(@cf_upgrade_writers_stopped,0)<>1 THEN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Select Seahub database and stop all writers';
 END IF;
 IF (SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE()
     AND table_name IN ('repo_metadata','repo_tags_repotags','base_userstarredfiles'))<>3 THEN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Expected CE14 Seahub tables are missing';
 END IF;
 IF NOT EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='repo_metadata' AND column_name='summary_enabled') THEN
  ALTER TABLE repo_metadata ADD COLUMN summary_enabled TINYINT(1) NOT NULL DEFAULT 0,
      ADD KEY key_repo_metadata_summary_enabled(summary_enabled);
 END IF;
 IF NOT EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='repo_tags_repotags' AND column_name='is_system') THEN
  ALTER TABLE repo_tags_repotags ADD COLUMN is_system TINYINT(1) NOT NULL DEFAULT 0,
      ADD KEY repo_tags_repotags_is_system(is_system);
 END IF;
 IF NOT EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='base_userstarredfiles' AND column_name='obj_id') THEN
  ALTER TABLE base_userstarredfiles ADD COLUMN obj_id VARCHAR(64) NULL,
      ADD KEY base_userstarredfiles_obj_id(obj_id);
 END IF;
 SELECT 'Seahub compatibility columns ready; run model/API validation' AS result;
END$$
CALL cfv2_seahub_compat_20261021()$$
DROP PROCEDURE cfv2_seahub_compat_20261021$$
DELIMITER ;
