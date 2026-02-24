from elevenlabs.client import ElevenLabs
from elevenlabs import play, save
from dotenv import load_dotenv
import os

load_dotenv()

_client: ElevenLabs | None = None


def _get_client() -> ElevenLabs:
    global _client
    if _client is None:
        api_key = os.environ.get("ELEVENLABS_API_KEY")
        if not api_key:
            raise ValueError("ELEVENLABS_API_KEY not found in environment variables.")
        _client = ElevenLabs(api_key=api_key)
    return _client


def text_to_speech(
    text_to_convert: str,
    voice_id: str = "JBFqnCBsd6RMkjVDRZzb",  # default: "George" (multilingual)
    model_id: str = "eleven_multilingual_v2",
) -> bytes:
    """
    Convert text to speech using ElevenLabs and return raw MP3 audio bytes.

    Args:
        text_to_convert: The text to synthesise.
        voice_id: ElevenLabs voice ID (default: George - multilingual).
        model_id: ElevenLabs model ID (default: eleven_multilingual_v2).

    Returns:
        Raw audio bytes (MP3).
    """
    client = _get_client()

    audio_generator = client.text_to_speech.convert(
        text=text_to_convert,
        voice_id=voice_id,
        model_id=model_id,
        output_format="mp3_44100_128",
    )

    # Collect generator chunks into bytes
    audio_bytes = b"".join(audio_generator)
    return audio_bytes