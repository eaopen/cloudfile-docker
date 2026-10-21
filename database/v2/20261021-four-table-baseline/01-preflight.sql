-- Read-only inspection, usable before/after the four-table conversion.
-- Select the native Seafile database. Output metadata and aggregates only.
SELECT DATABASE() AS database_name, VERSION() AS engine_version;
SELECT TABLE_NAME,ENGINE,TABLE_COLLATION FROM information_schema.TABLES
 WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME IN
 ('cf_library_storage','cf_dir_acl','cf_sso_group_map','cf_edit_guard') ORDER BY TABLE_NAME;
SELECT TABLE_NAME,COLUMN_NAME,COLUMN_TYPE,IS_NULLABLE,COLUMN_DEFAULT,COLLATION_NAME
 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME IN
 ('cf_library_storage','cf_dir_acl','cf_sso_group_map','cf_edit_guard') ORDER BY TABLE_NAME,ORDINAL_POSITION;
SELECT TABLE_NAME,INDEX_NAME,NON_UNIQUE,SEQ_IN_INDEX,COLUMN_NAME,SUB_PART
 FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME IN
 ('cf_library_storage','cf_dir_acl','cf_sso_group_map','cf_edit_guard') ORDER BY TABLE_NAME,INDEX_NAME,SEQ_IN_INDEX;
SELECT 'cf_library_storage' AS table_name,COUNT(*) AS row_count FROM cf_library_storage
 UNION ALL SELECT 'cf_dir_acl',COUNT(*) FROM cf_dir_acl
 UNION ALL SELECT 'cf_sso_group_map',COUNT(*) FROM cf_sso_group_map
 UNION ALL SELECT 'cf_edit_guard',COUNT(*) FROM cf_edit_guard;
SELECT COUNT(*) AS guard_rows,SUM(guard_id IS NOT NULL) AS occupied_guard_rows,
 SUM(generation>0) AS rows_with_generation FROM cf_edit_guard;
