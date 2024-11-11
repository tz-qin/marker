import json
import argparse
from pathlib import Path
import pypdfium2 as pdfium
import os

from marker.convert import convert_single_pdf, convert_single_textract
from marker.textract.parser import parse_textract_json, process_text_block, process_table

from marker.output import save_markdown


def main():
    parser = argparse.ArgumentParser(description="Test Textract JSON parsing")
    parser.add_argument("filename", help="Input PDF file")
    parser.add_argument("textract_json", help="Input Textract JSON file")
    parser.add_argument("output", help="Output base folder path")
    parser.add_argument("--debug", action="store_true", help="Print debug output")
    args = parser.parse_args()

    # Load the Textract JSON
    with open(args.textract_json) as f:
        textract_data = json.load(f)

    
    full_text, images, out_meta = convert_single_textract(
        args.filename,
        textract_data, 
    )
    

    fname = os.path.basename(args.filename)
    subfolder_path = save_markdown(args.output, fname, full_text, images, out_meta)

    print(f"Saved markdown to the {subfolder_path} folder")

if __name__ == "__main__":
    main()