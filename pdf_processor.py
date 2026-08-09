import os
import re
import pymupdf as fitz  # PyMuPDF

def get_pdf_info(pdf_path):
    """
    Trích xuất thông tin cơ bản của file PDF.
    """
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"Không tìm thấy file: {pdf_path}")
    
    doc = fitz.open(pdf_path)
    file_size_bytes = os.path.getsize(pdf_path)
    
    # Đổi dung lượng sang KB hoặc MB
    if file_size_bytes < 1024 * 1024:
        size_str = f"{file_size_bytes / 1024:.1f} KB"
    else:
        size_str = f"{file_size_bytes / (1024 * 1024):.2f} MB"
        
    info = {
        "path": pdf_path,
        "filename": os.path.basename(pdf_path),
        "name_without_ext": os.path.splitext(os.path.basename(pdf_path))[0],
        "page_count": len(doc),
        "size_str": size_str,
        "size_bytes": file_size_bytes
    }
    doc.close()
    return info

def render_page_thumbnail_bytes(pdf_path, page_index, max_dim=220):
    """
    Render hình ảnh trang PDF sang định dạng PNG bytes cho GUI hiển thị thumbnail.
    """
    doc = fitz.open(pdf_path)
    if page_index < 0 or page_index >= len(doc):
        doc.close()
        raise ValueError(f"Chỉ số trang {page_index} nằm ngoài phạm vi (0-{len(doc)-1})")
        
    page = doc.load_page(page_index)
    rect = page.rect
    
    # Tính tỉ lệ scale sao cho chiều rộng hoặc chiều cao tối đa bằng max_dim
    scale = min(max_dim / rect.width, max_dim / rect.height) if rect.width > 0 and rect.height > 0 else 1.0
    matrix = fitz.Matrix(scale, scale)
    
    pix = page.get_pixmap(matrix=matrix, alpha=False)
    img_bytes = pix.tobytes("png")
    
    doc.close()
    return img_bytes

def render_page_high_res_bytes(pdf_path, page_index, scale=2.0):
    """
    Render ảnh chất lượng cao để xem trước phóng to.
    """
    doc = fitz.open(pdf_path)
    page = doc.load_page(page_index)
    matrix = fitz.Matrix(scale, scale)
    pix = page.get_pixmap(matrix=matrix, alpha=False)
    img_bytes = pix.tobytes("png")
    doc.close()
    return img_bytes

def parse_page_range_string(range_str, max_pages):
    """
    Chuyển chuỗi định dạng trang (ví dụ: '1-3, 5, 8-10') thành danh sách các index trang (0-indexed).
    """
    if not range_str or not range_str.strip():
        return list(range(max_pages))
        
    pages = set()
    parts = range_str.split(',')
    
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if '-' in part:
            subparts = part.split('-')
            if len(subparts) == 2 and subparts[0].isdigit() and subparts[1].isdigit():
                start = max(1, int(subparts[0]))
                end = min(max_pages, int(subparts[1]))
                for p in range(start, end + 1):
                    pages.add(p - 1)
        elif part.isdigit():
            p = int(part)
            if 1 <= p <= max_pages:
                pages.add(p - 1)
                
    sorted_pages = sorted(list(pages))
    return sorted_pages if sorted_pages else list(range(max_pages))

def split_pdf_pages(pdf_path, output_dir, file_pattern="{name}_trang_{page}.pdf", range_str="", create_subfolder=False, progress_callback=None):
    """
    Tách từng trang của file PDF thành các file PDF đơn lẻ.
    """
    if not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)
        
    doc = fitz.open(pdf_path)
    total_doc_pages = len(doc)
    base_name = os.path.splitext(os.path.basename(pdf_path))[0]
    
    if create_subfolder:
        target_dir = os.path.join(output_dir, base_name)
        os.makedirs(target_dir, exist_ok=True)
    else:
        target_dir = output_dir

    target_pages = parse_page_range_string(range_str, total_doc_pages)
    created_files = []
    
    total_steps = len(target_pages)
    for idx, page_num in enumerate(target_pages):
        page_1_based = page_num + 1
        
        # Định dạng tên file đầu ra
        file_name = file_pattern.replace("{name}", base_name).replace("{page}", f"{page_1_based:03d}")
        if not file_name.lower().endswith(".pdf"):
            file_name += ".pdf"
            
        out_path = os.path.join(target_dir, file_name)
        
        # Tạo file PDF mới với 1 trang
        new_doc = fitz.open()
        new_doc.insert_pdf(doc, from_page=page_num, to_page=page_num)
        new_doc.save(out_path)
        new_doc.close()
        
        created_files.append(out_path)
        
        if progress_callback:
            progress_callback(idx + 1, total_steps, file_name)
            
    doc.close()
    return created_files

def merge_custom_pages(page_items, output_pdf_path, progress_callback=None):
    """
    Ghép danh sách các trang chọn lọc từ nhiều file PDF khác nhau thành 1 file PDF duy nhất.
    page_items: List các dict [{"pdf_path": str, "page_index": int}, ...]
    """
    if not page_items:
        raise ValueError("Danh sách trang cần ghép đang trống!")
        
    # Tạo thư mục chứa file đầu ra nếu chưa có
    out_dir = os.path.dirname(output_pdf_path)
    if out_dir and not os.path.exists(out_dir):
        os.makedirs(out_dir, exist_ok=True)
        
    merged_doc = fitz.open()
    
    # Cache các file doc mở sẵn để tối ưu tốc độ
    cached_docs = {}
    
    try:
        total_items = len(page_items)
        for idx, item in enumerate(page_items):
            src_path = item["pdf_path"]
            page_idx = item["page_index"]
            
            if src_path not in cached_docs:
                cached_docs[src_path] = fitz.open(src_path)
                
            src_doc = cached_docs[src_path]
            if 0 <= page_idx < len(src_doc):
                merged_doc.insert_pdf(src_doc, from_page=page_idx, to_page=page_idx)
                
            if progress_callback:
                file_basename = os.path.basename(src_path)
                progress_callback(idx + 1, total_items, f"{file_basename} (Trang {page_idx + 1})")
                
        merged_doc.save(output_pdf_path)
        return output_pdf_path
    finally:
        merged_doc.close()
        for d in cached_docs.values():
            d.close()
