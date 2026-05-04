WITH base AS (
	SELECT
		AEndAddress,
		BEndAddress,
		BillingType,
		BudgetRequestID,
		CCC,
		CostCategory,
		CostItemID,
		CostSubCategory,
		CostType,
		CreatedBy,
		CreationDate,
		Currency,
		CustomerName,
		Description,
		GLAccCode,
		ItemCode,
		ItemStatus,
		LastestIssueDescription AS LatestIssueDescription,
		LastUpdateDate,
		LastUpdatedBy,
		LISPONum,
		MRC,
		MRC_USD,
		Nomenclature,
		NRC,
		NRC_USD,
		POLineNum,
		PONumber,
		PopID,
		POType,
		PreviousCostItemID,
		PRID,
		PRItemID,
		ProjectNumber,
		ProvisioningCentre,
		Quantity,
		Quarter,
		ReachType,
		ReceivedAmount,
		ReceivedAmountUSD,
		ReceivedQty,
		ReceivingDate,
		Requester,
		SalesRecord,
		SalesRegion,
		ServiceHandoverDate,
		SignedBDMName,
		SignedCompany,
		snapshot_date,
		SRProductFamily,
		SRProductType,
		SRStatus,
		StartBillingDate,
		StopBillingDate,
		TerminationDate,
		TerminationNoticeDays,
		UnitPrice,
		UOM,
		ValueStream,
		VendorCircuitID,
		VendorCode,
		VendorGroup,
		VendorName,
		VendorType,
		WONum,
		SRTerminationDate,
		CTStatus, 
		STMRequestDate
	FROM `edp-prod-lake-data-warehouse.Cost_Items.all_cost_items_report`
	WHERE ItemCode = 'MRC'
		AND MRC_USD > 0
),
enriched AS (
	SELECT
		base.*,
		CASE
			WHEN CostType LIKE 'Network%' THEN 'Network'
			WHEN CostType LIKE 'Direct Cost%' THEN 'Direct Cost'
			ELSE 'Others'
		END AS CostTypeCleaned,
		1 AS RowCount,
		CASE
			WHEN ItemCode = 'MRC' AND IFNULL(MRC_USD, 0) > 0 THEN 1
			ELSE 0
		END AS MRCActiveFlag,
		(ServiceHandoverDate IS NOT NULL AND StartBillingDate IS NOT NULL) AS StartGapEligible,
		CASE
			WHEN ServiceHandoverDate IS NOT NULL AND StartBillingDate IS NOT NULL THEN 1
			ELSE 0
		END AS StartGapEligibleFlag,
		(SRTerminationDate IS NOT NULL AND StopBillingDate IS NOT NULL) AS StopGapEligible,
		CASE
			WHEN SRTerminationDate IS NOT NULL AND StopBillingDate IS NOT NULL THEN 1
			ELSE 0
		END AS StopGapEligibleFlag,
		CASE
			WHEN ServiceHandoverDate IS NOT NULL AND StartBillingDate IS NOT NULL THEN DATE_DIFF(StartBillingDate, ServiceHandoverDate, DAY)
		END AS StartGapDays,
		CASE
			WHEN SRTerminationDate IS NOT NULL AND StopBillingDate IS NOT NULL THEN DATE_DIFF(StopBillingDate, SRTerminationDate, DAY)
		END AS StopGapDays,
		CASE
			WHEN ServiceHandoverDate IS NOT NULL AND StartBillingDate IS NOT NULL AND DATE_DIFF(StartBillingDate, ServiceHandoverDate, DAY) > 3 THEN 1
			ELSE 0
		END AS LateStartFlag,
		CASE
			WHEN SRTerminationDate IS NOT NULL AND StopBillingDate IS NOT NULL AND DATE_DIFF(StopBillingDate, SRTerminationDate, DAY) > 3 THEN 1
			ELSE 0
		END AS LateStopFlag,
		CASE
			WHEN ServiceHandoverDate IS NOT NULL AND StartBillingDate IS NOT NULL AND DATE_DIFF(StartBillingDate, ServiceHandoverDate, DAY) > 30 THEN 1
			ELSE 0
		END AS SevereLateStartFlag,
		CASE
			WHEN SRTerminationDate IS NOT NULL AND StopBillingDate IS NOT NULL AND DATE_DIFF(StopBillingDate, SRTerminationDate, DAY) > 30 THEN 1
			ELSE 0
		END AS SevereLateStopFlag,
		CASE
			WHEN ServiceHandoverDate IS NOT NULL AND ServiceHandoverDate <= CURRENT_DATE() AND (StartBillingDate IS NULL OR StartBillingDate > CURRENT_DATE()) THEN 1
			ELSE 0
		END AS UnbilledDeliveredFlag,
		CASE
			WHEN ServiceHandoverDate IS NOT NULL AND ServiceHandoverDate <= CURRENT_DATE() AND (StartBillingDate IS NULL OR StartBillingDate > CURRENT_DATE()) THEN 1
			ELSE 0
		END AS OpenStartGapFlag,
		CASE
			WHEN ServiceHandoverDate IS NOT NULL AND ServiceHandoverDate <= CURRENT_DATE() AND (StartBillingDate IS NULL OR StartBillingDate > CURRENT_DATE()) THEN DATE_DIFF(CURRENT_DATE(), ServiceHandoverDate, DAY)
		END AS UnbilledDeliveredAgingDays,
		CASE
			WHEN ServiceHandoverDate IS NULL OR ServiceHandoverDate > CURRENT_DATE() OR (StartBillingDate IS NOT NULL AND StartBillingDate <= CURRENT_DATE()) THEN 'Not Open Start Gap'
			WHEN DATE_DIFF(CURRENT_DATE(), ServiceHandoverDate, DAY) BETWEEN 0 AND 7 THEN '0-7 Days'
			WHEN DATE_DIFF(CURRENT_DATE(), ServiceHandoverDate, DAY) BETWEEN 8 AND 30 THEN '8-30 Days'
			WHEN DATE_DIFF(CURRENT_DATE(), ServiceHandoverDate, DAY) BETWEEN 31 AND 60 THEN '31-60 Days'
			ELSE '61+ Days'
		END AS StartGapAgingBucket,
		CASE
			WHEN SRTerminationDate IS NOT NULL AND SRTerminationDate <= CURRENT_DATE() AND (StopBillingDate IS NULL OR StopBillingDate > CURRENT_DATE()) THEN 1
			ELSE 0
		END AS TerminatedNotStoppedFlag,
		CASE
			WHEN SRTerminationDate IS NOT NULL AND SRTerminationDate <= CURRENT_DATE() AND (StopBillingDate IS NULL OR StopBillingDate > CURRENT_DATE()) THEN 1
			ELSE 0
		END AS OpenStopGapFlag,
		CASE
			WHEN SRTerminationDate IS NOT NULL AND SRTerminationDate <= CURRENT_DATE() AND (StopBillingDate IS NULL OR StopBillingDate > CURRENT_DATE()) THEN DATE_DIFF(CURRENT_DATE(), SRTerminationDate, DAY)
		END AS TerminatedNotStoppedAgingDays,
		CASE
			WHEN SRTerminationDate IS NULL OR SRTerminationDate > CURRENT_DATE() OR (StopBillingDate IS NOT NULL AND StopBillingDate <= CURRENT_DATE()) THEN 'Not Open Stop Gap'
			WHEN DATE_DIFF(CURRENT_DATE(), SRTerminationDate, DAY) BETWEEN 0 AND 7 THEN '0-7 Days'
			WHEN DATE_DIFF(CURRENT_DATE(), SRTerminationDate, DAY) BETWEEN 8 AND 30 THEN '8-30 Days'
			WHEN DATE_DIFF(CURRENT_DATE(), SRTerminationDate, DAY) BETWEEN 31 AND 60 THEN '31-60 Days'
			ELSE '61+ Days'
		END AS StopGapAgingBucket,
		CASE
			WHEN SRTerminationDate IS NOT NULL AND SRTerminationDate < CURRENT_DATE() THEN 1
			ELSE 0
		END AS ExpiredFlag,
		CASE
			WHEN SRTerminationDate IS NOT NULL AND DATE_DIFF(SRTerminationDate, CURRENT_DATE(), DAY) BETWEEN 0 AND 30 THEN 1
			ELSE 0
		END AS ToBeExpired30DaysFlag,
		CASE
			WHEN SRTerminationDate IS NOT NULL AND DATE_DIFF(SRTerminationDate, CURRENT_DATE(), DAY) BETWEEN 31 AND 60 THEN 1
			ELSE 0
		END AS ToBeExpired60DaysFlag,
		CASE
			WHEN SRTerminationDate IS NOT NULL THEN DATE_DIFF(SRTerminationDate, CURRENT_DATE(), DAY)
		END AS DaysToExpiry,
		CASE
			WHEN SRTerminationDate IS NULL THEN 'No Termination Date'
			WHEN SRTerminationDate < CURRENT_DATE() THEN 'Expired'
			WHEN DATE_DIFF(SRTerminationDate, CURRENT_DATE(), DAY) BETWEEN 0 AND 30 THEN 'Expiring in 30 Days'
			WHEN DATE_DIFF(SRTerminationDate, CURRENT_DATE(), DAY) BETWEEN 31 AND 60 THEN 'Expiring in 31-60 Days'
			ELSE 'Active'
		END AS ExpiryStatus,
		SAFE_DIVIDE(IFNULL(MRC_USD, 0), 30) AS DailyMRC_USD,
		GREATEST(IFNULL(DATE_DIFF(StartBillingDate, ServiceHandoverDate, DAY), 0), 0) * SAFE_DIVIDE(IFNULL(MRC_USD, 0), 30) AS EstimatedStartGapCostUSD,
		GREATEST(IFNULL(DATE_DIFF(StopBillingDate, SRTerminationDate, DAY), 0), 0) * SAFE_DIVIDE(IFNULL(MRC_USD, 0), 30) AS EstimatedStopGapCostUSD,
		GREATEST(IFNULL(DATE_DIFF(SRTerminationDate, StopBillingDate, DAY), 0), 0) * SAFE_DIVIDE(IFNULL(MRC_USD, 0), 30) AS EstimatedEarlyStopGapCostUSD,
		CASE
			WHEN ServiceHandoverDate IS NOT NULL AND ServiceHandoverDate <= CURRENT_DATE() AND (StartBillingDate IS NULL OR StartBillingDate > CURRENT_DATE()) AND IFNULL(MRC_USD, 0) > 0 THEN MRC_USD
			ELSE 0
		END AS PotentialStartGapMonthlySavingsUSD,
		CASE
			WHEN ServiceHandoverDate IS NOT NULL AND ServiceHandoverDate <= CURRENT_DATE() AND (StartBillingDate IS NULL OR StartBillingDate > CURRENT_DATE()) AND IFNULL(MRC_USD, 0) > 0 THEN MRC_USD * 12
			ELSE 0
		END AS PotentialStartGapAnnualSavingsUSD,
		CASE
			WHEN SRTerminationDate IS NOT NULL AND SRTerminationDate <= CURRENT_DATE() AND (StopBillingDate IS NULL OR StopBillingDate > CURRENT_DATE()) AND IFNULL(MRC_USD, 0) > 0 THEN MRC_USD
			ELSE 0
		END AS PotentialStopGapMonthlySavingsUSD,
		CASE
			WHEN SRTerminationDate IS NOT NULL AND SRTerminationDate <= CURRENT_DATE() AND (StopBillingDate IS NULL OR StopBillingDate > CURRENT_DATE()) AND IFNULL(MRC_USD, 0) > 0 THEN MRC_USD * 12
			ELSE 0
		END AS PotentialStopGapAnnualSavingsUSD,
		CASE
			WHEN ((ServiceHandoverDate IS NOT NULL AND ServiceHandoverDate <= CURRENT_DATE() AND (StartBillingDate IS NULL OR StartBillingDate > CURRENT_DATE())) OR (SRTerminationDate IS NOT NULL AND SRTerminationDate <= CURRENT_DATE() AND (StopBillingDate IS NULL OR StopBillingDate > CURRENT_DATE()))) AND IFNULL(MRC_USD, 0) > 0 THEN MRC_USD
			ELSE 0
		END AS PotentialMonthlySavingsUSD,
		CASE
			WHEN ((ServiceHandoverDate IS NOT NULL AND ServiceHandoverDate <= CURRENT_DATE() AND (StartBillingDate IS NULL OR StartBillingDate > CURRENT_DATE())) OR (SRTerminationDate IS NOT NULL AND SRTerminationDate <= CURRENT_DATE() AND (StopBillingDate IS NULL OR StopBillingDate > CURRENT_DATE()))) AND IFNULL(MRC_USD, 0) > 0 THEN MRC_USD * 12
			ELSE 0
		END AS PotentialAnnualSavingsUSD,
		CASE
			WHEN ServiceHandoverDate IS NULL OR StartBillingDate IS NULL THEN 'Open/Incomplete'
			WHEN DATE_DIFF(StartBillingDate, ServiceHandoverDate, DAY) < -3 THEN 'Early Start (<-3)'
			WHEN DATE_DIFF(StartBillingDate, ServiceHandoverDate, DAY) BETWEEN -3 AND 3 THEN 'On Time (-3 to 3)'
			WHEN DATE_DIFF(StartBillingDate, ServiceHandoverDate, DAY) BETWEEN 4 AND 30 THEN 'Late Start (4-30)'
			ELSE 'Severe Late Start (>30)'
		END AS StartGapBand,
		CASE
			WHEN SRTerminationDate IS NULL OR StopBillingDate IS NULL THEN 'Open/Incomplete'
			WHEN DATE_DIFF(StopBillingDate, SRTerminationDate, DAY) < -3 THEN 'Early Stop (<-3)'
			WHEN DATE_DIFF(StopBillingDate, SRTerminationDate, DAY) BETWEEN -3 AND 3 THEN 'On Time (-3 to 3)'
			WHEN DATE_DIFF(StopBillingDate, SRTerminationDate, DAY) BETWEEN 4 AND 30 THEN 'Late Stop (4-30)'
			ELSE 'Severe Late Stop (>30)'
		END AS StopGapBand
	FROM base
)
SELECT
	enriched.*
FROM enriched