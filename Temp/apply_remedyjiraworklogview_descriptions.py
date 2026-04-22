from __future__ import annotations

from pathlib import Path
from google.cloud import bigquery

PROJECT = "pccw-internal-virtual-agent"
TABLE_ID = f"{PROJECT}.wanda_ds.RemedyJiraWorkLogView"
DICT_FILE = Path(r"g:\My Drive\Scripts\Temp\RemedyJiraWorkLogView_field_descriptions.md")


def parse_dictionary(md_path: Path) -> dict[str, str]:
    descriptions: dict[str, str] = {}
    for raw_line in md_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line.startswith("| `"):
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) < 5:
            continue
        field = parts[1].strip().strip("`")
        source = parts[2].strip()
        field_type = parts[3].strip()
        desc = parts[4].strip()
        if not field or field.lower() == "field":
            continue
        descriptions[field] = f"Source: {source}. Type: {field_type}. {desc}"
    return descriptions


def update_fields(fields, descriptions: dict[str, str], prefix: str = ""):
    new_fields = []
    updated_count = 0
    for field in fields:
        full_name = f"{prefix}.{field.name}" if prefix else field.name
        api = field.to_api_repr()
        if full_name in descriptions:
            api["description"] = descriptions[full_name]
            updated_count += 1
        if field.fields:
            nested_fields, nested_count = update_fields(field.fields, descriptions, full_name)
            api["fields"] = [nested.to_api_repr() for nested in nested_fields]
            updated_count += nested_count
        new_fields.append(bigquery.SchemaField.from_api_repr(api))
    return new_fields, updated_count


def main() -> None:
    descriptions = parse_dictionary(DICT_FILE)
    client = bigquery.Client(project=PROJECT)
    table = client.get_table(TABLE_ID)

    new_schema, updated_count = update_fields(table.schema, descriptions)
    table.schema = new_schema
    updated = client.update_table(table, ["schema"])

    print(f"Updated schema descriptions on: {updated.full_table_id}")
    print(f"Descriptions loaded from markdown: {len(descriptions)}")
    print(f"Schema fields updated: {updated_count}")

    sample_fields = [
        "Incident_Number",
        "JiraStatus",
        "MTTRStatus",
        "Comments",
        "Comments.Body",
        "Changelog",
        "Changelog.Transitioned_To",
    ]

    def get_field(schema, path: str):
        current = schema
        field_obj = None
        for part in path.split('.'):
            field_obj = next((f for f in current if f.name == part), None)
            if field_obj is None:
                return None
            current = field_obj.fields
        return field_obj

    print("\nVerification samples:")
    verified = client.get_table(TABLE_ID)
    for path in sample_fields:
        field = get_field(verified.schema, path)
        if field is None:
            print(f"- {path}: NOT FOUND")
        else:
            print(f"- {path}: {field.description}")


if __name__ == "__main__":
    main()
