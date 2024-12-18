import time
import json

import pypdfium2 # Needs to be at the top to avoid warnings
import os

os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1" # For some reason, transformers decided to use .isin for a simple op, which is not supported on MPS

import argparse
from marker.convert import convert_single_pdf, convert_single_textract
from marker.logger import configure_logging
from marker.models import load_all_models

from marker.output import save_markdown

configure_logging()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--textract_json", default=None, help="Textract JSON file to parse")
    parser.add_argument("filename", help="PDF file to parse")
    parser.add_argument("output", help="Output base folder path")
    parser.add_argument("--max_pages", type=int, default=None, help="Maximum number of pages to parse")
    parser.add_argument("--start_page", type=int, default=None, help="Page to start processing at")
    parser.add_argument("--langs", type=str, help="Optional languages to use for OCR, comma separated", default=None)
    parser.add_argument("--batch_multiplier", type=int, default=2, help="How much to increase batch sizes")
    args = parser.parse_args()

    langs = args.langs.split(",") if args.langs else None

    model_lst = load_all_models()
    start = time.time()

    if args.textract_json:
        with open(args.textract_json) as f:
            textract_data = json.load(f)
        full_text, images, out_meta = convert_single_textract(
            args.filename,
            textract_data, 
            max_pages=args.max_pages,
        )
    else:
        full_text, images, out_meta = convert_single_pdf(
            args.filename,
            model_lst,
            max_pages=args.max_pages,
            langs=langs, 
            batch_multiplier=args.batch_multiplier
        )

    fname = os.path.basename(args.filename)
    subfolder_path = save_markdown(args.output, fname, full_text, images, out_meta)

    print(f"Saved markdown to the {subfolder_path} folder")
    print(f"Total time: {time.time() - start}")


if __name__ == "__main__":
    main()
