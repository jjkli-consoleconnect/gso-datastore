import pandas as pd
import argparse
import os

def convert_to_json(input_file):
    """
    Converts a CSV or Excel file to a newline-delimited JSON file with the same name.
    
    Args:
        input_file (str): Path to the input CSV or XLSX file.
    """
    try:
        # Extract the filename without extension
        base_name = os.path.splitext(input_file)[0]
        json_file = f"{base_name}.json"  # Auto-generate JSON filename

        # Determine file type based on extension
        file_extension = os.path.splitext(input_file)[-1].lower()

        if file_extension == ".csv":
            df = pd.read_csv(input_file, encoding="utf-8", dtype=str)
        elif file_extension in [".xls", ".xlsx"]:
            df = pd.read_excel(input_file, engine="openpyxl", dtype=str)
        else:
            raise ValueError("Unsupported file format! Please provide a CSV or XLSX file.")

        # Convert DataFrame to newline-delimited JSON
        df.to_json(json_file, orient="records", lines=True, force_ascii=False)

        print(f"✅ Successfully converted '{input_file}' to '{json_file}'!")

    except Exception as e:
        print(f"🚨 Error converting file: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Convert CSV/XLSX to JSON for BigQuery")
    parser.add_argument("input_file", help="Path to the input CSV or XLSX file")

    args = parser.parse_args()
    
    # Run conversion function
    convert_to_json(args.input_file)

# python convert_to_json.py cableinventory.xlsx
# python convert_to_json.py cableinventory.csv