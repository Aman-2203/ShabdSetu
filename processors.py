import time
import base64
import io
import threading
import socket
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional
import re
import logging

try:
    import fitz  # PyMuPDF
    import requests
    import google.generativeai as genai
    from PIL import Image
except ImportError as e:
    print(f"Missing required package: {e}")
    print("\nPlease install required packages:")
    print("pip install PyMuPDF requests google-generativeai python-docx Pillow Flask")
    import sys
    sys.exit(1)

from config import progress_tracker

logger = logging.getLogger(__name__)


class DocumentProcessor:
    """Base class for document processing operations"""

    def __init__(self, gemini_api_key: str, max_workers: int = 5, job_id: str = None, executor=None):
        self.gemini_api_key = gemini_api_key
        genai.configure(api_key=gemini_api_key)
        self.max_workers = max_workers
        self.rate_limit_lock = threading.Lock()
        self.last_request_time = 0
        self.min_request_interval = 0.05  # Reduced for paid tier
        self.job_id = job_id
        self.executor = executor  # External executor (global thread pool)

    def update_progress(self, current: int, total: int, status: str):
        """Update progress for the job"""
        if self.job_id:
            progress_tracker[self.job_id] = {
                'current': current,
                'total': total,
                'status': status,
                'percentage': int((current / total) * 100) if total > 0 else 0
            }

    def chunk_text(self, text: str, max_chunk_size: int = 15000) -> List[str]:
        """Split text into chunks for processing.
        
        Uses multiple strategies to ensure chunks never exceed max_chunk_size:
        1. Split by double newlines (paragraphs)
        2. Split by sentence delimiters (।, ॥, ., ?, !)
        3. Split by single newlines or tabs
        4. Hard character-based split as final fallback
        """
        chunks = []
        current_chunk = ""
        
        # First, try splitting by double newlines (paragraphs)
        paragraphs = text.split('\n\n')
        
        for paragraph in paragraphs:
            # If paragraph itself is too large, break it down further
            if len(paragraph) > max_chunk_size:
                # Save current chunk if exists
                if current_chunk:
                    chunks.append(current_chunk.strip())
                    current_chunk = ""
                
                # Break down large paragraph using sentence delimiters
                sub_chunks = self._split_large_text(paragraph, max_chunk_size)
                chunks.extend(sub_chunks)
            else:
                # Normal paragraph handling
                if len(current_chunk) + len(paragraph) + 2 > max_chunk_size:
                    if current_chunk:
                        chunks.append(current_chunk.strip())
                    current_chunk = paragraph + '\n\n'
                else:
                    current_chunk += paragraph + '\n\n'
        
        if current_chunk.strip():
            chunks.append(current_chunk.strip())
        
        # Final safety check: ensure no chunk exceeds max_chunk_size
        final_chunks = []
        for chunk in chunks:
            if len(chunk) > max_chunk_size:
                final_chunks.extend(self._force_split(chunk, max_chunk_size))
            else:
                final_chunks.append(chunk)
        
        return final_chunks
    
    def _split_large_text(self, text: str, max_chunk_size: int) -> List[str]:
        """Split large text using multiple delimiter strategies."""
        chunks = []
        current_chunk = ""
        
        # Try multiple delimiters in order of preference
        # Hindi/Gujarati sentence ends, then standard punctuation, then structural
        delimiters = ['।', '॥', '। ', '? ', '! ', '. ', '\n', '\t', ' ']
        
        # Find the best delimiter that actually exists in the text
        best_delimiter = None
        for delim in delimiters:
            if delim in text:
                best_delimiter = delim
                break
        
        if best_delimiter:
            segments = text.split(best_delimiter)
            
            for i, segment in enumerate(segments):
                # Add delimiter back (except for last segment)
                segment_with_delim = segment + (best_delimiter if i < len(segments) - 1 else '')
                
                # If single segment is too large, recursively split or force split
                if len(segment_with_delim) > max_chunk_size:
                    if current_chunk:
                        chunks.append(current_chunk.strip())
                        current_chunk = ""
                    # Force split this segment
                    chunks.extend(self._force_split(segment_with_delim, max_chunk_size))
                elif len(current_chunk) + len(segment_with_delim) > max_chunk_size:
                    if current_chunk:
                        chunks.append(current_chunk.strip())
                    current_chunk = segment_with_delim
                else:
                    current_chunk += segment_with_delim
            
            if current_chunk.strip():
                chunks.append(current_chunk.strip())
        else:
            # No delimiters found, force split
            chunks = self._force_split(text, max_chunk_size)
        
        return chunks
    
    def _force_split(self, text: str, max_chunk_size: int) -> List[str]:
        """Force split text at max_chunk_size boundaries.
        
        Tries to split at word boundaries when possible.
        """
        chunks = []
        remaining = text
        
        while len(remaining) > max_chunk_size:
            # Try to find a space near the max_chunk_size to avoid breaking words
            split_point = max_chunk_size
            
            # Look back up to 500 chars for a good break point (space, newline)
            search_start = max(0, max_chunk_size - 500)
            last_space = remaining.rfind(' ', search_start, max_chunk_size)
            last_newline = remaining.rfind('\n', search_start, max_chunk_size)
            
            # Prefer newline over space
            if last_newline > search_start:
                split_point = last_newline + 1
            elif last_space > search_start:
                split_point = last_space + 1
            # else: hard split at max_chunk_size
            
            chunks.append(remaining[:split_point].strip())
            remaining = remaining[split_point:].strip()
        
        if remaining:
            chunks.append(remaining)
        
        return chunks

    def process_with_rate_limit(self, process_func, *args):
        """Execute function with rate limiting"""
        with self.rate_limit_lock:
            current_time = time.time()
            time_since_last = current_time - self.last_request_time
            if time_since_last < self.min_request_interval:
                time.sleep(self.min_request_interval - time_since_last)
            self.last_request_time = time.time()

        return process_func(*args)

    def process_chunks_parallel(self, chunks: List[str], process_func, operation_name: str = "Processing"):
        """Process chunks in parallel with progress tracking.
        Uses global executor if provided, otherwise creates a temporary one.
        """
        results = [None] * len(chunks)
        total = len(chunks)

        # Use provided executor (global pool) or create temporary one
        use_global = self.executor is not None
        executor = self.executor if use_global else ThreadPoolExecutor(max_workers=self.max_workers)

        try:
            future_to_index = {
                executor.submit(self.process_with_rate_limit, process_func, chunk): i
                for i, chunk in enumerate(chunks)
            }

            completed = 0

            for future in as_completed(future_to_index):
                index = future_to_index[future]
                completed += 1
                self.update_progress(completed, total, f"{operation_name}: {completed}/{total}")

                try:
                    result = future.result()
                    results[index] = result if result else chunks[index]
                except Exception as e:
                    if "429" in str(e) or "quota" in str(e).lower() or "rate" in str(e).lower():
                        logger.warning(f"Rate limit hit on chunk {index + 1}. Retrying...")
                        time.sleep(5)
                        try:
                            result = self.process_with_rate_limit(process_func, chunks[index])
                            results[index] = result if result else chunks[index]
                        except Exception as retry_error:
                            logger.warning(f"Failed chunk {index + 1} after retry: {retry_error}")
                            results[index] = chunks[index]
                    else:
                        logger.warning(f"Error on chunk {index + 1}: {e}")
                        results[index] = chunks[index]
        finally:
            # Only shutdown if we created a temporary executor
            if not use_global:
                executor.shutdown(wait=False)

        return results


class ProofreadingProcessor(DocumentProcessor):
    """Handles AI-powered proofreading"""

    def __init__(self, gemini_api_key: str, max_workers: int = 5, job_id: str = None, executor=None):
        super().__init__(gemini_api_key, max_workers, job_id, executor)
        self.model = genai.GenerativeModel('gemini-2.5-pro')
        self.request_timeout = 300  # 5 minutes

    def proofread_chunk(self, text_chunk: str, language: str) -> str:
        """Proofread a text chunk with retry logic"""
        if language.lower() == 'gujarati':
            specific_instructions = """
- Check for proper Gujarati matras (ા, િ, ી, ુ, ૂ, ૃ, ે, ૈ, ો, ૌ)
- Verify correct use of Gujarati conjuncts and half letters
- Check Gujarati punctuation marks (।, ॥, etc.)
- Ensure proper spacing in Gujarati text
- Fix common OCR errors in Gujarati: confusing similar letters (ત/ટ, પ/બ, ક/ખ, etc.)
"""
        else:
            specific_instructions = """
- Check for proper Hindi matras (ा, ि, ी, ु, ू, ृ, े, ै, ो, ौ)
- Verify correct use of Hindi conjuncts and half letters
- Check Hindi punctuation marks (।, ॥, etc.)
- Ensure proper spacing in Hindi text
- Fix common OCR errors in Hindi: confusing similar letters (त/ट, प/फ, क/ख, द/ध, etc.)
"""

        prompt = f"""
ROLE & CORE DIRECTIVE: You are a meticulous digital text restorer. Your sole function is to correct technical errors from an OCR scan while perfectly preserving the original author's voice, style, and intent.

GUIDING PRINCIPLES:
 * The Rule of Minimum Intervention: Only change what is absolutely necessary to fix a clear technical OCR error.
 * The Rule of Stylistic Invisibility: Your corrections must be so perfectly matched to the original style that a reader would never know an OCR error ever existed.

YOUR TASKS (In Order of Priority):
LEVEL 1: PURELY TECHNICAL CORRECTIONS (Mechanical Fixes)
 * Character Recognition: Fix misidentified characters
 * Vowel Marks & Conjuncts ({language}): Correct any missing, extra, or broken matras, bindis/anusvaras, and repair broken conjunct characters
 * Spacing: Eliminate incorrect spaces inside words and add missing spaces between words
 * Punctuation: Correct OCR-mangled punctuation
 * Line Breaks & Hyphenation: Join words incorrectly split by end-of-line hyphenation
 * Formatting & Structure: Reconstruct paragraph breaks, preserve headings
   {specific_instructions}

LEVEL 2: CONTEXT-AWARE CORRECTIONS (Word-Level Fixes)
 * Nonsensical Words: Replace words that are gibberish due to OCR errors
 * Style-Matched Replacement: Replacements MUST match the exact same formality and tone

ABSOLUTE PROHIBITIONS:
  DO NOT TRANSALATE THE CONTENT
 * DO NOT "IMPROVE" THE TEXT
 * DO NOT MODERNIZE OR SANITIZE
 * DO NOT ALTER THE TONE
 * DO NOT CHANGE VOCABULARY LEVEL
 * DO NOT REPHRASE FOR CLARITY

Text to process:
{text_chunk}

Response format:
CORRECTED_TEXT:
[Provide the corrected version with ONLY OCR errors fixed, maintaining the exact original style and tone.]
"""

        max_retries = 3
        for attempt in range(max_retries):
            try:
                old_timeout = socket.getdefaulttimeout()
                socket.setdefaulttimeout(self.request_timeout)

                try:
                    logger.info(f"Proofreading attempt {attempt + 1}/{max_retries}")
                    response = self.model.generate_content(prompt)
                    logger.info(f"Proofreading successful on attempt {attempt + 1}")
                    return self.extract_corrected_text(response.text)
                finally:
                    socket.setdefaulttimeout(old_timeout)

            except Exception as e:
                error_msg = str(e).lower()

                if '504' in str(e) or 'timeout' in error_msg or 'timed out' in error_msg:
                    if attempt < max_retries - 1:
                        wait_time = (2 ** attempt) * 10  # 10s, 20s, 40s
                        logger.warning(f"Timeout on proofreading attempt {attempt + 1}/{max_retries}, retrying in {wait_time}s...")
                        time.sleep(wait_time)
                        continue
                    else:
                        logger.error(f"Max retries reached for proofreading chunk: {e}")
                        return text_chunk
                else:
                    logger.error(f"Error proofreading chunk on attempt {attempt + 1}: {e}")
                    if attempt < max_retries - 1:
                        time.sleep(5)
                        continue
                    return text_chunk

        return text_chunk

    def extract_corrected_text(self, ai_response: str) -> Optional[str]:
        """Extract corrected text from AI response"""
        try:
            if "CORRECTED_TEXT:" in ai_response:
                parts = ai_response.split("CORRECTED_TEXT:")
                if len(parts) > 1:
                    corrected_part = parts[1]

                    for section in ["CHANGES_MADE:", "FORMATTING_APPLIED:"]:
                        if section in corrected_part:
                            corrected_part = corrected_part.split(section)[0]

                    corrected_text = corrected_part.strip()
                    if corrected_text:
                        return corrected_text

            cleaned_response = ai_response.strip()
            prefixes_to_remove = [
                "TECHNICAL ERRORS FOUND:", "CHANGES_MADE:", "FORMATTING_APPLIED:",
                "No technical corrections needed", "No obvious technical errors found"
            ]

            for prefix in prefixes_to_remove:
                if cleaned_response.startswith(prefix):
                    cleaned_response = cleaned_response[len(prefix):].strip()

            if len(cleaned_response) > 50:
                return cleaned_response

            return None

        except Exception:
            return None

    # ========== NEW METHOD: FULL TEXT PROOFREADING WITH AUTO-CHUNKING ==========
    def proofread_full_text(self, full_text: str, language: str) -> str:
        """
        Proofread entire text with automatic chunking and parallel processing.
        
        Args:
            full_text: Complete text to proofread
            language: Language of the text (for language-specific corrections)
            
        Returns:
            Complete proofread text
        """
        logger.info(f"Starting full text proofreading (length: {len(full_text)} chars)")
        
        # Chunk the text
        chunks = self.chunk_text(full_text)
 
        logger.info(f"Text split into {len(chunks)} chunks. Chunk sizes: {[len(c) for c in chunks[:5]]}...")

        
        # Process chunks in parallel
        proofread_chunks = self.process_chunks_parallel(
            chunks,
            lambda chunk: self.proofread_chunk(chunk, language),
            operation_name="Proofreading"
        )
        
        # Join results
        result = '\n\n'.join(proofread_chunks)
        logger.info(f"Proofreading complete (output length: {len(result)} chars)")
        
        return result


class TranslationProcessor(DocumentProcessor):
    """Handles AI-powered translation"""

    def __init__(self, gemini_api_key: str, max_workers: int = 5, job_id: str = None, executor=None):
        super().__init__(gemini_api_key, max_workers, job_id, executor)
        self.model = genai.GenerativeModel('gemini-2.5-pro')
        self.request_timeout = 300  # 5 minutes

        self.translation_prompt = """You are a master translator and literary stylist specializing in texts with high cultural and religious specificity. Your primary goal is to produce a polished, high-register {target_lang} translation that prioritizes natural flow, contextual dignity, and cultural resonance for the specified audience, moving far beyond literal or word-for-word rendering.

USER QUERY:

Translate the following source document into simple yet professional, highly fluent {target_lang}. CRITICAL OUTPUT RULE: The final response MUST consist SOLELY of the translated text. Do not include any introductory phrases, file headers, AI-generated headings, metadata, commentary, or extraneous text whatsoever.

Preprocessing:
The source text may contain scanning errors (OCR mistakes). Your critical first step is to look past these technical flaws to discern the author's true, intended words and meaning. Do not "correct" the style, only reconstruct the text to make it intelligible for translation.

Translation Strategy & Non-Negotiable Rules:

Step 1: Document Analysis (Internal Only): Before generating the first word of the translation, you must internally analyze the provided text to determine:

Original Writing Style: Identify the core stylistic register (e.g., highly academic, devotional/hymnal, historical narrative, legal/prescriptive, direct instructional, etc.).

Document Type & Genre: Classify the specific type (e.g., philosophical treatise, historical commentary, religious sermon, contemporary report) and the general genre (e.g., philosophy, spirituality, history).

Step 2: Automated Style Directive (Genre-Based Translation): You must automatically select the most appropriate elevated {target_lang} style (e.g., Scholarly/Academic, Devotional/Inspirational, or Modern/Interpretive) that directly corresponds to the identified Document Type & Genre (from Step 1). This ensures the translation's tone and syntax are inherently suited to the text's original purpose, without requiring further user input.

Step 3: Target Audience Adaptation (Indian {target_lang}): The entire tone and lexicon must be optimized for an educated Indian {target_lang}-speaking audience. Favor vocabulary and phrasing that is precise, formal, and widely understood within that context, avoiding overly colloquial, American, or casual Western phrasing.

CRITICAL NOTIFICATION: Jain Terminology Preservation: DO NOT TRANSLATE core Jain religious, philosophical, or technical terms (e.g., Anekantavada, Samyak Charitra, Kevala Jnana, Tirthankara, etc.). These terms must be preserved as they are transliterated in the source text, ensuring the religious and scholarly integrity of the document is maintained. Only surrounding contextual language should be translated. Text within <brackets> should be kept as is since it's usually Sanskrit/technical terms.

Text:
{text_chunk}

Response format:
[Provide the complete translated text maintaining structure and formatting.]
"""

    def clean_sanskrit_formatting(self, text: str) -> str:
        """Clean up inconsistent Sanskrit formatting markers"""
        patterns = [
            r'\*sanskrit\*(.*?)\*/sanskrit\*',
            r'\*\*sanskrit\*\*(.*?)\*\*/sanskrit\*\*',
            r'\[sanskrit\](.*?)\[/sanskrit\]',
            r'<sanskrit>(.*?)</sanskrit>',
        ]

        for pattern in patterns:
            text = re.sub(pattern, r'<\1>', text, flags=re.DOTALL | re.IGNORECASE)

        return text

    def translate_chunk(self, text_chunk: str, source_lang: str, target_lang: str) -> str:
        """Translate a text chunk with retry logic"""
        max_retries = 3

        for attempt in range(max_retries):
            try:
                cleaned_text = self.clean_sanskrit_formatting(text_chunk)

                prompt = self.translation_prompt.format(
                    target_lang=target_lang,
                    text_chunk=cleaned_text
                )

                old_timeout = socket.getdefaulttimeout()
                socket.setdefaulttimeout(self.request_timeout)

                try:
                    logger.info(f"Translation attempt {attempt + 1}/{max_retries} (chunk size: {len(prompt)} chars)")
                    response = self.model.generate_content(prompt)
                    logger.info(f"Translation successful on attempt {attempt + 1}")
                    return response.text.strip()
                finally:
                    socket.setdefaulttimeout(old_timeout)

            except Exception as e:
                error_msg = str(e).lower()

                if '504' in str(e) or 'timeout' in error_msg or 'timed out' in error_msg:
                    if attempt < max_retries - 1:
                        wait_time = (2 ** attempt) * 10  # 10s, 20s, 40s
                        logger.warning(f"Timeout on translation attempt {attempt + 1}/{max_retries}, retrying in {wait_time}s...")
                        time.sleep(wait_time)
                        continue
                    else:
                        logger.error(f"Max retries reached for translation chunk: {e}")
                        return text_chunk
                else:
                    logger.error(f"Error translating chunk on attempt {attempt + 1}: {e}")
                    if attempt < max_retries - 1:
                        time.sleep(5)
                        continue
                    return text_chunk

        return text_chunk

    # ========== NEW METHOD: FULL TEXT TRANSLATION WITH AUTO-CHUNKING ==========
    def translate_full_text(self, full_text: str, source_lang: str, target_lang: str) -> str:
        """
        Translate entire text with automatic chunking and parallel processing.
        
        Args:
            full_text: Complete text to translate
            source_lang: Source language
            target_lang: Target language
            
        Returns:
            Complete translated text
        """
        logger.info(f"Starting full text translation (length: {len(full_text)} chars)")
        
        # Chunk the text
        chunks = self.chunk_text(full_text)
        logger.info(f"Text split into {len(chunks)} chunks for translation")
        
        # Process chunks in parallel
        translated_chunks = self.process_chunks_parallel(
            chunks,
            lambda chunk: self.translate_chunk(chunk, source_lang, target_lang),
            operation_name="Translation"
        )
        
        # Join results
        result = '\n\n'.join(translated_chunks)
        logger.info(f"Translation complete (output length: {len(result)} chars)")
        
        return result


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
        
        try:
            for start_idx in range(0, total_pages, BATCH_SIZE):
                end_idx = min(start_idx + BATCH_SIZE, total_pages)
                current_batch_images = []
                
                logger.info(f"Processing batch: pages {start_idx+1} to {end_idx} of {total_pages}")
                
                # Load images for current batch only
                zoom = 200 / 72  # 200 DPI
                matrix = fitz.Matrix(zoom, zoom)
                
                for page_num in range(start_idx, end_idx):
                    self.update_progress(page_num + 1, total_pages, f"Converting page {page_num + 1}/{total_pages}")
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
                            self.update_progress(page_num + 1, total_pages, f"OCR Processing page {page_num + 1}/{total_pages}")
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