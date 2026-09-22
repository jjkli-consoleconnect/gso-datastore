WITH unpivoted AS (
  -- Collaboration
  SELECT
    Timestamp,
    Your_Department,
    "My experience of collaborating with colleagues from other teams WITHIN the GS&O Department." AS Question,
    My_experience_of_collaborating_with_colleagues_from_other_teams_WITHIN_the_GS_O_Department_ AS Rating,
    _OPTIONAL__What_is_the_key_factor_we_should_address_to_help_improve_cross_team_collaboration_ AS Comment
  FROM `pccw-internal-virt-agent-uat.GSO.2025SurveyResponse_clustered`
  UNION ALL

  -- Goal Clarity
  SELECT
    Timestamp,
    Your_Department,
    "I understand how my work contributes to the team's goals; and my performance expectations are clear and transparent." AS Question,
    I_understand_how_my_work_contributes_to_the_team_s_goals__and_my_performance_expectations_are_clear_and_transparent___ AS Rating,
    _OPTIONAL__What_would_help_improve_transparency_about_goals_and_expectations_ AS Comment
  FROM `pccw-internal-virt-agent-uat.GSO.2025SurveyResponse_clustered`
  UNION ALL

  -- Management Responsiveness
  SELECT
    Timestamp,
    Your_Department,
    "The GS&O Management Team listens to my feedback and takes action when feasible." AS Question,
    The_GS_O_Management_Team_listens_to_my_feedback_and_takes_action_when_feasible_ AS Rating,
    _OPTIONAL__What_feedback__if_any__has_the_GS_O_Management_Team_not_taken_action_on__ AS Comment
  FROM `pccw-internal-virt-agent-uat.GSO.2025SurveyResponse_clustered`
  UNION ALL

  -- Tools Effectiveness
  SELECT
    Timestamp,
    Your_Department,
    "The tools and applications that I use for my daily work are sufficient and effective (e.g., Insight, Remedy, Jira, Shield, etc.)." AS Question,
    The_tools_and_applications_that_I_use_for_my_daily_work_are_sufficient_and_effective__e_g___Insight__Remedy__Jira__Shield__etc___ AS Rating,
    _OPTIONAL___What_is_one_resource__tool__or_training_you_currently_lack_that_would_significantly_improve_your_productivity_ AS Comment
  FROM `pccw-internal-virt-agent-uat.GSO.2025SurveyResponse_clustered`
  UNION ALL

  -- Procedure Clarity
  SELECT
    Timestamp,
    Your_Department,
    "Formal and written procedures are helping improve the deliverables and performance of the GS&O Team." AS Question,
    Formal_and_written_procedures_are_helping_improve_the_deliverables_and_performance_of_the_GS_O_Team_ AS Rating,
    _OPTIONAL__What_aspect_of_your_daily_work_needs_better_written_procedures_ AS Comment
  FROM `pccw-internal-virt-agent-uat.GSO.2025SurveyResponse_clustered`
  UNION ALL

  -- Service Quality
  SELECT
    Timestamp,
    Your_Department,
    "The level of service quality and customer experience that me and my team delivers." AS Question,
    The_level_of_service_quality_and_customer_experience_that_me_and_my_team_delivers_ AS Rating,
    _OPTIONAL__What_is_one_thing_that_your_team_could_do_to_better_service_your_customers_ AS Comment
  FROM `pccw-internal-virt-agent-uat.GSO.2025SurveyResponse_clustered`
  UNION ALL

  -- Service Excellence Control
  SELECT
    Timestamp,
    Your_Department,
    "My ability to deliver service excellence is within my control." AS Question,
    My_ability_to_deliver_service_excellence_is_within_my_control_ AS Rating,
    _OPTIONAL__What_aspect_of_delivering_service_excellence_is_NOT_in_your_control_that_you_think_that_the_GS_O_Management_Team_could_help_with_ AS Comment
  FROM `pccw-internal-virt-agent-uat.GSO.2025SurveyResponse_clustered`
  UNION ALL

  -- Overall Satisfaction
  SELECT
    Timestamp,
    Your_Department,
    "In 2025, I am satisfied with my work experience in the GS&O Team." AS Question,
    In_2025__I_am_satisfied_with_my_work_experience_in_the_GS_O_Team_ AS Rating,
    CONCAT(
      "Frustration: ", IFNULL(What_is_the_single_most_frustrating_thing_you_deal_with_in_your_daily_work_, "N/A"),
      " | Support: ", IFNULL(What_is_one_thing_your_line_manager_and_or_the_GS_O_Management_Team_could_do_to_better_support_your_work_, "N/A"),
      " | Contribution: ", IFNULL(What_is_the_greatest_contribution_of_you_and_your_team_, "N/A")
    ) AS Comment
  FROM `pccw-internal-virt-agent-uat.GSO.2025SurveyResponse_clustered`
)

SELECT
  Timestamp,
  Your_Department,
  Question,
  Rating,
  Comment,
  CASE
    WHEN Question LIKE "My experience of collaborating%" THEN "Internal Collaboration"
    WHEN Question LIKE "I understand how my work contributes%" THEN "Goal Clarity & Alignment"
    WHEN Question LIKE "The GS&O Management Team listens%" THEN "Management Responsiveness"
    WHEN Question LIKE "The tools and applications%" THEN "Tools Effectiveness"
    WHEN Question LIKE "Formal and written procedures%" THEN "Procedure Clarity"
    WHEN Question LIKE "The level of service quality%" THEN "Service Quality Delivered"
    WHEN Question LIKE "My ability to deliver service excellence%" THEN "Service Excellence Control"
    WHEN Question LIKE "In 2025, I am satisfied%" THEN "Overall Satisfaction"
    ELSE "Other"
  END AS SurveyTheme,
  CASE 
    WHEN Rating IN (4,5) THEN "Positive"
    WHEN Rating = 3 THEN "Neutral"
    WHEN Rating IN (1,2) THEN "Negative"
  END AS Sentiment,
  CASE
    WHEN Comment IS NULL 
      OR TRIM(Comment) = "" 
      OR LOWER(Comment) IN ("n/a","na","null","no response") 
      OR LOWER(Comment) LIKE "%none%"
      OR LOWER(Comment) LIKE "%nil%"
      OR LOWER(Comment) LIKE "%not at the moment%"
      OR LOWER(Comment) LIKE "%...%"
    THEN "No Comment"

    WHEN LOWER(Comment) LIKE "%workload%" 
      OR LOWER(Comment) LIKE "%headcount%"
      OR LOWER(Comment) LIKE "%head count%"  
      OR LOWER(Comment) LIKE "%resources%" 
      OR LOWER(Comment) LIKE "%more staff%" 
    THEN "Workload"

    WHEN LOWER(Comment) LIKE "%jira%" 
      OR LOWER(Comment) LIKE "%insight%" 
      OR LOWER(Comment) LIKE "%shield%" 
      OR LOWER(Comment) LIKE "%remedy%" 
      OR LOWER(Comment) LIKE "%tools%"
      OR LOWER(Comment) LIKE "%excel%"  
    THEN "Tools"

    WHEN LOWER(Comment) LIKE "%salary%" 
      OR LOWER(Comment) LIKE "%pay%" 
      OR LOWER(Comment) LIKE "%bonus%" 
      OR LOWER(Comment) LIKE "%benefit%" 
      OR LOWER(Comment) LIKE "%compensation%" 
      OR LOWER(Comment) LIKE "%reward%" 
    THEN "Compensation"

    WHEN LOWER(Comment) LIKE "%communicat%" 
      OR LOWER(Comment) LIKE "%meeting%" 
      OR LOWER(Comment) LIKE "%update%" 
      OR LOWER(Comment) LIKE "%info%" 
      OR LOWER(Comment) LIKE "%comms%" 
      OR LOWER(Comment) LIKE "%feedback%"
      OR LOWER(Comment) LIKE "%attention%"
      OR LOWER(Comment) LIKE "%respons%"
      OR LOWER(Comment) LIKE "%slack%"
    THEN "Communication"

    WHEN LOWER(Comment) LIKE "%procedure%" 
      OR LOWER(Comment) LIKE "%wiki%" 
      OR LOWER(Comment) LIKE "%documentation%" 
      OR LOWER(Comment) LIKE "%manual%" 
    THEN "Documentation"

    -- Refined categories for previous "Other"
    WHEN LOWER(Comment) LIKE "%management%" 
      OR LOWER(Comment) LIKE "%leader%" 
      OR LOWER(Comment) LIKE "%decision%" 
      OR LOWER(Comment) LIKE "%strategy%" 
      OR LOWER(Comment) LIKE "%direction%" 
      OR LOWER(Comment) LIKE "%vision%" 
      OR LOWER(Comment) LIKE "%listen%" 
      OR LOWER(Comment) LIKE "%escalation%" 
      OR LOWER(Comment) LIKE "%superior%"
      OR LOWER(Comment) LIKE "%manager%"
    THEN "Leadership & Decision-Making"

    WHEN LOWER(Comment) LIKE "%training%" 
      OR LOWER(Comment) LIKE "%learning%" 
      OR LOWER(Comment) LIKE "%career%" 
      OR LOWER(Comment) LIKE "%promotion%" 
      OR LOWER(Comment) LIKE "%growth%" 
      OR LOWER(Comment) LIKE "%development%" 
    THEN "Career Development & Training"

    WHEN LOWER(Comment) LIKE "%culture%" 
      OR LOWER(Comment) LIKE "%morale%" 
      OR LOWER(Comment) LIKE "%motivation%" 
      OR LOWER(Comment) LIKE "%trust%" 
      OR LOWER(Comment) LIKE "%respect%" 
      OR LOWER(Comment) LIKE "%engagement%" 
      OR LOWER(Comment) LIKE "%cares%" 
    THEN "Culture & Morale"

    WHEN LOWER(Comment) LIKE "%customer%" 
      OR LOWER(Comment) LIKE "%client%" 
      OR LOWER(Comment) LIKE "%market%" 
      OR LOWER(Comment) LIKE "%demand%" 
      OR LOWER(Comment) LIKE "%expectation%" 
    THEN "Customer & Market Factors"

    WHEN LOWER(Comment) LIKE "%workflow%" 
      OR LOWER(Comment) LIKE "%process%" 
      OR LOWER(Comment) LIKE "%efficiency%" 
      OR LOWER(Comment) LIKE "%bottleneck%" 
      OR LOWER(Comment) LIKE "%delay%" 
      OR LOWER(Comment) LIKE "%guideline%" 
    THEN "Process & Efficiency"

    WHEN LOWER(Comment) LIKE "%system%" 
      OR LOWER(Comment) LIKE "%platform%" 
      OR LOWER(Comment) LIKE "%integration%" 
      OR LOWER(Comment) LIKE "%automation%" 
    THEN "Technology"

    WHEN LOWER(Comment) LIKE "%teamwork%" 
      OR LOWER(Comment) LIKE "%colleague%" 
      OR LOWER(Comment) LIKE "%support%" 
      OR LOWER(Comment) LIKE "%conflict%" 
      OR LOWER(Comment) LIKE "%collab%"
    THEN "Collaboration"

    ELSE "Other"
  END AS PainPointCategory

FROM unpivoted;
