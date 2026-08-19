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
		STMRequestDate,
		STMID,
		STMAssignPerson AS STMAssignee,
		OperationD AS OperationStartDate
	FROM `pccw-internal-virt-agent-uat.Mirror.all_cost_items_report`
	WHERE ItemCode = 'MRC'
		AND MRC_USD > 0
		AND IFNULL(CTStatus, '') != 'Confirmed'
		AND IFNULL(CostType, '') != 'Direct Cost (Optify)'
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
		(OperationStartDate IS NOT NULL AND StartBillingDate IS NOT NULL) AS StartGapEligible,
		CASE
			WHEN OperationStartDate IS NOT NULL AND StartBillingDate IS NOT NULL THEN 1
			ELSE 0
		END AS StartGapEligibleFlag,
		(SRTerminationDate IS NOT NULL AND StopBillingDate IS NOT NULL) AS StopGapEligible,
		CASE
			WHEN SRTerminationDate IS NOT NULL AND StopBillingDate IS NOT NULL THEN 1
			ELSE 0
		END AS StopGapEligibleFlag,
		CASE
			WHEN StartBillingDate IS NULL THEN NULL
			WHEN OperationStartDate IS NULL OR OperationStartDate > CURRENT_DATE() THEN DATE_DIFF(CURRENT_DATE(), StartBillingDate, DAY)
			WHEN OperationStartDate IS NOT NULL THEN DATE_DIFF(OperationStartDate, StartBillingDate, DAY)
		END AS StartGapDays,
		CASE
			WHEN SRTerminationDate IS NOT NULL AND StopBillingDate IS NOT NULL THEN DATE_DIFF(StopBillingDate, SRTerminationDate, DAY)
		END AS StopGapDays,
		CASE
			WHEN StartBillingDate IS NULL THEN 0
			WHEN OperationStartDate IS NULL OR OperationStartDate > CURRENT_DATE() THEN CASE WHEN DATE_DIFF(CURRENT_DATE(), StartBillingDate, DAY) > 3 THEN 1 ELSE 0 END
			WHEN DATE_DIFF(OperationStartDate, StartBillingDate, DAY) > 3 THEN 1
			ELSE 0
		END AS LateStartFlag,
		CASE
			WHEN SRTerminationDate IS NOT NULL AND StopBillingDate IS NOT NULL AND DATE_DIFF(StopBillingDate, SRTerminationDate, DAY) > 3 THEN 1
			ELSE 0
		END AS LateStopFlag,
		CASE
			WHEN StartBillingDate IS NULL THEN 0
			WHEN OperationStartDate IS NULL OR OperationStartDate > CURRENT_DATE() THEN CASE WHEN DATE_DIFF(CURRENT_DATE(), StartBillingDate, DAY) > 30 THEN 1 ELSE 0 END
			WHEN DATE_DIFF(OperationStartDate, StartBillingDate, DAY) > 30 THEN 1
			ELSE 0
		END AS SevereLateStartFlag,
		CASE
			WHEN SRTerminationDate IS NOT NULL AND StopBillingDate IS NOT NULL AND DATE_DIFF(StopBillingDate, SRTerminationDate, DAY) > 30 THEN 1
			ELSE 0
		END AS SevereLateStopFlag,
		CASE
			WHEN StartBillingDate IS NOT NULL AND StartBillingDate <= CURRENT_DATE() AND (OperationStartDate IS NULL OR OperationStartDate > CURRENT_DATE()) THEN 1
			ELSE 0
		END AS UnbilledDeliveredFlag,
		CASE
			WHEN StartBillingDate IS NOT NULL AND StartBillingDate <= CURRENT_DATE() AND (OperationStartDate IS NULL OR OperationStartDate > CURRENT_DATE()) THEN 1
			ELSE 0
		END AS OpenStartGapFlag,
		CASE
			WHEN StartBillingDate IS NOT NULL AND StartBillingDate <= CURRENT_DATE() AND (OperationStartDate IS NULL OR OperationStartDate > CURRENT_DATE()) THEN DATE_DIFF(CURRENT_DATE(), StartBillingDate, DAY)
		END AS UnbilledDeliveredAgingDays,
		CASE
			WHEN StartBillingDate IS NULL OR StartBillingDate > CURRENT_DATE() OR (OperationStartDate IS NOT NULL AND OperationStartDate <= CURRENT_DATE()) THEN 'Not Open Start Gap'
			WHEN DATE_DIFF(CURRENT_DATE(), StartBillingDate, DAY) BETWEEN 0 AND 7 THEN '0-7 Days'
			WHEN DATE_DIFF(CURRENT_DATE(), StartBillingDate, DAY) BETWEEN 8 AND 30 THEN '8-30 Days'
			WHEN DATE_DIFF(CURRENT_DATE(), StartBillingDate, DAY) BETWEEN 31 AND 60 THEN '31-60 Days'
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
		GREATEST(
			IFNULL(
				CASE
					WHEN StartBillingDate IS NULL THEN NULL
					WHEN OperationStartDate IS NULL OR OperationStartDate > CURRENT_DATE() THEN DATE_DIFF(CURRENT_DATE(), StartBillingDate, DAY)
					ELSE DATE_DIFF(OperationStartDate, StartBillingDate, DAY)
				END,
			0),
		0) * SAFE_DIVIDE(IFNULL(MRC_USD, 0), 30) AS EstimatedStartGapCostUSD,
		GREATEST(IFNULL(DATE_DIFF(StopBillingDate, SRTerminationDate, DAY), 0), 0) * SAFE_DIVIDE(IFNULL(MRC_USD, 0), 30) AS EstimatedStopGapCostUSD,
		GREATEST(IFNULL(DATE_DIFF(SRTerminationDate, StopBillingDate, DAY), 0), 0) * SAFE_DIVIDE(IFNULL(MRC_USD, 0), 30) AS EstimatedEarlyStopGapCostUSD,
		CASE
			WHEN StartBillingDate IS NOT NULL AND StartBillingDate <= CURRENT_DATE() AND (OperationStartDate IS NULL OR OperationStartDate > CURRENT_DATE()) AND IFNULL(MRC_USD, 0) > 0 THEN MRC_USD
			ELSE 0
		END AS PotentialStartGapMonthlySavingsUSD,
		CASE
			WHEN StartBillingDate IS NOT NULL AND StartBillingDate <= CURRENT_DATE() AND (OperationStartDate IS NULL OR OperationStartDate > CURRENT_DATE()) AND IFNULL(MRC_USD, 0) > 0 THEN MRC_USD * 12
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
			WHEN ((StartBillingDate IS NOT NULL AND StartBillingDate <= CURRENT_DATE() AND (OperationStartDate IS NULL OR OperationStartDate > CURRENT_DATE())) OR (SRTerminationDate IS NOT NULL AND SRTerminationDate <= CURRENT_DATE() AND (StopBillingDate IS NULL OR StopBillingDate > CURRENT_DATE()))) AND IFNULL(MRC_USD, 0) > 0 THEN MRC_USD
			ELSE 0
		END AS PotentialMonthlySavingsUSD,
		CASE
			WHEN ((StartBillingDate IS NOT NULL AND StartBillingDate <= CURRENT_DATE() AND (OperationStartDate IS NULL OR OperationStartDate > CURRENT_DATE())) OR (SRTerminationDate IS NOT NULL AND SRTerminationDate <= CURRENT_DATE() AND (StopBillingDate IS NULL OR StopBillingDate > CURRENT_DATE()))) AND IFNULL(MRC_USD, 0) > 0 THEN MRC_USD * 12
			ELSE 0
		END AS PotentialAnnualSavingsUSD,
		CASE
			WHEN OperationStartDate IS NULL OR StartBillingDate IS NULL THEN 'Open/Incomplete'
			WHEN DATE_DIFF(OperationStartDate, StartBillingDate, DAY) > 30 THEN 'Early Billing (>30 days)'
			WHEN DATE_DIFF(OperationStartDate, StartBillingDate, DAY) BETWEEN 4 AND 30 THEN 'Early Billing (4-30 days)'
			WHEN DATE_DIFF(OperationStartDate, StartBillingDate, DAY) BETWEEN -3 AND 3 THEN 'On Time (-3 to 3)'
			ELSE 'Late Billing (>3 days after handover)'
		END AS StartGapBand,
		CASE
			WHEN SRTerminationDate IS NULL OR StopBillingDate IS NULL THEN 'Open/Incomplete'
			WHEN DATE_DIFF(StopBillingDate, SRTerminationDate, DAY) < -3 THEN 'Early Stop (<-3)'
			WHEN DATE_DIFF(StopBillingDate, SRTerminationDate, DAY) BETWEEN -3 AND 3 THEN 'On Time (-3 to 3)'
			WHEN DATE_DIFF(StopBillingDate, SRTerminationDate, DAY) BETWEEN 4 AND 30 THEN 'Late Stop (4-30)'
			ELSE 'Severe Late Stop (>30)'
		END AS StopGapBand,
		CASE
			WHEN StopBillingDate IS NOT NULL AND StopBillingDate <= CURRENT_DATE() THEN 'Billing Stopped'
			WHEN StopBillingDate IS NOT NULL AND StopBillingDate > CURRENT_DATE() THEN 'Pending Stop Billing'
			ELSE 'No Stop Date - Action Required'
		END AS StopBillingStatus,
		CASE
			WHEN SRTerminationDate IS NULL AND StopBillingDate IS NULL THEN 'Manual Review Required'
			WHEN StopBillingDate IS NULL THEN 'Vendor Billing Stop Date Missing'
			WHEN SRTerminationDate IS NULL OR SRTerminationDate > CURRENT_DATE() THEN 'Monitor - Vendor Billing Stop Not Begun'
			WHEN StopBillingDate > CURRENT_DATE() THEN 'Open Leakage - Vendor Billing Continues After Termination'
			ELSE 'No Action Required'
		END AS StopGapActionRequired,
		CASE
			WHEN StartBillingDate IS NULL AND OperationStartDate IS NULL THEN 'Manual Review Required'
			WHEN StartBillingDate IS NULL THEN 'Monitor - Start Billing Not Begun'
			WHEN StartBillingDate > CURRENT_DATE() THEN 'Monitor - Start Billing Not Begun'
			WHEN OperationStartDate IS NULL THEN 'Operation Start Date Missing'
			WHEN DATE_DIFF(OperationStartDate, StartBillingDate, DAY) > 3 THEN 'Open Leakage - Vendor Billing Started Before Operation Start'
			ELSE 'No Action Required'
		END AS StartGapActionRequired
	FROM base
)
SELECT
	enriched.*
FROM enriched
