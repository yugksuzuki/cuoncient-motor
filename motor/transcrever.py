#!/usr/bin/env python3
"""Transcreve vídeos com faster-whisper e gera, por arquivo, .json (segmentos + palavras com tempo), .srt e .txt.

Uso: python motor/transcrever.py pasta_entrada pasta_saida [modelo]
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

from faster_whisper import WhisperModel


def ts(s: float) -> str:
    ms = int(round(s * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s2, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s2:02d},{ms:03d}"


def main() -> None:
    ent, sai = Path(sys.argv[1]), Path(sys.argv[2])
    modelo = sys.argv[3] if len(sys.argv) > 3 else "medium"
    sai.mkdir(parents=True, exist_ok=True)
    m = WhisperModel(modelo, device="cpu", compute_type="int8")
    for arq in sorted(ent.iterdir()):
        if not arq.is_file():
            continue
        # decodifica com o ffmpeg (evita o PyAV) e entrega o áudio em float32 16 kHz mono
        bruto = subprocess.run(["ffmpeg", "-v", "error", "-i", str(arq), "-f", "s16le", "-ac", "1", "-ar", "16000", "-"],
                               capture_output=True, check=True).stdout
        audio = np.frombuffer(bruto, dtype=np.int16).astype(np.float32) / 32768.0
        dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(arq)],
                                   capture_output=True, text=True).stdout.strip() or 0)
        segs, info = m.transcribe(audio, language="pt", word_timestamps=True, vad_filter=True, beam_size=5)
        lista = []
        for s in segs:
            lista.append({"ini": round(s.start, 2), "fim": round(s.end, 2), "texto": s.text.strip(),
                          "palavras": [{"p": w.word.strip(), "ini": round(w.start, 2), "fim": round(w.end, 2)} for w in (s.words or [])]})
        (sai / f"{arq.stem}.json").write_text(json.dumps({"arquivo": arq.name, "duracao": dur, "segmentos": lista}, ensure_ascii=False, indent=1), encoding="utf-8")
        (sai / f"{arq.stem}.srt").write_text("\n".join(f"{i}\n{ts(s['ini'])} --> {ts(s['fim'])}\n{s['texto']}\n" for i, s in enumerate(lista, 1)), encoding="utf-8")
        (sai / f"{arq.stem}.txt").write_text(" ".join(s["texto"] for s in lista), encoding="utf-8")
        print(f"{arq.name}: {dur:.1f}s, {len(lista)} segmentos")


if __name__ == "__main__":
    main()
