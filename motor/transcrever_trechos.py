#!/usr/bin/env python3
"""Transcreve trechos curtos já cortados e devolve uma transcrição por vídeo, no tempo do vídeo original.

Os arquivos de entrada se chamam <chave>__<k>__<ini>__<fim>.flac. Cada trecho é transcrito sozinho
(sem VAD e sem contexto do trecho anterior), o que dá tempos de palavra bem mais precisos que a
transcrição do vídeo inteiro quando a pessoa fala com pausas longas. prompts.json (opcional) traz o
texto esperado de cada trecho, usado como initial_prompt.

Uso: python motor/transcrever_trechos.py pasta_entrada pasta_saida [modelo]
"""
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

from faster_whisper import WhisperModel


def main() -> None:
    ent, sai = Path(sys.argv[1]), Path(sys.argv[2])
    modelo = sys.argv[3] if len(sys.argv) > 3 else "medium"
    sai.mkdir(parents=True, exist_ok=True)
    prompts = json.loads((ent / "prompts.json").read_text(encoding="utf-8")) if (ent / "prompts.json").exists() else {}
    m = WhisperModel(modelo, device="cpu", compute_type="int8")
    por_chave = defaultdict(list)
    for arq in sorted(ent.glob("*.flac")):
        chave, k, ini, fim = arq.stem.split("__")
        ini, fim = float(ini), float(fim)
        bruto = subprocess.run(["ffmpeg", "-v", "error", "-i", str(arq), "-f", "s16le", "-ac", "1", "-ar", "16000", "-"],
                               capture_output=True, check=True).stdout
        audio = np.frombuffer(bruto, dtype=np.int16).astype(np.float32) / 32768.0
        segs, _ = m.transcribe(audio, language="pt", word_timestamps=True, vad_filter=False, beam_size=5,
                               condition_on_previous_text=False, initial_prompt=prompts.get(arq.name))
        palavras, textos = [], []
        for s in segs:
            textos.append(s.text.strip())
            for w in s.words or []:
                a, b = ini + max(0.0, w.start), ini + min(w.end, fim - ini)
                palavras.append({"p": w.word.strip(), "ini": round(a, 3), "fim": round(max(a, b), 3)})
        por_chave[chave].append({"k": int(k), "ini": ini, "fim": fim, "texto": " ".join(textos), "palavras": palavras})
        print(f"{arq.name}: {' '.join(textos)}")
    for chave, segs in por_chave.items():
        segs.sort(key=lambda s: s["k"])
        (sai / f"{chave}_trechos.json").write_text(json.dumps({"segmentos": segs}, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
