SELECT
  CASE
    WHEN STARTS_WITH(RemedyLoginID, 'cs-') THEN SUBSTR(RemedyLoginID, 4)
    WHEN RemedyLoginID = 'mktam' THEN 'ken.mk.tam'
    WHEN RemedyLoginID = 'jrliu' THEN 'aliu'
    WHEN RemedyLoginID = 'angelal' THEN 'alui'
    WHEN RemedyLoginID = 'angus' THEN 'ktlau'
    WHEN RemedyLoginID = 'casunders' THEN 'csaunders'
    WHEN RemedyLoginID = 'allip' THEN 'cwtang'
    WHEN RemedyLoginID = 'damehl' THEN 'dmehl'
    WHEN RemedyLoginID = 'ekoutsopoulo' THEN 'ekoutsopoulos'
    WHEN RemedyLoginID = 'hcwong' THEN 'hhcwong'
    WHEN RemedyLoginID = 'hlyeung2' THEN 'hlyeung'
    WHEN RemedyLoginID = 'jluk' THEN 'twluk'
    WHEN RemedyLoginID = 'ayip' THEN 'klyip'
    WHEN RemedyLoginID = 'kchan' THEN 'lcchan'
    WHEN RemedyLoginID = 'kkmcheung' THEN 'kcheung'
    WHEN RemedyLoginID = 'kennethc' THEN 'tkchan'
    WHEN RemedyLoginID = 'kennyh' THEN 'kheung'
    WHEN RemedyLoginID = 'khloe' THEN 'khe'
    WHEN RemedyLoginID = 'kjgan1' THEN 'kjgan'
    WHEN RemedyLoginID = 'mmejia' THEN 'matehortua'
    WHEN RemedyLoginID = 'rcccheng' THEN 'rcheng'
    WHEN RemedyLoginID = 'sbecker' THEN 'sbecker-babel'
    WHEN RemedyLoginID = 'asiags' THEN 'asia_projectteam'
    WHEN RemedyLoginID = 'teddy' THEN 'teddyn'
    WHEN RemedyLoginID = 'michopoulos' THEN 'tvmichopoulos'
    WHEN RemedyLoginID = 'tracylee' THEN 'tlee'
    WHEN RemedyLoginID = 'vincentkc' THEN 'vyau'
    WHEN RemedyLoginID = 'wkchan' THEN 'wkchan1'
    WHEN RemedyLoginID = 'ikonstantako' THEN 'ikonstantakopouloss'
    WHEN RemedyLoginID = 'ymng' THEN 'cfliu'
    ELSE RemedyLoginID
  END AS RemedyLoginID,
  FullName,
  trim(lower(EmailAddress)) AS EmailAddress
FROM
  `pccw-internal-virtual-agent.BMC.UserList`

WHERE LOWER(EmailAddress) LIKE '%pccw%'

ORDER BY FullName ASC;
