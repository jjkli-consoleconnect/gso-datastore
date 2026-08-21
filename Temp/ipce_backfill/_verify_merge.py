import sys
sys.path.insert(0, r"g:\My Drive\Scripts\Temp\ipce_backfill")
from gcloud_auth import get_client

c = get_client("pccw-internal-virt-agent-uat")
T = "`pccw-internal-virt-agent-uat.GSO.JiraTickets`"

# 1) Field fill-rate across TXCE rows (should now be mostly non-null)
stats = list(c.query(f"""
    SELECT
      COUNT(*) AS total,
      COUNT(Resolution) AS has_resolution,
      COUNT(Description) AS has_description,
      COUNT(FeatureTeam) AS has_featureteam,
      COUNT(Component) AS has_component,
      COUNT(Labels) AS has_labels,
      COUNT(DueDate) AS has_duedate,
      COUNT(TimeSpentSeconds) AS has_timespent,
      COUNT(Creator) AS has_creator
    FROM {T} WHERE Project = 'Transmission TX-CE'
""").result())[0]
print("=== TXCE field fill rates ===")
for k in ["total","has_resolution","has_description","has_featureteam","has_component",
          "has_labels","has_duedate","has_timespent","has_creator"]:
    print(f"  {k:20s}: {getattr(stats,k)}")

# 2) The 5 rows with NULL creator
print("\n=== TXCE rows with NULL Creator ===")
for r in c.query(f"""
    SELECT Key, T, Status, Priority, Resolution, Created, Updated
    FROM {T}
    WHERE Project = 'Transmission TX-CE' AND (Creator IS NULL OR Creator = '')
    ORDER BY Key
""").result():
    print(f"  {r.Key} | {r.T} | {r.Status} | {r.Priority} | {r.Resolution} | {r.Created} -> {r.Updated}")

# 3) Count of TXCE keys present in BQ but absent from the CSV (proxy via null creator)
nullk = list(c.query(f"SELECT Key FROM {T} WHERE Project='Transmission TX-CE' AND (Creator IS NULL OR Creator='')").result())
print(f"\nNull-creator TXCE row count: {len(nullk)}")
