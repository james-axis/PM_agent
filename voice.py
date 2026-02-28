"""
PM Agent — Voice Transcription
Transcribes Telegram voice notes using SpeechRecognition + Google API.
"""

import os
from config import log


def transcribe_voice(file_path):
    """Transcribe an OGG voice note to text. Returns text or None."""
    try:
        import speech_recognition as sr
        from pydub import AudioSegment

        # Convert OGG to WAV
        wav_path = file_path.replace(".ogg", ".wav")
        audio = AudioSegment.from_ogg(file_path)
        audio.export(wav_path, format="wav")

        recognizer = sr.Recognizer()
        with sr.AudioFile(wav_path) as source:
            audio_data = recognizer.record(source)

        text = recognizer.recognize_google(audio_data)
        log.info(f"Transcribed voice: {text[:100]}...")
        return text
    except sr.UnknownValueError:
        log.warning("Could not understand the voice note.")
        return None
    except sr.RequestError as e:
        log.error(f"Speech recognition service error: {e}")
        return None
    except Exception as e:
        log.error(f"Transcription error: {e}")
        return None
    finally:
        for p in [file_path, file_path.replace(".ogg", ".wav")]:
            try:
                os.remove(p)
            except OSError:
                pass
