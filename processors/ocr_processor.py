import base64
import io
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List
import logging

try:
    import fitz  # PyMuPDF
    import requests
    from PIL import Image
except ImportError as e:
    print(f"Missing required package: {e}")
    print("\nPlease install required packages:")
    print("pip install PyMuPDF requests Pillow")
    import sys
    sys.exit(1)

from config import progress_tracker

logger = logging.getLogger(__name__)


class OCRProcessor:
    """Handles OCR operations"""

    def __init__(self, vision_api_key: str, job_id: str = None):
        self.vision_api_key = vision_api_key
        self.vision_api_url = f"https://vision.googleapis.com/v1/images:annotate?key={vision_api_key}"
        self.job_id = job_id

    def update_progress(self, current: int, total: int, status: str):
        """Update progress for the job"""
        if self.job_id:
            progress_tracker[self.job_id] = {
                'current': current,
                'total': total,
                'status': status,
                'percentage': int((current / total) * 100) if total > 0 else 0
            }

    def pdf_to_images(self, pdf_path: str, dpi: int = 200) -> List[Image.Image]:
        """Convert PDF pages to images"""
        pdf_document = fitz.open(pdf_path)
        images = []

        zoom = dpi / 72
        matrix = fitz.Matrix(zoom, zoom)

        total_pages = pdf_document.page_count

        for page_num in range(total_pages):
            self.update_progress(page_num + 1, total_pages, f"Converting page {page_num + 1}/{total_pages}")
            page = pdf_document[page_num]
            pix = page.get_pixmap(matrix=matrix)
            img_data = pix.tobytes("png")
            image = Image.open(io.BytesIO(img_data))
            images.append(image)

        pdf_document.close()
        return images

    def image_to_base64(self, image: Image.Image) -> str:
        """Convert image to base64"""
        buffer = io.BytesIO()
        image.save(buffer, format='PNG', optimize=True, quality=95)
        return base64.b64encode(buffer.getvalue()).decode('utf-8')

    def extract_text_from_image(self, base64_image: str) -> str:
        """Extract text using Google Vision API"""
        request_body = {
            "requests": [{
                "image": {"content": base64_image},
                "features": [{"type": "TEXT_DETECTION", "maxResults": 1}]
            }]
        }

        response = requests.post(
            self.vision_api_url,
            headers={"Content-Type": "application/json"},
            json=request_body,
            timeout=120
        )

        if not response.ok:
            error_msg = response.json().get('error', {}).get('message', 'API request failed')
            raise Exception(f"Google Vision API error: {error_msg}")

        data = response.json()
        annotations = data.get('responses', [{}])[0].get('textAnnotations', [])
        return annotations[0]['description'] if annotations else ""

    def perform_ocr(self, pdf_path: str) -> str:
        """Perform OCR on PDF with parallel processing per page"""
        images = self.pdf_to_images(pdf_path)
        total = len(images)
        extracted_texts = [None] * total

        def ocr_page(index_image_tuple):
            index, image = index_image_tuple
            try:
                self.update_progress(index + 1, total, f"Extracting text from page {index + 1}/{total}")
                base64_image = self.image_to_base64(image)
                text = self.extract_text_from_image(base64_image)
                return (index, text if text.strip() else "")
            except Exception as e:
                logger.warning(f"Error on page {index + 1}: {e}")
                return (index, "")

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(ocr_page, (i, img)) for i, img in enumerate(images)]
            for future in as_completed(futures):
                index, text = future.result()
                extracted_texts[index] = text

        return '\n\n'.join([t for t in extracted_texts if t])
