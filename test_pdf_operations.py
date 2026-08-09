import os
import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
import pymupdf as fitz
from pdf_processor import get_pdf_info, split_pdf_pages, merge_custom_pages

def create_sample_pdf(filepath, title, page_count):
    doc = fitz.open()
    for i in range(page_count):
        page = doc.new_page(width=595, height=842) # Size A4
        text = f"{title} - Trang {i+1}"
        page.insert_text((50, 100), text, fontsize=24, color=(0, 0.2, 0.8))
        page.draw_rect(fitz.Rect(40, 40, 555, 802), color=(0.7, 0.7, 0.7), width=2)
    doc.save(filepath)
    doc.close()
    print(f"Đã tạo file mẫu: {filepath} ({page_count} trang)")

def test_workflow():
    test_dir = os.path.join(os.path.dirname(__file__), "test_output")
    os.makedirs(test_dir, exist_ok=True)
    
    sample1 = os.path.join(test_dir, "File_Mau_1.pdf")
    sample2 = os.path.join(test_dir, "File_Mau_2.pdf")
    
    create_sample_pdf(sample1, "Tài liệu A", 3)
    create_sample_pdf(sample2, "Tài liệu B", 3)
    
    # 1. Kiểm tra get_pdf_info
    info1 = get_pdf_info(sample1)
    print("Thông tin File 1:", info1)
    assert info1["page_count"] == 3
    
    # 2. Kiểm tra Tách mỗi trang thành 1 file
    split_dir = os.path.join(test_dir, "test_split")
    created_files = split_pdf_pages(sample1, split_dir, file_pattern="{name}_page_{page}.pdf")
    print(f"Đã tách {len(created_files)} file:")
    for f in created_files:
        print("  -", os.path.basename(f))
    assert len(created_files) == 3
    
    # 3. Kiểm tra Ghép trang tùy chọn (Ví dụ: Trang 1 của File 1 ghép với Trang 2 của File 2)
    merge_items = [
        {"pdf_path": sample1, "page_index": 0}, # Trang 1 File 1
        {"pdf_path": sample2, "page_index": 1}, # Trang 2 File 2
        {"pdf_path": sample1, "page_index": 2}, # Trang 3 File 1
    ]
    out_merge = os.path.join(test_dir, "test_merged_custom.pdf")
    merge_custom_pages(merge_items, out_merge)
    
    info_merged = get_pdf_info(out_merge)
    print("Thông tin file đã ghép:", info_merged)
    assert info_merged["page_count"] == 3
    
    print("\n✅ TẤT CẢ CÁC BƯỚC TEST BACKEND PDF ĐỀU THÀNH CÔNG VÀ CHÍNH XÁC!")

if __name__ == "__main__":
    test_workflow()
