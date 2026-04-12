# Processors Package
# Re-exports all processor classes for backwards compatibility

from .base_processor import DocumentProcessor
from .proofreading_processor import ProofreadingProcessor
from .translation_processor import TranslationProcessor
from .ocr_processor import OCRProcessor
from .audio_processor import AudioProcessor

__all__ = [
    'DocumentProcessor',
    'ProofreadingProcessor',
    'TranslationProcessor',
    'OCRProcessor',
    'AudioProcessor',
]
