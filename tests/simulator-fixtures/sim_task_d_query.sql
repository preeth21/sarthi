-- Simulator test fixture: SQL with intentional column error (sql_error scenario)
-- Table: wmt-intl-dp-etrans-360-dev.GLBL_MB_DL_STAGE_TABLES.COSMOS_EXTRACT_ORDR_LINES
-- This is a real queryable table in the CL-DEV environment.
-- Error: 'item_id' does not exist in this table. Real columns include: departmentCode, entityType, id, fulfillmentType, etc.
-- sArthI sar-fix target: remove item_id reference; use departmentCode instead.

SELECT item_id, departmentCode
FROM `wmt-intl-dp-etrans-360-dev.GLBL_MB_DL_STAGE_TABLES.COSMOS_EXTRACT_ORDR_LINES`
WHERE item_id IS NOT NULL
