from marker.schema.merged import MergedLine, MergedBlock, FullyMergedBlock
from marker.schema.page import Page
import re
import regex
from typing import List

from marker.settings import settings


def escape_markdown(text):
    # List of characters that need to be escaped in markdown
    characters_to_escape = r"[#]"
    # Escape each of these characters with a backslash
    escaped_text = re.sub(characters_to_escape, r'\\\g<0>', text)
    return escaped_text


def surround_text(s, char_to_insert):
    leading_whitespace = re.match(r'^(\s*)', s).group(1)
    trailing_whitespace = re.search(r'(\s*)$', s).group(1)
    stripped_string = s.strip()
    modified_string = char_to_insert + stripped_string + char_to_insert
    final_string = leading_whitespace + modified_string + trailing_whitespace
    return final_string


def merge_spans(pages: List[Page]) -> List[List[MergedBlock]]:
    merged_blocks = []
    for pagenum, page in enumerate(pages):
        page_num = pagenum + 1
        page_blocks = []
        for blocknum, block in enumerate(page.blocks):
            block_lines = []
            block_id = block.id
            for linenum, line in enumerate(block.lines):
                line_text = ""
                line_id = line.id
                if len(line.spans) == 0:
                    continue
                fonts = []
                for i, span in enumerate(line.spans):
                    font = span.font.lower()
                    next_span = None
                    next_idx = 1
                    while len(line.spans) > i + next_idx:
                        next_span = line.spans[i + next_idx]
                        next_idx += 1
                        if len(next_span.text.strip()) > 2:
                            break

                    fonts.append(font)
                    span_text = span.text

                    # Don't bold or italicize very short sequences
                    # Avoid bolding first and last sequence so lines can be joined properly
                    if len(span_text) > 3 and 0 < i < len(line.spans) - 1:
                        if span.italic and (not next_span or not next_span.italic):
                            span_text = surround_text(span_text, "*")
                        elif span.bold and (not next_span or not next_span.bold):
                            span_text = surround_text(span_text, "**")
                    line_text += span_text
                line_text += f" [[{page_num}_{block_id}_{line_id}]]"

                # For the last line in the block, add the ID
                # if linenum == len(block.lines) - 1 and block.id is not None and block.block_type not in ["Code", "Formula"]:
                #     line_text += f"[[{block.id}]]"

                block_lines.append(MergedLine(
                    text=line_text,
                    fonts=fonts,
                    bbox=line.bbox
                ))
            if len(block_lines) > 0:
                page_blocks.append(MergedBlock(
                    lines=block_lines,
                    pnum=page.pnum,
                    bbox=block.bbox,
                    block_type=block.block_type,
                    heading_level=block.heading_level,
                    id=block.id
                ))
        if len(page_blocks) == 0:
            page_blocks.append(MergedBlock(
                lines=[],
                pnum=page.pnum,
                bbox=page.bbox,
                block_type="Text",
                heading_level=None,
                id=None
            ))
        merged_blocks.append(page_blocks)

    return merged_blocks


def block_surround(text, block_type, heading_level, block_id=None):  # Add block_id parameter
    if block_type == "Section-header":
        if not text.startswith("#"):
            asterisks = "#" * heading_level if heading_level is not None else "##"
            text = f"\n{asterisks} " + text.strip().title() + "\n"
    elif block_type == "Title":
        if not text.startswith("#"):
            text = "# " + text.strip().title() + "\n"
    elif block_type == "Table":
        text = "\n" + text + "\n"
    elif block_type == "List-item":
        text = escape_markdown(text.rstrip()) + "\n"
    elif block_type == "Code":
        text = "\n```\n" + text + "\n```\n"
    elif block_type == "Text":
        text = escape_markdown(text)
    elif block_type == "Formula":
        if text.strip().startswith("$$") and text.strip().endswith("$$"):
            text = text.strip()
            text = "\n" + text + "\n"
    elif block_type == "Caption":
        text = "\n" + escape_markdown(text) + "\n"
    return text


def line_separator(line1, line2, block_type, is_continuation=False):
    # Should cover latin-derived languages and russian
    lowercase_letters = r'\p{Lo}|\p{Ll}|\d'
    hyphens = r'-—¬'
    # Remove hyphen in current line if next line and current line appear to be joined
    hyphen_pattern = regex.compile(rf'.*[{lowercase_letters}][{hyphens}]\s?$', regex.DOTALL)
    if line1 and hyphen_pattern.match(line1) and regex.match(rf"^\s?[{lowercase_letters}]", line2):
        # Split on — or - from the right
        line1 = regex.split(rf"[{hyphens}]\s?$", line1)[0]
        return line1.rstrip() + line2.lstrip()

    all_letters = r'\p{L}|\d'
    sentence_continuations = r',;\(\—\"\'\*'
    sentence_ends = r'。ๆ\.?!'
    line_end_pattern = regex.compile(rf'.*[{lowercase_letters}][{sentence_continuations}]?\s?$', regex.DOTALL)
    line_start_pattern = regex.compile(rf'^\s?[{all_letters}]', regex.DOTALL)
    sentence_end_pattern = regex.compile(rf'.*[{sentence_ends}]\s?$', regex.DOTALL)

    text_blocks = ["Text", "List-item", "Footnote", "Caption", "Figure"]
    if block_type in ["Title", "Section-header"]:
        return line1.rstrip() + " " + line2.lstrip()
    elif block_type == "Formula":
        return line1 + "\n" + line2
    elif line_end_pattern.match(line1) and line_start_pattern.match(line2) and block_type in text_blocks:
        return line1.rstrip() + " " + line2.lstrip()
    elif is_continuation:
        return line1.rstrip() + " " + line2.lstrip()
    elif block_type in text_blocks and sentence_end_pattern.match(line1):
        return line1 + "\n\n" + line2
    elif block_type == "Table":
        return line1 + "\n\n" + line2
    else:
        return line1 + "\n" + line2


def block_separator(prev_block: FullyMergedBlock, block: FullyMergedBlock):
    sep = "\n"
    if prev_block.block_type == "Text":
        sep = "\n\n"

    return sep + block.text


def merge_lines(blocks: List[List[MergedBlock]], max_block_gap=15):
    text_blocks = []
    prev_type = None
    prev_line = None
    block_text = ""
    block_type = ""
    prev_heading_level = None
    pnum = None
    curr_block_id = None  # Add this line

    for idx, page in enumerate(blocks):
        # Insert pagination at every page boundary
        if settings.PAGINATE_OUTPUT:
            if block_text:
                text_blocks.append(
                    FullyMergedBlock(
                        text=block_surround(block_text, prev_type, prev_heading_level, curr_block_id),
                        block_type=prev_type if prev_type else settings.DEFAULT_BLOCK_TYPE,
                        page_start=False,
                        pnum=pnum,
                        block_id=curr_block_id  # Add this line
                    )
                )
                block_text = ""
            text_blocks.append(
                FullyMergedBlock(
                    text="",
                    block_type="Text",
                    page_start=True,
                    pnum=page[0].pnum
                )
            )

        for block in page:
            block_type = block.block_type
            curr_block_id = block.id
            if (block_type != prev_type and prev_type) or (block.heading_level != prev_heading_level and prev_heading_level):
                text_blocks.append(
                    FullyMergedBlock(
                        text=block_surround(block_text, prev_type, prev_heading_level, curr_block_id),
                        block_type=prev_type if prev_type else settings.DEFAULT_BLOCK_TYPE,
                        page_start=False,
                        pnum=block.pnum,
                        block_id=curr_block_id  # Add this line
                    )
                )
                block_text = ""

            prev_type = block_type
            prev_heading_level = block.heading_level
            pnum = block.pnum
            # Join lines in the block together properly
            for i, line in enumerate(block.lines):
                line_height = line.bbox[3] - line.bbox[1]
                prev_line_height = prev_line.bbox[3] - prev_line.bbox[1] if prev_line else 0
                prev_line_x = prev_line.bbox[0] if prev_line else 0
                vertical_dist = min(abs(line.bbox[1] - prev_line.bbox[3]), abs(line.bbox[3] - prev_line.bbox[1])) if prev_line else 0
                prev_line = line
                is_continuation = line_height == prev_line_height and line.bbox[0] == prev_line_x and vertical_dist < max_block_gap
                if block_text:
                    block_text = line_separator(block_text, line.text, block_type, is_continuation)
                else:
                    block_text = line.text

    # Append the final block
    text_blocks.append(
        FullyMergedBlock(
            text=block_surround(block_text, prev_type, prev_heading_level, curr_block_id),
            block_type=block_type if block_type else settings.DEFAULT_BLOCK_TYPE,
            page_start=False,
            pnum=pnum,
            block_id=curr_block_id  # Add this line
        )
    )

    text_blocks = [block for block in text_blocks if (block.text.strip() or block.page_start)]
    return text_blocks


def get_full_text(text_blocks):
    full_text = ""
    prev_block = None
    for block in text_blocks:
        if block.page_start:
            full_text += "\n\n{" + str(block.pnum) + "}" + settings.PAGE_SEPARATOR
        elif prev_block:
            full_text += block_separator(prev_block, block)
        else:
            full_text += block.text
        prev_block = block
    return full_text
