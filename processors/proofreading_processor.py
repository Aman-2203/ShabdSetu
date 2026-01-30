import time
import socket
from typing import Optional
import logging

try:
    import google.generativeai as genai
except ImportError as e:
    print(f"Missing required package: {e}")
    print("\nPlease install required packages:")
    print("pip install google-generativeai")
    import sys
    sys.exit(1)

from .base_processor import DocumentProcessor

logger = logging.getLogger(__name__)


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
