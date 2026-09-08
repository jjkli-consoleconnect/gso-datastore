$a = Import-Csv 'Temp\Start & Stop Cost Gap Report_Stop Gap To-Do_Table (missing items).csv' | Select-Object -ExpandProperty CostItemID
$b = Import-Csv 'Temp\Start & Stop Cost Gap Report_Stop Gap_Table.csv' | Select-Object -ExpandProperty CostItemID
$missing = $a | Where-Object { $b -notcontains $_ }
Write-Host ('ToDo:' + $a.Count + ' StopGap:' + $b.Count + ' Missing:' + $missing.Count)
$missing -join ','