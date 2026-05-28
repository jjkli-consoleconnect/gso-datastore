%%{init: {'flowchart': {'curve': 'linear', 'nodeSpacing': 30, 'rankSpacing': 90}} }%%
graph LR
    subgraph SYSTEMS["Systems"]
        direction TB
        SYS_JIRA["JIRA"]
        SYS_BMC["BMC"]
        SYS_GSHEET["Google Sheet"]
        SYS_CONNECT["CONNECT"]
        SYS_INSIGHT["INsight"]
        SYS_DATAPIPE["Datapipe"]
        SYS_PAGERDUTY["Pager Duty"]
        SYS_METABASE["Metabase"]
    end

    subgraph BASE_TABLES["Base Tables"]
        direction TB
        JT[JiraTickets]
        JCL[JiraChangelog]
        JCM[JiraComments]
        HD[HelpDeskAllNOC]
        WL[WorkLogAllNOC]
        COSS[CenterOperationsShiftSnapshots]
        COSSA[CenterOperationsShiftSnapshotsAgg]
        Staff[Staff]
        SHR[SHRPeople]
        TD[TrainingData]
        SRI[SRInventory]
        JTP[JiraTickets_progress]
        JCLP[JiraChangelog_progress]
        JCMP[JiraComments_progress]
        VDL[VerificationDisputeList]
        VVP[VerificationVerifierPerformance]
        VPRP[VerificationPRRequesterPerformance]
        VTN[VerificationTeamNames]
        DLOG[dispute_log]
        Survey[2025SurveyResponse_clustered]
        PDI[PagerDutyIncidentData]
        CST[CustomerSuccessTracking]
        CostItemCombined[CostItemExpiration.CostItemCombined]
    end

    subgraph VIEWS["Views"]
        direction TB
        JiraCombined
        CSM
        CSM_Changelog
        CSM_Comment_Shift
        CSM_Individual
        SH
        SH_Changelog
        CCAS
        CCAS_Comment_Shift
        ITHD
        ITHD_Changelog
        HDWL
        HDWL_Shift
        JIRA_HD
        JiraHDChangelog
        RemedyJira
        StaffListCleaned
        Verification_Dispute
        Verification_IS_PR_CT
        Verification_Verifier_Performance
        SD_Changelog
        DataProgress
        PipelineRuns
        SRInventory_HD
        Snapshot_Outstanding[Snapshot-Outstanding]
        COSSA_Latest[CenterOperationsShiftSnapshotsAgg_Latest]
        SurveyFormatted[2025SurveyResponseFormatted]
        AAProjects
        PDI_Cleansed[PagerDutyIncidentCleansed]
        PDI_Inc[PagerDutyIncidents]
        PDI_Agg[PagerDutyAgg]
        HD_CarrierVendor
    end

    subgraph LOOKER_REPORTS["Looker Studio Reports"]
        direction TB
        LS_SH["[M] SRE Month End Report"]
        LS_CCAS["[M] CCAS"]
        LS_ITHD["IT Operations"]
        LS_CSM["Customer Success Management"]
        LS_QMS["QMS - Quality Objectives"]
        LS_CENTEROPS["Center Operations"]
        LS_MONITOR["Datapipe Monitor"]
        LS_AAPROJ["GS&O Automation and Analytics - Jira Projects Report"]
        LS_AAPROJ_B["[M] GS&O Automation and Analytics - Jira Projects Report"]
        LS_JIRAHD_A["GS&O Customer Profile Performance"]
        LS_JIRAHD_B["JIRA_HD Report (bea658b1)"]
        LS_CCAS_B["CCAS Report (ca87daa9)"]
        LS_VENDOR["Vendor/Carrier Performance"]
        LS_SURVEY_FMT["2025 GS&O Survey Results"]
        LS_PAGERDUTY["Escalation Performance - Pager Duty"]
        LS_COSTITEM["Cost Item Expiration (85a63c13)"]
        LS_GSO["GSO Performance Dashboard"]
    end

    SYS_JIRA --> JT & JCL & JCM
    SYS_BMC --> HD & WL & COSS & COSSA & SHR
    SYS_GSHEET --> Staff & VDL & VVP & VPRP & VTN & DLOG & Survey & CST
    SYS_CONNECT --> TD
    SYS_INSIGHT --> SRI
    SYS_DATAPIPE --> JTP & JCLP & JCMP
    SYS_PAGERDUTY --> PDI
    SYS_METABASE --> CostItemCombined

    JT & JCL & JCM --> JiraCombined
    JiraCombined --> CSM & SH & CCAS & ITHD & AAProjects & SD_Changelog
    SH --> SH_Changelog
    CSM --> CSM_Changelog & CSM_Comment_Shift & CSM_Individual
    CCAS --> CCAS_Comment_Shift

    HD & WL --> HDWL
    HD & WL --> HD_CarrierVendor
    HDWL --> HDWL_Shift
    JT & HD & SHR --> JIRA_HD
    JIRA_HD --> JiraHDChangelog
    JIRA_HD --> RemedyJira
    Staff --> RemedyJira
    Staff --> StaffListCleaned

    JTP & JCLP & JCMP --> DataProgress
    VDL --> Verification_Dispute
    VVP & VPRP & VTN --> Verification_IS_PR_CT
    VVP --> Verification_Verifier_Performance
    SRI --> SRInventory_HD
    COSSA --> Snapshot_Outstanding & COSSA_Latest
    Survey --> SurveyFormatted
    PDI --> PDI_Cleansed

    %% Full validated report lineage from 365-day BigQuery scan
    JIRA_HD --> LS_GSO
    ITHD --> LS_GSO
    CSM --> LS_GSO
    PDI --> LS_GSO
    Verification_IS_PR_CT --> LS_GSO
    Verification_Dispute --> LS_GSO
    Verification_Verifier_Performance --> LS_GSO
    SD_Changelog --> LS_GSO
    PDI_Cleansed --> LS_GSO
    HDWL --> LS_GSO
    JiraHDChangelog --> LS_GSO
    ITHD_Changelog --> LS_GSO
    CST --> LS_GSO
    StaffListCleaned --> LS_GSO
    SH --> LS_SH
    SH_Changelog --> LS_SH
    CCAS --> LS_CCAS
    CCAS_Comment_Shift --> LS_CCAS
    ITHD --> LS_ITHD
    HDWL --> LS_CENTEROPS
    HDWL_Shift --> LS_CENTEROPS
    COSS --> LS_CENTEROPS
    COSSA --> LS_CENTEROPS
    SRInventory_HD --> LS_CENTEROPS
    JIRA_HD --> LS_CENTEROPS
    Snapshot_Outstanding --> LS_CENTEROPS
    COSSA_Latest --> LS_CENTEROPS
    CSM --> LS_CSM
    CSM_Changelog --> LS_CSM
    CSM_Comment_Shift --> LS_CSM
    CSM_Individual --> LS_CSM
    CST --> LS_CSM
    HDWL --> LS_QMS
    JIRA_HD --> LS_QMS
    PipelineRuns --> LS_MONITOR
    DataProgress --> LS_MONITOR
    AAProjects --> LS_AAPROJ
    PDI --> LS_PAGERDUTY
    PDI_Cleansed --> LS_PAGERDUTY

    JIRA_HD --> LS_JIRAHD_A
    AAProjects --> LS_AAPROJ_B
    SurveyFormatted --> LS_SURVEY_FMT
    HD_CarrierVendor --> LS_VENDOR
    CostItemCombined --> LS_COSTITEM
    JIRA_HD --> LS_JIRAHD_B
    CCAS --> LS_CCAS_B

    classDef base fill:#d4e6f1,stroke:#2980b9,color:#000
    classDef view fill:#d5f5e3,stroke:#27ae60,color:#000
    classDef external fill:#fff3cd,stroke:#b8860b,color:#000
    classDef report fill:#fce4ec,stroke:#ad1457,color:#000
    classDef system fill:#eceff1,stroke:#455a64,color:#000

    class JT,JCL,JCM,HD,WL,COSS,COSSA,Staff,SHR,SRI,TD,JTP,JCLP,JCMP,VDL,VVP,VPRP,VTN,DLOG,Survey,PDI base
    class JiraCombined,CSM,CSM_Changelog,CSM_Comment_Shift,CSM_Individual,SH,SH_Changelog,CCAS,CCAS_Comment_Shift,ITHD,ITHD_Changelog,HDWL,HDWL_Shift,JIRA_HD,JiraHDChangelog,RemedyJira,StaffListCleaned,Verification_Dispute,Verification_IS_PR_CT,Verification_Verifier_Performance,SD_Changelog,DataProgress,PipelineRuns,SRInventory_HD,Snapshot_Outstanding,COSSA_Latest,SurveyFormatted,AAProjects,PDI_Cleansed,PDI_Inc,PDI_Agg,HD_CarrierVendor view
    class CST,CostItemCombined external
    class SYS_JIRA,SYS_BMC,SYS_GSHEET,SYS_CONNECT,SYS_INSIGHT,SYS_DATAPIPE,SYS_PAGERDUTY,SYS_METABASE system
    class LS_GSO,LS_CCAS,LS_SH,LS_ITHD,LS_CENTEROPS,LS_CSM,LS_QMS,LS_MONITOR,LS_AAPROJ,LS_PAGERDUTY,LS_JIRAHD_A,LS_AAPROJ_B,LS_SURVEY_FMT,LS_VENDOR,LS_COSTITEM,LS_JIRAHD_B,LS_CCAS_B report
