-- Wanda generated Google Workspace files (Sheets, Docs, Slides, etc.)
-- One row per Google file, keyed by Google file_id.
-- Upsert on file_id: new file -> insert; edit of existing file -> update row.

CREATE TABLE IF NOT EXISTS `pccw-internal-virt-agent-uat.wanda_ds.wanda_docs` (
  file_id STRING NOT NULL OPTIONS (description="Google Drive file ID (from the file URL)"),
  file_name STRING OPTIONS (description="Display name of the file"),
  file_type STRING OPTIONS (description="File type: sheet / doc / slide / form"),
  file_url STRING OPTIONS (description="Google Drive URL"),
  mime_type STRING OPTIONS (description="Google MIME type, e.g. application/vnd.google-apps.spreadsheet"),
  created_by STRING OPTIONS (description="User who asked Wanda to create the file"),
  created_at TIMESTAMP NOT NULL OPTIONS (description="When the file was created"),
  updated_at TIMESTAMP OPTIONS (description="When the file/record was last updated"),
  status STRING OPTIONS (description="created / updated / deleted"),
  conversation_id STRING OPTIONS (description="Wanda chat session that produced the file"),
  request_id STRING OPTIONS (description="Identifier of the triggering request"),
  trigger_prompt STRING OPTIONS (description="Message that asked Wanda to create/update the file"),
  metadata JSON OPTIONS (description="Free-form JSON for future fields")
)
PARTITION BY DATE(created_at)
CLUSTER BY file_type, created_by
OPTIONS (
  description="Wanda generated Google Workspace files registry"
);
