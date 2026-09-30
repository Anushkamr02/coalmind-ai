"""PDF text -> page-tagged chunks (used for RAG and topics). Needs PyMuPDF (pip install pymupdf).
Scanned pages (no text layer) are OCR'd only if pytesseract + Pillow are installed."""
import re


def split_text(text, size=900, overlap=120):
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    out, cur = [], ""
    for p in paras:
        if len(cur) + len(p) > size and cur:
            out.append(cur)
            cur = cur[-overlap:] + " " + p
        else:
            cur = (cur + "\n" + p).strip()
    if cur:
        out.append(cur)
    return out


def parse_pdf(path, max_pages=None, log=print):
    try:
        import fitz
    except ImportError:
        log("  ! PyMuPDF not installed (pip install pymupdf) - skipping PDF text")
        return []
    doc, chunks, scanned = fitz.open(path), [], 0
    for i, page in enumerate(doc, 1):
        if max_pages and i > max_pages:
            break
        text = page.get_text("text").strip()
        if len(text) < 40:
            scanned += 1
            try:
                import pytesseract
                from PIL import Image
                pix = page.get_pixmap(dpi=200)
                text = pytesseract.image_to_string(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
            except Exception:
                continue
        for piece in split_text(text):
            if len(piece) > 40:
                chunks.append((str(i), piece))
    if scanned:
        log(f"  ({scanned} page(s) had no text layer)")
    return chunks


def render_page(path, page_no, rects=None, dpi=110):
    """PNG bytes of a page with optional highlight rectangles - the click-to-source view for PDFs."""
    import fitz
    doc = fitz.open(path)
    page = doc[int(page_no) - 1]
    for r in rects or []:
        page.draw_rect(fitz.Rect(r), color=(1, 0.5, 0), width=2)
    return page.get_pixmap(dpi=dpi).tobytes("png")


def locate(path, page_no, snippet):
    import fitz
    page = fitz.open(path)[int(page_no) - 1]
    return [tuple(r) for r in page.search_for(snippet[:80])]
