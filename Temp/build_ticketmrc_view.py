"""Build the new TicketMRC view SQL: swap SHRPeople join for GSOEDPLink.EDP-SR."""
import re

src = r"c:\dev\consoleconnect\Temp\ticketmrc_view.sql"
dst = r"c:\dev\consoleconnect\BigQuery\pccw-internal-virt-agent-uat\Restricted\views\TicketMRC.sql"

sql = open(src, encoding="utf-8-sig").read().replace("\r\n", "\n")

pattern = re.compile(
    r"LEFT JOIN \(\n"
    r"  SELECT\n"
    r"    SRNo,\n"
    r"    ANY_VALUE\(Product_Family\) AS Product_Family,\n"
    r"    ANY_VALUE\(Product_ID\) AS Product_ID,\n"
    r"    ANY_VALUE\(ProductDescription\) AS ProductDescription\n"
    r"  FROM `pccw-internal-virt-agent-uat\.GSO\.SHRPeople`\n"
    r"  GROUP BY SRNo\n"
    r"\) shr"
)

replacement = (
    "LEFT JOIN (\n"
    "  -- SR product enrichment now sourced from the daily EDP mirror (GSOEDPLink.EDP-SR)\n"
    "  SELECT\n"
    "    CONCAT('SR', CAST(sr_id AS STRING)) AS SRNo,\n"
    "    product_id AS Product_ID,\n"
    "    product_family AS Product_Family,\n"
    "    product_description AS ProductDescription\n"
    "  FROM `pccw-internal-virt-agent-uat.GSOEDPLink.EDP-SR`\n"
    ") shr"
)

new_sql, n = pattern.subn(replacement, sql)
if n != 1:
    raise SystemExit(f"Expected exactly 1 replacement, got {n}")
if "SHRPeople" in new_sql:
    raise SystemExit("SHRPeople still referenced!")

header = (
    "-- Restricted.TicketMRC view: ticket + MRC enrichment.\n"
    "-- SR product enrichment joined from GSOEDPLink.EDP-SR (daily mirror of\n"
    "-- edp-prod-lake-data-warehouse.DATA_676.dw_hub_sr). Previously joined GSO.SHRPeople.\n"
)
open(dst, "w", encoding="utf-8", newline="\n").write(header + new_sql)
print(f"OK - written {dst}")
