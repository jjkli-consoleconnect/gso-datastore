import sys
print(sys.path)
try:
    from service_account_env import ensure
    print('Import successful')
except ImportError as e:
    print(f'Import failed: {e}')
