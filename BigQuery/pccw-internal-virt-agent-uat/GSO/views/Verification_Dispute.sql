-- View for Verification Dispute data synced from Google Sheets via GAS
-- Data is cleaned and validated during sync (see GAS/VerificationDispute_to_BQ)
-- Table is partitioned by File_Dispute_Date and clustered by File_Dispute_Date, Vendor_Name, Dispute_Category__Reason
SELECT 
  File_Dispute_Date,
  DATE_TRUNC(File_Dispute_Date, MONTH) AS File_Dispute_Month,
  IS_ID, 
  Charged_Company, 
  Vendor_Name, 
  Vendor_Code, 
  Invoice__Number, 
  Line__, 
  circuit_ID, 
  PO_no_, 
  Charge_Date_From, 
  Charge_Date_To, 
  Invoice_Currency, 
  Line_Amount, 
  Dispute_Amount_in_local_currency, 
  Exchange_rate, 
  Dispute_Amount_in_USD, 
  Dispute_Category__Reason, 
  Dispute_Details, 
  Follow_up_action___Remarks, 
  Ticket__case_no__if_any, 
  Credit_Note_Reference, 
  Received_Credit_Amount_in_local_currency, 
  Received_Credit_Amount_in_USD, 
  Dispute_Resolve_Date, 
  Diff_btw_forecast_and_actual_credit_Amount__local_currency_, 
  Diff_btw_forecast_and_actual_credit_Amount__USD_, 
  Name_of_verifier, 
  Days_of_Resovled, 
  Actual_Days_of_Resolved, 
  Vendor_Group_Name, 
  Dispute_Reason,
  ingestion_time,
  _source_row_number
  
FROM `pccw-internal-virt-agent-uat.GSO.VerificationDisputeList`


