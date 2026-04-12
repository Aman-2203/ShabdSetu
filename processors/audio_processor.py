import os
import time
import socket
import math
import logging
import platform
from pathlib import Path
from typing import List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import requests
except ImportError as e:
    print(f"Missing required package: {e}")
    import sys
    sys.exit(1)

try:
    import google.generativeai as genai
except ImportError as e:
    print(f"Missing required package: {e}")
    print("\nPlease install: pip install google-generativeai")
    import sys
    sys.exit(1)

from .base_processor import DocumentProcessor
from config import progress_tracker

logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────────────────────────
# FFmpeg bootstrap (must run before pydub is imported)
# ────────────────────────────────────────────────────────────────────────────

def _configure_ffmpeg():
    """Locate FFmpeg and add it to PATH so pydub can find it."""
    if platform.system() == 'Windows':
        candidates = [
            r"C:/ffmpeg-8.1-essentials_build/bin/ffmpeg.exe",
            r"C:/ffmpeg-7.1.1-essentials_build/bin/ffmpeg.exe",
            r"C:/ffmpeg/bin/ffmpeg.exe",
            r"C:/Program Files/ffmpeg/bin/ffmpeg.exe",
            os.path.expanduser(r"~/ffmpeg/bin/ffmpeg.exe"),
        ]
        for path in candidates:
            if os.path.exists(path):
                os.environ["PATH"] = (
                    os.path.dirname(path) + os.pathsep + os.environ.get("PATH", "")
                )
                return path

    from shutil import which
    return which("ffmpeg")


_ffmpeg_path = _configure_ffmpeg()

try:
    from pydub import AudioSegment
    if _ffmpeg_path:
        AudioSegment.converter = _ffmpeg_path
        if platform.system() == 'Windows':
            AudioSegment.ffprobe = _ffmpeg_path.replace('ffmpeg.exe', 'ffprobe.exe')
    _PYDUB_AVAILABLE = True
except ImportError:
    _PYDUB_AVAILABLE = False
    logger.warning("pydub not installed — audio processing unavailable")


# ────────────────────────────────────────────────────────────────────────────
# Constants
# ────────────────────────────────────────────────────────────────────────────

SUPPORTED_FORMATS = {'.mp3', '.wav'}
MAX_FILE_SIZE_MB   = 50
CHUNK_DURATION_MS  = 10 * 60 * 1000   # 10 minutes per audio chunk
AUDIO_OVERLAP_MS   = 1500             # 1.5 s overlap to prevent mid-word cuts
MAX_CONCURRENT_AUDIO_CHUNKS = 2       # ElevenLabs: 2 chunks in parallel

ELEVENLABS_BASE_URL  = "https://api.elevenlabs.io/v1"
ELEVENLABS_MODEL_ID  = "scribe_v1"


# ────────────────────────────────────────────────────────────────────────────
# AudioProcessor
# ────────────────────────────────────────────────────────────────────────────

class AudioProcessor(DocumentProcessor):
    """
    Transcribes audio (ElevenLabs STT) then refines the transcript with
    Gemini AI using the existing DocumentProcessor chunking / parallel
    processing infrastructure.

    Billing unit: 1 "page" == 1 minute of audio.
    """

    def __init__(self,
                 elevenlabs_api_key: str,
                 gemini_api_key: str,
                 job_id: str = None,
                 executor=None,
                 max_workers: int = 5):
        super().__init__(gemini_api_key, max_workers, job_id, executor)
        self.elevenlabs_api_key = elevenlabs_api_key
        self.el_headers = {"xi-api-key": elevenlabs_api_key}
        self.model = genai.GenerativeModel('gemini-2.5-pro')
        self.request_timeout = 300

    # ── helpers ──────────────────────────────────────────────────────────────

    def _update(self, current: int, total: int, status: str):
        """Write progress to the shared tracker (preserves user_email / page_usage)."""
        if self.job_id:
            existing = progress_tracker.get(self.job_id, {})
            progress_tracker[self.job_id] = {
                **existing,
                'current':    current,
                'total':      total,
                'status':     status,
                'percentage': int((current / total) * 100) if total > 0 else 0,
            }

    @staticmethod
    def validate_file(file_path: str) -> None:
        """Raise ValueError for unsupported format or oversized file."""
        ext = Path(file_path).suffix.lower()
        if ext not in SUPPORTED_FORMATS:
            raise ValueError(
                f"Unsupported audio format '{ext}'. "
                f"Only {', '.join(SUPPORTED_FORMATS)} files are accepted."
            )
        size_mb = os.path.getsize(file_path) / (1024 * 1024)
        if size_mb > MAX_FILE_SIZE_MB:
            raise ValueError(
                f"File size {size_mb:.1f} MB exceeds the maximum allowed "
                f"{MAX_FILE_SIZE_MB} MB."
            )

    @staticmethod
    def get_duration_minutes(file_path: str) -> float:
        """Return audio duration in minutes using pydub."""
        if not _PYDUB_AVAILABLE:
            raise RuntimeError("pydub is not installed — cannot read audio duration.")
        audio = AudioSegment.from_file(file_path)
        return len(audio) / (60 * 1000)

    # ── ElevenLabs transcription ──────────────────────────────────────────────

    def _split_audio(self, file_path: str, output_dir: str) -> List[str]:
        """
        Split audio into ≤10-minute chunks with a small overlap.
        Returns list of chunk file paths.
        """
        os.makedirs(output_dir, exist_ok=True)
        audio = AudioSegment.from_file(file_path)
        total_ms = len(audio)

        effective_step = CHUNK_DURATION_MS - AUDIO_OVERLAP_MS
        num_chunks = math.ceil(total_ms / effective_step)

        logger.info(
            f"Splitting audio ({total_ms / 60000:.1f} min) into "
            f"{num_chunks} chunks of ≤10 min each"
        )

        ext = Path(file_path).suffix.lstrip('.')
        chunk_paths = []
        for i in range(num_chunks):
            start = max(0, i * effective_step)
            end   = min(start + CHUNK_DURATION_MS, total_ms)
            chunk = audio[start:end]

            chunk_path = os.path.join(output_dir, f"chunk_{i:03d}.{ext}")
            chunk.export(chunk_path, format=ext)
            chunk_paths.append(chunk_path)
            logger.info(f"  chunk {i+1}/{num_chunks}: {len(chunk)/60000:.1f} min")

        return chunk_paths

    def _transcribe_single(self, file_path: str, language: Optional[str]) -> str:
        """Send one audio file to ElevenLabs STT and return the raw text."""
        url = f"{ELEVENLABS_BASE_URL}/speech-to-text"
        with open(file_path, 'rb') as f:
            files = {'file': f}
            data  = {'model_id': ELEVENLABS_MODEL_ID}
            if language:
                lang_map = {
                    'hindi': 'hi',
                    'gujarati': 'gu',
                    'english': 'en',
                    'marathi': 'mr',
                    'bengali': 'bn',
                    'tamil': 'ta',
                    'telugu': 'te',
                    'kannada': 'kn',
                    'malayalam': 'ml',
                    'punjabi': 'pa',
                    'others': None
                }
                lang_lower = language.lower()
                
                if lang_lower in lang_map:
                    iso_code = lang_map[lang_lower]
                elif len(lang_lower) <= 3:
                    iso_code = lang_lower
                else:
                    iso_code = None
                    
                if iso_code:
                    data['language_code'] = iso_code
            resp = requests.post(url, headers=self.el_headers, files=files, data=data, timeout=300)

        if resp.status_code != 200:
            raise RuntimeError(
                f"ElevenLabs STT failed [{resp.status_code}]: {resp.text[:200]}"
            )
        return resp.json().get('text', '')

    def _transcribe_audio(self, file_path: str, language: Optional[str],
                          total_steps: int, completed_so_far: int,
                          duration_min: float = None) -> str:
        """
        Transcribe the full audio file, splitting into 10-min chunks and
        processing MAX_CONCURRENT_AUDIO_CHUNKS at a time.
        Returns the merged raw transcript.
        """
        if duration_min is None:
            duration_min = len(AudioSegment.from_file(file_path)) / 60000
        needs_split = duration_min > 10 or \
                      os.path.getsize(file_path) / (1024 * 1024) > 25

        if not needs_split:
            self._update(completed_so_far + 1, total_steps, "Transcribing audio…")
            text = self._transcribe_single(file_path, language)
            return text

        # Split
        temp_dir = os.path.join(os.path.dirname(file_path), f"_chunks_{self.job_id}")
        chunk_paths = self._split_audio(file_path, temp_dir)
        n = len(chunk_paths)
        transcriptions = [None] * n

        with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_AUDIO_CHUNKS) as pool:
            future_map = {
                pool.submit(self._transcribe_single, cp, language): idx
                for idx, cp in enumerate(chunk_paths)
            }
            done = 0
            for future in as_completed(future_map):
                idx = future_map[future]
                done += 1
                step = completed_so_far + done
                self._update(step, total_steps, "Transcribing audio…")
                try:
                    transcriptions[idx] = future.result()
                    logger.info(f"Chunk {idx+1}/{n} transcribed OK")
                except Exception as e:
                    logger.error(f"Chunk {idx+1} transcription failed: {e}")
                    transcriptions[idx] = f"[TRANSCRIPTION ERROR IN CHUNK {idx+1}]"

        # Cleanup temp chunks
        for cp in chunk_paths:
            try:
                os.remove(cp)
            except Exception:
                pass
        try:
            os.rmdir(temp_dir)
        except Exception:
            pass

        # Merge: join with a space; smart sentence-boundary handling
        parts = []
        for i, t in enumerate(transcriptions):
            t = (t or '').strip()
            if not t:
                continue
            if i == 0 or not parts:
                parts.append(t)
            else:
                prev_last = parts[-1][-1] if parts[-1] else ''
                if prev_last in '.!?।॥':
                    parts.append(t)
                else:
                    parts.append(t)
        return ' '.join(parts)

    # ── Gemini refinement ────────────────────────────────────────────────────

    def _refine_chunk(self, text_chunk: str) -> str:
        """Refine one transcript chunk with Gemini using the linguistic restoration prompt."""
        prompt = f"""ROLE & CORE DIRECTIVE
You are an expert Linguistic Restoration Specialist for multi-lingual content (Hindi, Gujarati, Sanskrit, English). Your goal is to convert raw speech-to-text data into flawless, readable text that can be read aloud without stumbling.

INPUT CONTEXT
The input text contains transcription errors, missing verbs (kriyapad) due to audio drops, and mixed languages.

STRICT GUIDELINES

1. SCRIPT & LANGUAGE HANDLING
 * English: MUST remain in the English (Latin) script. (e.g., write "Doctor" not "डॉक्टर").
 * Indian Languages: Use the appropriate native script (Devanagari/Gujarati) for Hindi, Gujarati, and Sanskrit.
 * Sanskrit/High-Level Terms: Preserve all Shlokas, Jain-path terms, and complex vocabulary exactly as spoken. DO NOT translate or simplify them.

2. LOGICAL RESTORATION (Audio Fixes)
 * Missing Verbs: If the audio cut out or the speaker swallowed a verb, you MUST insert the grammatically correct verb to complete the sentence. The sentence must make complete sense.
 * Low Voice Reconstruction: If words are missing due to disturbance, infer the missing content based on the surrounding context and style. The final output must be seamless.

3. CONTEXTUAL ACCURACY
 * Homophones: Distinguish clearly between similar sounds based on context (e.g., Bhai vs. Bai, Hana vs. Na).
 * Gender Consistency: Check the adjectives and verbs in the paragraph to ensure gendered nouns are correct.

4. FORMATTING FOR READABILITY
 * Punctuation: Add commas, full stops, and question marks where the speaker naturally pauses.
 * Paragraphs: Break long text into logical paragraphs.
 * No Simplification: Keep the language "hard" and authentic. Do not modernize colloquialisms or slang.

INPUT TEXT TO PROCESS:
{text_chunk}

OUTPUT FORMAT
Provide only the CORRECTED_TEXT. Do not include explanations. The output must be ready to be read aloud immediately."""

        max_retries = 3
        for attempt in range(max_retries):
            try:
                old_to = socket.getdefaulttimeout()
                socket.setdefaulttimeout(self.request_timeout)
                try:
                    response = self.model.generate_content(prompt)
                    return response.text.strip()
                finally:
                    socket.setdefaulttimeout(old_to)
            except Exception as e:
                err = str(e).lower()
                if '504' in str(e) or 'timeout' in err or 'timed out' in err:
                    if attempt < max_retries - 1:
                        wait = (2 ** attempt) * 10
                        logger.warning(f"Timeout on refinement attempt {attempt+1}, retrying in {wait}s…")
                        time.sleep(wait)
                        continue
                    logger.error(f"Max retries reached for refinement chunk: {e}")
                    return text_chunk
                else:
                    logger.error(f"Error refining chunk (attempt {attempt+1}): {e}")
                    if attempt < max_retries - 1:
                        time.sleep(5)
                        continue
                    return text_chunk
        return text_chunk

    def _refine_transcript(self, raw_text: str,
                           step_start: int, total_steps: int) -> str:
        """
        Chunk the raw transcript with the existing BaseProcessor chunking
        logic, then refine each chunk with Gemini in parallel (global executor).

        Progress is mapped into the [step_start … REFINEMENT_END] window of
        the overall 0-100 audio pipeline so the bar never jumps backward.
        """
        logger.info(f"Starting Gemini refinement (length: {len(raw_text)} chars)")
        chunks = self.chunk_text(raw_text)
        n_chunks = len(chunks)
        logger.info(f"Text split into {n_chunks} chunks for refinement")

        self._update(step_start, total_steps, "Refining transcript…")

        # --- inline parallel processing with correctly-scaled progress ---
        REFINEMENT_END = 95  # must match the constant in process_audio()
        progress_range = REFINEMENT_END - step_start  # e.g. 45

        results = [None] * n_chunks

        use_global = self.executor is not None
        executor = self.executor if use_global else ThreadPoolExecutor(max_workers=self.max_workers)

        try:
            future_to_index = {
                executor.submit(self.process_with_rate_limit, self._refine_chunk, chunk): i
                for i, chunk in enumerate(chunks)
            }

            completed = 0
            for future in as_completed(future_to_index):
                index = future_to_index[future]
                completed += 1

                # Map chunk progress onto the overall 0-100 scale
                mapped = step_start + int((completed / n_chunks) * progress_range)
                self._update(mapped, total_steps, "Refining transcript…")

                try:
                    result = future.result()
                    results[index] = result if result else chunks[index]
                except Exception as e:
                    if "429" in str(e) or "quota" in str(e).lower() or "rate" in str(e).lower():
                        logger.warning(f"Rate limit hit on refinement chunk {index + 1}. Retrying…")
                        time.sleep(5)
                        try:
                            result = self.process_with_rate_limit(self._refine_chunk, chunks[index])
                            results[index] = result if result else chunks[index]
                        except Exception as retry_err:
                            logger.warning(f"Failed refinement chunk {index + 1} after retry: {retry_err}")
                            results[index] = chunks[index]
                    else:
                        logger.warning(f"Error on refinement chunk {index + 1}: {e}")
                        results[index] = chunks[index]
        finally:
            if not use_global:
                executor.shutdown(wait=False)

        refined_text = '\n\n'.join(results)
        logger.info(f"Refinement complete (output length: {len(refined_text)} chars)")
        return refined_text

    # ── public entry point ────────────────────────────────────────────────────

    def process_audio(self, file_path: str,
                      language: Optional[str] = None) -> dict:
        """
        Full pipeline: validate → transcribe → refine.

        Args:
            file_path: Path to the uploaded .mp3 or .wav file.
            language:  Optional BCP-47 language code for ElevenLabs (e.g. 'hi', 'gu', 'en').

        Returns:
            {
                'raw_transcript':      str,
                'refined_transcript':  str,
                'duration_minutes':    float,
            }
        """
        # 1. Validate format & size (fast, synchronous)
        self.validate_file(file_path)

        duration_min = self.get_duration_minutes(file_path)
        logger.info(f"Audio duration: {duration_min:.2f} minutes")

        # Define a rough total step budget for progress reporting
        # Steps: N transcription chunks + refinement chunks + 1 final
        # We use 100 as an abstract total and map stages to ranges.
        TOTAL = 100
        TRANSCRIPTION_END = 50
        REFINEMENT_END    = 95

        self._update(0, TOTAL, "Starting transcription…")

        # 2. Transcribe
        raw_transcript = self._transcribe_audio(
            file_path, language,
            total_steps=TOTAL,
            completed_so_far=0,
            duration_min=duration_min
        )
        self._update(TRANSCRIPTION_END, TOTAL, "Transcription complete. Refining…")
        logger.info(f"Raw transcript length: {len(raw_transcript)} chars")

        # 3. Refine with Gemini
        refined_transcript = self._refine_transcript(
            raw_transcript,
            step_start=TRANSCRIPTION_END,
            total_steps=TOTAL
        )
        self._update(REFINEMENT_END, TOTAL, "Refinement complete. Building document…")

        return {
            'raw_transcript':     raw_transcript,
            'refined_transcript': refined_transcript,
            'duration_minutes':   duration_min,
        }
