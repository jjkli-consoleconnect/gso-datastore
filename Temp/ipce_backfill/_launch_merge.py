import subprocess, sys
WD = r"g:\My Drive\Scripts\Temp\ipce_backfill"
PY = r"C:\Users\jjkli\AppData\Local\Programs\Python\Python313\python.exe"
out = open(WD + "\\txce_allfields.out", "w")
err = open(WD + "\\txce_allfields.err", "w")
subprocess.Popen([PY, "merge_allfields.py"], cwd=WD, stdout=out, stderr=err,
                 creationflags=subprocess.DETACHED_PROCESS)
print("launched merge_allfields.py detached")
sys.stdout = None
