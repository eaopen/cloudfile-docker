-- Read-only archive plan. Historical tables must not remain in V2 runtime.
-- Select the runtime DB and set @cf_upgrade_archive_database to a separately
-- backed-up archive DB. Review the generated statements and dependencies,
-- stop all writers, then execute the reviewed RENAME statements explicitly.
-- This file itself never moves or deletes data; FK/views require DBA review.
SELECT TABLE_NAME,TABLE_TYPE,ENGINE
 FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE()
 AND LOWER(LEFT(TABLE_NAME,2))='cf'
 AND TABLE_NAME NOT IN ('cf_library_storage','cf_dir_acl','cf_sso_group_map','cf_edit_guard')
 ORDER BY TABLE_NAME;
SELECT CONCAT('RENAME TABLE `',REPLACE(TABLE_SCHEMA,'`','``'),'`.`',REPLACE(TABLE_NAME,'`','``'),
 '` TO `',REPLACE(@cf_upgrade_archive_database,'`','``'),'`.`',REPLACE(TABLE_NAME,'`','``'),'`;')
 AS reviewed_archive_sql
 FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_TYPE='BASE TABLE'
 AND @cf_upgrade_archive_database IS NOT NULL AND @cf_upgrade_archive_database<>DATABASE()
 AND LOWER(LEFT(TABLE_NAME,2))='cf'
 AND TABLE_NAME NOT IN ('cf_library_storage','cf_dir_acl','cf_sso_group_map','cf_edit_guard')
 ORDER BY TABLE_NAME;
