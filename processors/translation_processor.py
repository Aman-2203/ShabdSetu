import time
import socket
import re
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
