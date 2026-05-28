-- SHR:People export - Terminated (IDs with first character < 'H')
SELECT 
  CASE 
    WHEN src.SanitizedID = '' THEN NULL 
    ELSE '"' + src.IdChar + '"' 
  END AS CustID,
  CASE
    WHEN src.`Full Name` IS NULL THEN NULL
    ELSE '"' + DBFN('REPLACE', DBFN('REPLACE', DBFN('REPLACE', DBFN('REPLACE', src.`Full Name`, '\r\n', ''), '\r', ''), '\n', ''), '"', '') + '"'
  END AS CustName,
  src.`Login Name` AS SRNo,
  src.`Product Family`,
  src.`Product ID`,
  src.`Insight Circuit ID`,
  src.`Circuit Owner`,
  src.`Product ID` + ' - ' + src.`PROD DESC` AS `ProductDescription`,
  src.`SR Status`
FROM (
  SELECT
    innerSrc.IdChar,
    innerSrc.`Full Name`,
    innerSrc.`Login Name`,
    innerSrc.`Product Family`,
    innerSrc.`Product ID`,
    innerSrc.`Insight Circuit ID`,
    innerSrc.`Circuit Owner`,
    innerSrc.`PROD DESC`,
    innerSrc.`SR Status`,
    DBFN('REPLACE', DBFN('REPLACE', DBFN('REPLACE', DBFN('REPLACE', innerSrc.IdChar, '\n', ''), '\r', ''), ' ', ''), '\t', '') AS SanitizedID
  FROM (
    SELECT
      STRCONVERT(`ID`, 'CHARACTER200') AS IdChar,
      `Full Name`,
      `Login Name`,
      `Product Family`,
      `Product ID`,
      `Insight Circuit ID`,
      `Circuit Owner`,
      `PROD DESC`,
      `SR Status`
    FROM `SHR:People`
  ) innerSrc
) src
WHERE 
  src.SanitizedID IS NOT NULL
  AND src.SanitizedID <> ''
  AND src.`SR Status` = 'Terminated'
  AND DBFN('UPPER', DBFN('SUBSTR', src.SanitizedID, 1, 1)) < 'H';
