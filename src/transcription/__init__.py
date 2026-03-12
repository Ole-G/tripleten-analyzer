"""Audio download and Whisper transcription for multi-platform videos."""

from . import download_audio as download_audio_module
from . import whisper_transcribe as whisper_transcribe_module

# Keep the submodule names importable for patching and direct module access.
download_audio = download_audio_module
download_audio_file = download_audio_module.download_audio
download_all_audio = download_audio_module.download_all_audio
transcribe_audio = whisper_transcribe_module.transcribe_audio

__all__ = [
    "download_audio",
    "download_audio_file",
    "download_all_audio",
    "transcribe_audio",
]
