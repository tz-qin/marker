from typing import List, Dict, Any, Optional
from marker.schema.block import Block, Line, Span
from marker.schema.page import Page

from tabled.formats.markdown import markdown_format
from tabled.schema import SpanTableCell

from surya.schema import TextDetectionResult, LayoutResult, OrderResult, LayoutBox

def convert_bbox(textract_bbox: Dict[str, float], page_width: int, page_height: int) -> List[float]:
    """
    Convert Textract BoundingBox format (normalized 0-1) to absolute pixel coordinates
    
    Args:
        textract_bbox: Dictionary with Left, Top, Width, Height in 0-1 range
        page_width: Width of the page in pixels (default 1000)
        page_height: Height of the page in pixels (default 1000)
    
    Returns:
        List[float]: [x0, y0, x1, y1] in absolute pixel coordinates
    """
    x0 = textract_bbox["Left"] * page_width
    y0 = textract_bbox["Top"] * page_height
    width = textract_bbox["Width"] * page_width
    height = textract_bbox["Height"] * page_height
    
    x1 = x0 + width
    y1 = y0 + height
    
    return [x0, y0, x1, y1]

def process_text_block(block: Dict, blocks_by_id: Dict[str, Dict], page_width: int, page_height: int) -> Block:
    """Convert a LINE block to our Block format"""
    # Convert bbox
    bbox = convert_bbox(block["Geometry"]["BoundingBox"], page_width, page_height)
    
    # Create span with the text content
    span = Span(
        text=block["Text"],
        bbox=bbox,
        span_id=block["Id"],
        font="default",  # Textract doesn't provide font info
        font_size=0,    # Textract doesn't provide font size
        font_weight=0   # Textract doesn't provide font weight
    )
    
    # Create line containing the span
    line = Line(
        spans=[span],
        bbox=bbox
    )
    
    # Create block containing the line
    text_block = Block(
        lines=[line],
        bbox=bbox,
        pnum=block["Page"] - 1,  # Textract is 1-indexed
        block_type="Text"
    )
    
    return text_block

def merge_line_blocks_with_cells(blocks_by_id: Dict[str, Dict]) -> Dict[str, Dict]:
    """Process CELL blocks and remove LINE blocks that overlap with cells"""
    
    # Track which LINE blocks to remove
    lines_to_remove = set()
    
    # First find all LINE and CELL blocks
    line_blocks = {
        block_id: block 
        for block_id, block in blocks_by_id.items() 
        if block["BlockType"] == "LINE"
    }
    
    cell_blocks = {
        block_id: block 
        for block_id, block in blocks_by_id.items() 
        if block["BlockType"] == "CELL"
    }
    
    # For each CELL block, check if any LINE blocks have overlapping children
    for cell_id, cell in cell_blocks.items():
        # Get cell's children (WORD blocks)
        cell_children = set()
        for relationship in cell.get("Relationships", []):
            if relationship["Type"] == "CHILD":
                cell_children.update(relationship["Ids"])
        
        # Remove any LINE blocks that have overlapping children with this cell
        for line_id, line in line_blocks.items():
            line_children = set()
            for relationship in line.get("Relationships", []):
                if relationship["Type"] == "CHILD":
                    line_children.update(relationship["Ids"])
            
            # If there's any overlap between children, mark line for removal
            if line_children & cell_children:  # Using set intersection
                lines_to_remove.add(line_id)
        
        # Get text from WORD blocks in order of cell's children
        cell_text = []
        for relationship in cell.get("Relationships", []):
            if relationship["Type"] == "CHILD":
                for word_id in relationship["Ids"]:
                    word_block = blocks_by_id.get(word_id)
                    if word_block and word_block["BlockType"] == "WORD":
                        cell_text.append(word_block["Text"])
        
        # Add table cell ID marker at the end
        # Note: Textract uses 1-based indexing, so subtract 1 for 0-based
        row_idx = cell["RowIndex"] - 1
        col_idx = cell["ColumnIndex"] - 1
        table_idx = cell["TableNumber"]  # Get table number we stored earlier
        cell_id = f"[[t{table_idx}_{row_idx}_{col_idx}]]"
        
        # Update cell's text with joined word texts and cell ID
        cell["Text"] = " ".join(cell_text) + " " + cell_id
    
    # Remove merged LINE blocks
    for line_id in lines_to_remove:
        del blocks_by_id[line_id]
        
    return blocks_by_id

def process_table(block: Dict, blocks_by_id: Dict[str, Dict], page_width: int, page_height: int) -> Block:
    """Convert a TABLE block and its cells to a markdown Block"""
    
    # Get table bbox
    table_bbox = convert_bbox(block["Geometry"]["BoundingBox"], page_width, page_height)
    
    # Get all cell blocks from relationships
    cells = []
    if "Relationships" in block:
        for relationship in block["Relationships"]:
            if relationship["Type"] == "CHILD":
                for cell_id in relationship["Ids"]:
                    cell_block = blocks_by_id.get(cell_id)
                    if cell_block and cell_block["BlockType"] == "CELL":
                        # Convert cell bbox
                        cell_bbox = convert_bbox(cell_block["Geometry"]["BoundingBox"], page_width, page_height)
                        
                        # Create SpanTableCell
                        cell = SpanTableCell(
                            bbox=cell_bbox,
                            text=cell_block.get("Text", ""),  # Text was merged in from LINE blocks
                            row_ids=[cell_block["RowIndex"] - 1],  # Convert to 0-based indexing
                            col_ids=[cell_block["ColumnIndex"] - 1]  # Convert to 0-based indexing
                        )
                        cells.append(cell)
    
    # Convert cells to markdown
    table_markdown = markdown_format(cells)
    
    # Create span with the markdown text
    span = Span(
        text=table_markdown,
        bbox=table_bbox,
        span_id=block["Id"],
        font="default",
        font_size=0,
        font_weight=0
    )
    
    # Create line containing the span
    line = Line(
        spans=[span],
        bbox=table_bbox
    )
    
    # Create block containing the line
    table_block = Block(
        lines=[line],
        bbox=table_bbox,
        pnum=block["Page"] - 1,  # Convert to 0-based indexing
        block_type="Table"
    )
    
    return table_block

def reorder_blocks_by_position(blocks: List[Block]) -> List[Block]:
    """Reorder blocks based on their vertical position"""
    
    # Separate table and non-table blocks
    table_blocks = [b for b in blocks if b.block_type == "Table"]
    text_blocks = [b for b in blocks if b.block_type != "Table"]
    
    # Sort text blocks by vertical position
    text_blocks.sort(key=lambda b: b.bbox[1])  # Sort by y-coordinate (top)
    
    # For each table block, find where it should be inserted
    reordered_blocks = []
    remaining_tables = table_blocks.copy()
    
    for i, text_block in enumerate(text_blocks):
        # Add any tables that should come before this text block
        while remaining_tables:
            table = remaining_tables[0]
            # If table's top is before current text block's top
            if table.bbox[1] < text_block.bbox[1]:
                reordered_blocks.append(table)
                remaining_tables.pop(0)
            else:
                break
                
        reordered_blocks.append(text_block)
    
    # Add any remaining tables at the end
    reordered_blocks.extend(remaining_tables)
    
    return reordered_blocks

def parse_textract_json(json_data: Dict[str, Any], page_width: int = 1000, page_height: int = 1000) -> List[Page]:
    """Main function to convert Textract JSON to Pages objects"""
    
    # Initialize storage
    pages: Dict[int, Page] = {}  # Store pages by page number
    blocks_by_id: Dict[str, Dict] = {}  # Store blocks by ID for relationship lookup
    table_counter = 0
    
    # First pass: Store all blocks by ID and initialize pages with layout
    for block in json_data["Blocks"]:
        blocks_by_id[block["Id"]] = block
        
        if "LAYOUT" in block["BlockType"]:
            # Get page number (Textract is 1-indexed)
            page_num = block["Page"] - 1
            
            # Create page if it doesn't exist
            if page_num not in pages:
                pages[page_num] = Page(
                    pnum=page_num,
                    blocks=[],
                    bbox=[0, 0, page_width, page_height],
                    ocr_method="textract",
                    layout=LayoutResult(
                        bboxes=[],
                        segmentation_map=None,
                        image_bbox=[0, 0, page_width, page_height]
                    )
                )
            
            # Convert bbox and create LayoutBox
            bbox = convert_bbox(block["Geometry"]["BoundingBox"], page_width, page_height)
            layout_box = LayoutBox(
                polygon=[[bbox[0], bbox[1]], [bbox[2], bbox[1]], 
                        [bbox[2], bbox[3]], [bbox[0], bbox[3]]],
                label=block["BlockType"].lower()
            )
            
            # Add to page's layout bboxes
            pages[page_num].layout.bboxes.append(layout_box)
    
    # Process tables first and number their cells
    for block in json_data["Blocks"]:
        if block["BlockType"] == "TABLE":
            # Add table number to all child cells
            if "Relationships" in block:
                for relationship in block["Relationships"]:
                    if relationship["Type"] == "CHILD":
                        for cell_id in relationship["Ids"]:
                            if cell_id in blocks_by_id and blocks_by_id[cell_id]["BlockType"] == "CELL":
                                blocks_by_id[cell_id]["TableNumber"] = table_counter
            table_counter += 1
    
    # Merge LINE blocks into their parent CELL blocks
    blocks_by_id = merge_line_blocks_with_cells(blocks_by_id)
    
    # Reset table counter for block processing
    table_counter = 0
        
    # Process blocks into Pages
    for block in json_data["Blocks"]:
        # Skip blocks that were merged into cells
        if block["Id"] not in blocks_by_id:
            continue
            
        # Get page number (Textract is 1-indexed)
        page_num = block["Page"] - 1
        
        # Create page if it doesn't exist
        if page_num not in pages:
            pages[page_num] = Page(
                pnum=page_num,
                blocks=[],
                bbox=[0, 0, page_width, page_height],
                ocr_method="textract"
            )
            
        # Process based on block type
        if block["BlockType"] == "LINE":
            processed_block = process_text_block(block, blocks_by_id, page_width, page_height)
        elif block["BlockType"] == "TABLE":
            processed_block = process_table(block, blocks_by_id, page_width, page_height)
            table_counter += 1
        else:
            continue
            
        # Add block to page
        pages[page_num].blocks.append(processed_block)
    
    # Convert dict to list and sort by page number
    pages_list = [pages[i] for i in sorted(pages.keys())]
    
    # Reorder blocks on each page
    for page in pages_list:
        page.blocks = reorder_blocks_by_position(page.blocks)
    
    return pages_list
