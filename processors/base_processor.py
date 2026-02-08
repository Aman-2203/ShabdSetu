import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List
import logging

try:
    import google.generativeai as genai
except ImportError as e:
    print(f"Missing required package: {e}")
    print("\nPlease install required packages:")
    print("pip install google-generativeai")
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
