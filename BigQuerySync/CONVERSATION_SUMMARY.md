# HubSpot to BigQuery Import - Conversation Summary

**Date:** 2024-05-24

## 1. Objective

The primary goal was to find or create a script to automate the process of loading monthly HubSpot survey data from Excel (`.xlsx`) files into two specific BigQuery tables:

- `pccw-internal-virt-agent-uat.GSO.HubspotRemedyClosureSurvey`
- `pccw-internal-virt-agent-uat.GSO.HubspotSCNFeedback`

## 2. Initial Exploration & Discovery

- **Initial Request:** The user asked to find existing scripts for this purpose.
- **Initial Finding:** No scripts were immediately found in the provided context. A generic Python script using `pandas` was offered as a starting point.
- **Discovery of Python Script:** Upon further investigation, an existing Python script was located at `g:\My Drive\Scripts\BigQuerySync\load_hubspot_surveys.py`. This script was designed for the exact task, and improvements were suggested to make it more robust.

## 3. Change in Strategy to Google Apps Script

The user decided that a Google Apps Script would be a superior solution for the following reasons:
- The source Excel files are consistently saved in a specific Google Drive folder: `https://drive.google.com/drive/folders/1ZgMpFUqoPH2WfshpGMRBSmrRrfzf8Cij`.
- An Apps Script provides a more integrated, serverless, and automated workflow within the Google ecosystem.

The key requirements for the new script were to be **"intelligent and seamless"**, automatically picking up the latest monthly files and using the best method to load the data into BigQuery.

## 4. The Google Apps Script Solution

A new, complete Google Apps Script was created to meet these requirements.

**File Location:** `g:\gdrive\HubspotSurveyLoader\Code.gs`

### Key Architectural Decisions & Features:

1.  **Import Method:** A `MERGE` operation was chosen as the most "intelligent" approach. This allows the script to:
    - **Insert** new survey records.
    - **Update** existing records if they are re-processed (using `record_id` as the key).
    - **Prevent duplicates**, ensuring data integrity.

2.  **File Handling:**
    - The script scans the specified Google Drive folder.
    - It uses regular expressions (`file_pattern`) to identify the correct files for each table.
    - It intelligently selects only the **most recently updated** file for each survey type to process.

3.  **Execution Flow:**
    - **Convert & Read:** The script temporarily converts the source `.xlsx` file into a Google Sheet to read the data reliably.
    - **Transform:** It maps the Excel column headers to the correct BigQuery column names based on predefined configurations.
    - **Stage:** The transformed data is loaded into a temporary BigQuery "staging" table. This is a best practice for ensuring atomic and efficient `MERGE` operations.
    - **Merge:** A BigQuery `MERGE` job is executed to upsert the data from the staging table into the final production table.
    - **Cleanup:** The temporary Google Sheet and the BigQuery staging table are automatically deleted after the process completes.

4.  **Automation:**
    - The script includes a helper function (`createMonthlyTrigger`) to set up a time-based trigger, allowing the entire process to run automatically every month without any user intervention.

## 5. Current Status

The complete Google Apps Script solution, along with detailed setup instructions (enabling APIs, granting permissions, and creating triggers), has been provided.

The next step is to review, deploy, and test this Apps Script in the user's environment.

---

### Files Referenced:

- **Original Python Script:** `g:\My Drive\Scripts\BigQuerySync\load_hubspot_surveys.py`
- **New Apps Script Solution:** `g:\gdrive\HubspotSurveyLoader\Code.gs`
- **This Summary:** `g:\gdrive\HubspotSurveyLoader\CONVERSATION_SUMMARY.md`