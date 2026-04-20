WITH SegmentsPrep AS (
  SELECT
    t1.ID AS SystemID,
    t2.ID AS SegmentID,
    t1.InventoryCode AS System,
    t2.InventoryCode AS Segment,

    -- SystemShort: from ItemSubCat if alphabetic, otherwise from InventoryCode prefix
    CASE
      WHEN SAFE.SUBSTR(t2.ItemSubCat, 1, 1) BETWEEN 'A' AND 'Z'
           OR SAFE.SUBSTR(t2.ItemSubCat, 1, 1) BETWEEN 'a' AND 'z'
      THEN t2.ItemSubCat
      ELSE REGEXP_EXTRACT(t2.InventoryCode, r'^(.+?)(?:-Unknown|\s|$)')
    END AS SystemShort,

    -- Extract location from trailing brackets (without brackets)
    REGEXP_EXTRACT(t2.InventoryCode, r'\[([^\]]+)\]\s*$') AS location,

    -- InventoryCode after first space (excluding system name)
    CASE
      WHEN STRPOS(t2.InventoryCode, ' ') > 0 THEN SUBSTR(t2.InventoryCode, STRPOS(t2.InventoryCode, ' ') + 1)
      ELSE ''
    END AS remainder

  FROM
    `pccw-internal-virt-agent-uat`.`SubCableEvents`.`CableInventory` AS t1
  LEFT JOIN
    `pccw-internal-virt-agent-uat`.`SubCableEvents`.`CableInventory` AS t2
  ON
    t2.Parent = t1.ID
  WHERE
    UPPER(t1.Nomenclature) = 'SYSTEM'
    AND UPPER(t1.CableStatus) = 'ACTIVE'
    AND UPPER(t2.CableStatus) = 'ACTIVE'
    -- AND t2.Nomenclature = 'SEGMENT'
),

SegmentsClean AS (
  SELECT
    *,
    -- Remove trailing bracketed location (with or without space before it)
    TRIM(
      CASE
        WHEN REGEXP_CONTAINS(remainder, r'\[.*\]\s*$')
        THEN REGEXP_REPLACE(remainder, r'\[.*\]\s*$', '')
        ELSE remainder
      END
    ) AS segments_str
  FROM SegmentsPrep
),

SegmentsTrimmed AS (
  SELECT
    *,
    -- Remove system prefix from segments_str (case insensitive, special chars handled)
    TRIM(REGEXP_REPLACE(
      segments_str,
      CONCAT(
        r'^(?i)',
        REGEXP_REPLACE(SystemShort, r'[^a-zA-Z0-9]+', r'[\\s\\-_.]*'),
        r'[\\s\\-_.]*'
      ),
      ''
    )) AS segments_without_system
  FROM SegmentsClean
),

SegmentsSplit AS (
  SELECT
    *,
    -- Replace '+' with '&' to unify separators, then split by '&'
    ARRAY(
      SELECT
        -- Remove keywords but keep descriptive text intact
        TRIM(REGEXP_REPLACE(segment_part, r'(?i)\b(cable|segment|fiber|pair)\b', ''))
      FROM
        UNNEST(SPLIT(REGEXP_REPLACE(segments_without_system, r'\s*\+\s*', '&'), '&')) AS segment_part
      WHERE
        TRIM(REGEXP_REPLACE(segment_part, r'(?i)\b(cable|segment|fiber|pair)\b', '')) != ''
        AND NOT REGEXP_CONTAINS(segment_part, r'^\[.*\]$')
    ) AS filtered_segments
  FROM SegmentsTrimmed
),

FinalSegments AS (
  SELECT
    SystemID,
    SegmentID,
    System,
    Segment,
    SystemShort,
    location,

    -- Clean SegmentCode: remove extra spaces, remove bracketed location, and fix spacing before (Decommissioned)/(Terminated)
    TRIM(
      REGEXP_REPLACE(
        REGEXP_REPLACE(
          REGEXP_REPLACE(SegmentCode, r'\s+', ' '),           -- Normalize spaces
          r'\s*\[[^\]]+\]', ''                                 -- Remove square bracketed location if present
        ),
        r'\s*\((Decommissioned|Terminated)\)',                 -- Ensure space before (Decommissioned)/(Terminated)
        r' (\1)'
      )
    ) AS SegmentCode
  FROM SegmentsSplit
  LEFT JOIN UNNEST(filtered_segments) AS SegmentCode
)

SELECT
  DISTINCT
  SystemID,
  SegmentID,
  System,
  Segment,
  SystemShort,

  CASE
    -- Handle Unknown Segment explicitly, ignoring system names
    WHEN LOWER(Segment) LIKE '%unknown segment%' THEN
      CASE
        WHEN LOWER(Segment) LIKE '%decommissioned%' OR LOWER(Segment) LIKE '%terminated%' THEN
          'Segment Unknown (Decommissioned)'
        WHEN location IS NOT NULL THEN
          FORMAT('Segment Unknown (%s)', location)
        ELSE
          'Segment Unknown'
      END

    -- Decommissioned or Terminated segments with possible location range
    WHEN LOWER(Segment) LIKE '%decommissioned%' OR LOWER(Segment) LIKE '%terminated%' THEN
      CASE
        WHEN location IS NOT NULL
            AND REGEXP_CONTAINS(Segment, r'/([A-Z]+\d+)/[^/]+-[A-Z]+/([A-Z]+\d+)/') THEN
          FORMAT(
            'Segment %s (%s - %s) (%s)',
            REGEXP_REPLACE(SegmentCode, r'^(?:-\s*)?' || SystemShort || r'\s*', ''), -- remove system prefix if present
            REGEXP_EXTRACT(Segment, r'/([A-Z]+\d+)/'),
            REGEXP_EXTRACT(Segment, r'/[^/]+-[A-Z]+/([A-Z]+\d+)/'),
            IF(LOWER(Segment) LIKE '%terminated%', 'Terminated', 'Decommissioned')
          )
        WHEN location IS NOT NULL THEN
          FORMAT(
            'Segment %s (%s) (%s)',
            REGEXP_REPLACE(SegmentCode, r'^(?:-\s*)?' || SystemShort || r'\s*', ''),
            location,
            IF(LOWER(Segment) LIKE '%terminated%', 'Terminated', 'Decommissioned')
          )
        ELSE
          FORMAT(
            'Segment %s (%s)',
            REGEXP_REPLACE(SegmentCode, r'^(?:-\s*)?' || SystemShort || r'\s*', ''),
            IF(LOWER(Segment) LIKE '%terminated%', 'Terminated', 'Decommissioned')
          )
      END

    -- Location range pattern without decommissioned/terminated
    WHEN location IS NULL
        AND REGEXP_CONTAINS(Segment, r'/([A-Z]+\d+)/[^/]+-[A-Z]+/([A-Z]+\d+)/') THEN
      FORMAT(
        'Segment %s (%s - %s)',
        REGEXP_REPLACE(SegmentCode, r'^(?:-\s*)?' || SystemShort || r'\s*', ''),
        REGEXP_EXTRACT(Segment, r'/([A-Z]+\d+)/'),
        REGEXP_EXTRACT(Segment, r'/[^/]+-[A-Z]+/([A-Z]+\d+)/')
      )

    -- Default case with location or without, stripping system prefix
    WHEN SegmentCode IS NOT NULL THEN
      CASE
        WHEN location IS NOT NULL THEN FORMAT('Segment %s (%s)', REGEXP_REPLACE(SegmentCode, r'^(?:-\s*)?' || SystemShort || r'\s*', ''), location)
        ELSE FORMAT('Segment %s', REGEXP_REPLACE(SegmentCode, r'^(?:-\s*)?' || SystemShort || r'\s*', ''))
      END

    -- Fallback to location only or generic "Segment"
    ELSE
      CASE
        WHEN location IS NOT NULL THEN FORMAT('Segment (%s)', location)
        ELSE 'Segment'
      END
  END AS SegmentShort

FROM FinalSegments
ORDER BY SystemID, SegmentID, SystemShort, SegmentShort;
