//run a SQL query to take snaps within BQ for outstanding and escalations

function runQuery() {
  try {
    Logger.log('Starting query execution...');

    var query = `
      INSERT INTO \`pccw-internal-virt-agent-uat.Snapshot.BQOutstandingSnapShift\`
      SELECT
        MAX(CASE WHEN \`pccw-internal-virt-agent-uat.Looker.helpdesk\`.\`Status\` IN ('Assigned', 'In Progress') 
          THEN TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), \`pccw-internal-virt-agent-uat.Looker.helpdesk\`.\`Submit_Date\`, MINUTE) ELSE NULL END) AS \`Longest Outstanding\`,
        COUNT(CASE WHEN \`pccw-internal-virt-agent-uat.Looker.helpdesk\`.\`Status\` IN ('Assigned', 'In Progress') 
          THEN \`pccw-internal-virt-agent-uat.Looker.helpdesk\`.\`Incident_Number\` ELSE NULL END) AS \`Total Outstanding\`,
        CAST(AVG(CASE WHEN \`pccw-internal-virt-agent-uat.Looker.helpdesk\`.\`Status\` IN ('Assigned', 'In Progress') 
          THEN TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), \`pccw-internal-virt-agent-uat.Looker.helpdesk\`.\`Submit_Date\`, MINUTE) ELSE NULL END) AS INT64) AS \`Average Duration\`,
        MAX(CASE WHEN \`pccw-internal-virt-agent-uat.Looker.helpdesk\`.\`Status\` IN ('Pending') 
          THEN TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), \`pccw-internal-virt-agent-uat.Looker.helpdesk\`.\`Submit_Date\`, MINUTE) ELSE NULL END) AS \`Max Duration_Pending\`,
        COUNT(CASE WHEN \`pccw-internal-virt-agent-uat.Looker.helpdesk\`.\`Status\` IN ('Pending') 
          THEN \`pccw-internal-virt-agent-uat.Looker.helpdesk\`.\`Incident_Number\` ELSE NULL END) AS \`Incident_Count_Pending\`,
        CAST(AVG(CASE WHEN \`pccw-internal-virt-agent-uat.Looker.helpdesk\`.\`Status\` IN ('Pending') 
          THEN TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), \`pccw-internal-virt-agent-uat.Looker.helpdesk\`.\`Submit_Date\`, MINUTE) ELSE NULL END) AS INT64) AS \`Average Duration_Pending\`,
        COUNT(CASE WHEN \`pccw-internal-virt-agent-uat.Looker.helpdesk\`.\`Status\` IN ('Resolved') 
          THEN \`pccw-internal-virt-agent-uat.Looker.helpdesk\`.\`Incident_Number\` ELSE NULL END) AS \`Incident_Count_Resolved\`,
        \`pccw-internal-virt-agent-uat.Looker.helpdesk\`.\`Assigned_Group\` AS NOC,
        CURRENT_TIMESTAMP() AS CurrentDateTime 
      FROM \`pccw-internal-virt-agent-uat.Looker.helpdesk\`
      WHERE \`pccw-internal-virt-agent-uat.Looker.helpdesk\`.\`CaseType\` = 'Incident'
      GROUP BY NOC;
    `;

    var job = {
      configuration: {
        query: {
          query: query,
          useLegacySql: false
        }
      }
    };

    BigQuery.Jobs.insert(job, 'pccw-internal-virt-agent-uat');
    Logger.log('Query executed successfully.');
    
  } catch (error) {
    Logger.log('Error executing query: ' + error.message);
  }
}
