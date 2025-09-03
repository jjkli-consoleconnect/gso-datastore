import os

def ensure():
    """Ensure GOOGLE_APPLICATION_CREDENTIALS points to the canonical service account
    key used by these scripts. If the environment variable is already set, do nothing.
    """
    if os.environ.get('GOOGLE_APPLICATION_CREDENTIALS'):
        return
    sa_path = r"G:\My Drive\Scripts\service-account.json"
    if os.path.isfile(sa_path):
        os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = sa_path
