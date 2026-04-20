# CostItemExpiration Script - Technical Summary of Changes

## Error Resolution

### Original Error
```
Error: No matching signature for operator = for argument types: INT64, STRING
```

### Root Cause
The MERGE statement's ON clause attempted to compare:
- `T.costitemid` (INT64 from target table) = `S.costitemid` (STRING from staging)

BigQuery cannot compare different types directly without explicit casting.

---

## Changes Made

### 1. **runMergeFromStaging() Function** (Lines 587-621)

**Type-Safe ON Clause Generation:**
```javascript
// BEFORE (causes error):
onClause = `T.${mergeKey} = S.${mergeKey}`;

// AFTER (handles type mismatch):
onClause = `CAST(T.${mergeKey} AS STRING) = CAST(S.${mergeKey} AS STRING)`;

// For snapshot_date also:
onClause += ` AND CAST(T.snapshot_date AS STRING) = CAST(S.snapshot_date AS STRING)`;
```

**Impact**: Both sides of the comparison are now explicitly cast to STRING, eliminating type mismatch errors.

---

### 2. **deriveSchemaFromSample() Function** (Lines 1-26)

**Smart Column Type Detection:**
- **Date columns** (names containing "date"): `STRING` type (to avoid Excel parsing issues)
- **Merge keys** (costitemid, cost_item_id): `STRING` type (to prevent INT64 assignment)
- **Numeric values**: `FLOAT64` (flexible for all numeric data)
- **Other columns**: `STRING` (default safe type)

**Why This Matters**: Prevents accidental type assignment changes that cause merge conflicts.

---

### 3. **Schema Inference Logic** (Lines 290-330 and 360-395)

**For ALL files processing:**
```javascript
const schemaFields = commonHeaders.map(h => {
  const v = sampleRow[h];
  let type = 'STRING';
  const lowerH = h.toLowerCase();
  
  if (lowerH.includes('date')) {
    if (v && /^\d{4}-\d{2}-\d{2}$/.test(String(v))) {
      type = 'DATE';  // Valid date format
    } else {
      type = 'STRING';  // Store as string if not parseable
    }
  } else if (lowerH === 'costitemid' || lowerH === 'cost_item_id') {
    type = 'STRING';  // Always STRING for merge keys
  } else if (typeof v === 'number') {
    type = 'FLOAT64';  // Numeric values
  }
  return { name: h, type: type };
});
```

**For TO-BE files processing:** Same improved logic applied.

---

### 4. **ensureTableSchema() Function** (Lines 840-890)

**Type Conflict Detection:**
```javascript
// Check for type mismatches
fields.forEach(f => {
  const fLower = String(f.name).toLowerCase();
  if (existingTypeMap[fLower] && 
      existingTypeMap[fLower] !== normalizeBqType(f.type || 'STRING')) {
    Logger.log('WARNING: Column ' + f.name + ' has type mismatch. ' +
      'Target=' + existingTypeMap[fLower] + 
      ' vs Staging=' + normalizeBqType(f.type || 'STRING') + 
      '. Will use target type in MERGE.');
  }
});
```

**Benefits:**
- Identifies schema drift issues early
- Logs helpful diagnostic information
- Allows merge to proceed using target's existing type

---

## Why These Fixes Work

### Problem Chain:
1. Excel files have IDs as text/strings
2. Schema inference sometimes assigned INT64 to numeric-looking IDs
3. Staging table gets STRING, Target gets INT64
4. MERGE compares incompatible types → Error

### Solution:
1. Merge keys are explicitly set to STRING in schema inference
2. ON clause casts both sides to STRING before comparison
3. Type conflicts are detected and logged
4. MERGE proceeds with type-aware operations

---

## Testing the Fix

### Manual Test Steps:
1. Navigate to the Google Apps Script editor for CostItemExpiration
2. Run the script with the latest Excel files
3. Check execution logs for:
   - ✅ No type mismatch errors
   - ✅ MERGE SQL shows CAST operations in ON clause
   - ⚠️ Any TYPE warnings should be noted (but won't block execution)
   - ✅ Final message: "Merge job completed"

### Expected Log Output:
```
DEBUG[ALL] Staging table: pccw-internal-virt-agent-uat.CostItemExpiration.staging_XXXXXXXXX
DEBUG[ALL] Staging rowCount=881
DEBUG[ALL] mergeKeyCandidate=costitemid nullOrEmptyCount=0 of 881
Running MERGE SQL...
MERGE `pccw-internal-virt-agent-uat.CostItemExpiration.expired_cost_items` T
USING (SELECT * FROM ... QUALIFY ROW_NUMBER()...) S
ON (CAST(T.costitemid AS STRING) = CAST(S.costitemid AS STRING) AND CAST(T.snapshot_date AS STRING) = CAST(S.snapshot_date AS STRING))
...
Merge job completed.
```

---

## Prevention of Future Errors

### The script is now more resilient because:

1. **Dynamic Type Detection**: Uses column names and sample values to infer types
2. **Type-Safe Comparisons**: All merge keys automatically cast to STRING
3. **Conflict Detection**: Warns about schema mismatches without failing
4. **Consistent Logic**: Same improved schema handling for both file types
5. **Flexible Casting**: SAFE_CAST used in UPDATE/INSERT with proper type mapping

### If Issues Still Occur:

1. **Check Logs for Warnings**: Type mismatches will be logged with column names
2. **Verify Data Format**: Ensure Excel columns are formatted consistently
3. **Review Schema**: Query the target table schema to see current column types
4. **Reset if Needed**: Use `resetLastProcessed()` to reprocess files

---

## Performance Impact

- **No degradation**: CAST operations are negligible in performance
- **Improved reliability**: Type safety prevents job failures
- **Better logging**: Additional diagnostic information helps troubleshooting

---

## Backward Compatibility

- Existing files and tables continue to work
- Script handles both old and new file formats
- Type conflicts are logged but don't block execution
- Safe for incremental updates to existing tables
