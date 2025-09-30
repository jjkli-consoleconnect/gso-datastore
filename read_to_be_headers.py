import pandas as pd
fp = r'G:\My Drive\Scripts\Temp\weekly_to_be_expired_cost_item_2025-09-22.xlsx'
df = pd.read_excel(fp, sheet_name=0)
print('Columns:')
for c in df.columns:
    print(repr(str(c)))
print('\nFirst row sample:')
print(df.head(1).to_dict(orient='records'))
