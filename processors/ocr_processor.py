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

    # REMOVED: pdf_to_images method (causing OOM) - integrated into perform_ocr with batching

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

    def process_page(self, index, image):
        """Helper to process a single page (used by thread pool)"""
        try:
            # Note: We don't have total_pages here easily, so we simplify the log
            # self.update_progress(...) call is moved to the batch loop or approx
            base64_image = self.image_to_base64(image)
            text = self.extract_text_from_image(base64_image)
            return text if text.strip() else ""
        except Exception as e:
            logger.warning(f"Error on page {index + 1}: {e}")
            return ""

    def perform_ocr(self, pdf_path: str) -> str:
        """Perform OCR on PDF with batched parallel processing"""
        import gc
        
        pdf_document = fitz.open(pdf_path)
        total_pages = pdf_document.page_count
        
        # Dictionary to store results by page index to ensure order
        results = {}
        
        # Batch settings
        BATCH_SIZE = 5
        
        # Unified Progress Tracking
        # Each page has 2 steps: Convert (50%) + OCR (50%)
        # Total steps = total_pages * 2
        total_steps = total_pages * 2
        completed_steps = 0
        
        try:
            for start_idx in range(0, total_pages, BATCH_SIZE):
                end_idx = min(start_idx + BATCH_SIZE, total_pages)
                current_batch_images = []
                
                logger.info(f"Processing batch: pages {start_idx+1} to {end_idx} of {total_pages}")
                
                # Load images for current batch only
                zoom = 200 / 72  # 200 DPI
                matrix = fitz.Matrix(zoom, zoom)
                
                for page_num in range(start_idx, end_idx):
                    # Update progress (Conversion Step)
                    completed_steps += 1
                    self.update_progress(completed_steps, total_steps, f"Converting page {page_num + 1}/{total_pages}")
                    
                    page = pdf_document[page_num]
                    pix = page.get_pixmap(matrix=matrix)
                    img_data = pix.tobytes("png")
                    image = Image.open(io.BytesIO(img_data))
                    current_batch_images.append((page_num, image))
                
                # Process current batch in parallel
                with ThreadPoolExecutor(max_workers=BATCH_SIZE) as executor:
                    future_to_page = {
                        executor.submit(self.process_page, p_num, img): p_num 
                        for p_num, img in current_batch_images
                    }
                    
                    for future in as_completed(future_to_page):
                        page_num = future_to_page[future]
                        try:
                            # Update progress (OCR Step)
                            completed_steps += 1
                            self.update_progress(completed_steps, total_steps, f"OCR Processing page {page_num + 1}/{total_pages}")
                            
                            text = future.result()
                            results[page_num] = text
                        except Exception as e:
                            logger.error(f"Error processing page {page_num}: {e}")
                            results[page_num] = ""

                # Explicitly clear memory for this batch
                del current_batch_images
                gc.collect()
                
        finally:
            pdf_document.close()

        # Reassemble keys in order
        final_text = []
        for i in range(total_pages):
            if i in results:
                final_text.append(results[i])
        
        return '\n\n'.join([t for t in final_text if t])
