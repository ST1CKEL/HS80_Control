#!/usr/bin/env python3
"""Render the spoken announcements in src/hs80_control/assets/voice.

The texts come from hs80_control.voice.CLIPS; speech is synthesised by the
ElevenLabs API and converted with ffmpeg. Only needed after changing a
phrase or the voice -- the rendered clips are committed.

    ELEVENLABS_API_KEY=... tools/render-voice-clips.py [--language de] [clip ...]
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from hs80_control.voice import CLIP_DIRECTORY, CLIPS  # noqa: E402

# ElevenLabs voice ids: "Matilda" (stock) and "Dana" (voice library).
VOICES = {"en": "XrExE9yKIg1WjnnlVkGX", "de": "nF7t9cuYo0u3kuVI9q4B"}
MODEL = "eleven_multilingual_v2"
# A USB sink that was idle swallows the first few milliseconds, so every
# clip starts with a short silence. 24 kHz mono is plenty for speech.
FILTER = (
    "silenceremove=start_periods=1:start_threshold=-50dB,"
    "areverse,silenceremove=start_periods=1:start_threshold=-50dB,areverse,"
    "loudnorm=I=-20:TP=-3:LRA=7,adelay=250,apad=pad_dur=0.15"
)


def synthesise(text: str, voice: str, language: str, key: str) -> bytes:
    request = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice}"
        "?output_format=mp3_44100_128",
        data=json.dumps(
            {
                "text": text + ".",
                "model_id": MODEL,
                "language_code": language,
                "voice_settings": {"stability": 0.6, "similarity_boost": 0.75},
            }
        ).encode(),
        headers={"xi-api-key": key, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"ElevenLabs: HTTP {exc.code}: {exc.read().decode()[:300]}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("clips", nargs="*", help="clip names; default: all")
    parser.add_argument("--language", choices=sorted(CLIPS), action="append")
    parser.add_argument("--voice", help="ElevenLabs voice id instead of the default")
    arguments = parser.parse_args()
    key = os.environ.get("ELEVENLABS_API_KEY", "")
    if not key:
        raise SystemExit("set ELEVENLABS_API_KEY")

    for language, name in (
        (language, name)
        for language in arguments.language or sorted(CLIPS)
        for name in arguments.clips or CLIPS[language]
    ):
        text = CLIPS[language][name]
        target = CLIP_DIRECTORY / language / f"{name}.wav"
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "mp3", "-i", "pipe:0",
                "-af", FILTER, "-ar", "24000", "-ac", "1",
                "-c:a", "pcm_s16le", "-bitexact", str(target),
            ],
            input=synthesise(text, arguments.voice or VOICES[language], language, key),
            check=True,
        )
        print(f"{target.relative_to(ROOT)}: {text!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
