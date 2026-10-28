#!/usr/bin/env python3
"""Reel de fala da Cuoncient.

Pega um vídeo de alguém falando e devolve um Reel 9:16 no padrão do Reel da AFE
(BR Oxigênio, 21/10/2026):

- só os trechos escolhidos, com punch-in alternado entre os cortes;
- selo lima no alto à esquerda e logo no alto à direita;
- abertura com título grande e linha de apoio sobre degradê;
- legendas curtas, palavra a palavra agrupadas, com destaque lima;
- fechamento em tela cheia (fundo do próprio vídeo desfocado e esverdeado)
  com título, subtítulo, "chame no WhatsApp · link na bio" e telefone;
- som normalizado a -14 LUFS, cor e nitidez leves, arquivo final abaixo de ~9,5 MB.

Uso:
  python motor/reel_fala.py jobs/mopp-reel.json --out out/
"""
from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
W, H, FPS = 1080, 1920, 30
PONTUACAO = ".,!?;:…"


def log(m: str) -> None:
    print(f"[reel] {m}", flush=True)


def run(cmd: list[str]) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write(r.stderr[-3000:])
        Path("/tmp/reel_ultimo_cmd.json").write_text(json.dumps(cmd))
        raise SystemExit(f"falhou ({r.returncode}): {' '.join(cmd[:4])}")
    return r.stderr


def fontes_css(familia: str) -> str:
    regras = []
    for arq in sorted((ROOT / "fonts" / familia).glob("*-latin-*-normal.woff2")):
        peso = arq.name.split("-latin-")[1].split("-")[0]
        regras.append(f"@font-face{{font-family:'Marca';font-weight:{peso};src:url('{arq.as_uri()}') format('woff2');}}")
    return "".join(regras)


# ------------------------------------------------------------------ legendas
def limpar(p: str) -> str:
    return re.sub(rf"[{re.escape(PONTUACAO)}\"'“”]", "", p).lower()


def montar_legendas(job: dict, transc: dict) -> list[dict]:
    """Agrupa as palavras da transcrição em legendas curtas, já no tempo do vídeo final."""
    corr = {k.lower(): v for k, v in job.get("correcoes", {}).items()}
    destaques = {limpar(d) for d in job.get("destaques", [])}
    palavras = [w for s in transc["segmentos"] for w in s.get("palavras", [])]
    # trocas por posição: [[inicio_da_palavra, "novo texto"]]; texto vazio apaga a palavra
    for t_ini, novo in job.get("trocas", []):
        for w in palavras:
            if abs(w["ini"] - t_ini) < 0.03:
                w["p"] = novo
    palavras = [w for w in palavras if w["p"].strip()]
    saida, acc = [], 0.0
    for ini, fim in job["trechos"]:
        # o whisper estica a palavra até a pausa seguinte: entra a palavra que ocupa de fato o trecho
        ws = [w for w in palavras
              if min(w["fim"], fim) - max(w["ini"], ini) >= min(0.12, 0.5 * (w["fim"] - w["ini"]))]
        grupo: list[dict] = []

        def fechar():
            if not grupo:
                return
            txt = []
            for w in grupo:
                p = corr.get(w["p"].lower(), corr.get(limpar(w["p"]), w["p"]))
                p = html.escape(p)
                txt.append(f"<em>{p}</em>" if limpar(p) in destaques else p)
            saida.append({"de": acc + max(0, grupo[0]["ini"] - ini), "ate": acc + min(fim, grupo[-1]["fim"]) - ini + 0.12,
                          "texto": " ".join(txt)})
            grupo.clear()

        for w in ws:
            if grupo:
                chars = sum(len(x["p"]) + 1 for x in grupo) + len(w["p"])
                pausa = w["ini"] - grupo[-1]["fim"]
                if len(grupo) >= job.get("max_palavras", 3) or chars > job.get("max_chars", 22) or pausa > 0.35 \
                        or grupo[-1]["p"][-1:] in PONTUACAO:
                    fechar()
            grupo.append(w)
        fechar()
        acc += fim - ini
    # cada legenda fica até a próxima começar (sem buraco curto)
    for a, b in zip(saida, saida[1:]):
        if b["de"] - a["ate"] < 0.25:
            a["ate"] = b["de"]
    ate_abertura = job.get("abertura", {}).get("ate", 0)
    return [l for l in saida if l["de"] >= ate_abertura - 0.05]


# ------------------------------------------------------------------ HTML
def pagina(css: str, corpo: str, fundo: str = "transparent") -> str:
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{css}
html,body{{margin:0;background:{fundo}}}*{{box-sizing:border-box}}
.r{{width:{W}px;height:{H}px;position:relative;overflow:hidden;font-family:'Marca',sans-serif}}
em{{font-style:normal}}
</style></head><body><div class="r">{corpo}</div></body></html>"""


def html_fixo(css, cor, logo, selo):
    return pagina(css, f"""
<div style="position:absolute;left:72px;top:300px;background:{cor['destaque']};color:{cor['texto_sobre_destaque']};font-weight:800;
font-size:27px;letter-spacing:.12em;padding:9px 18px;border-radius:6px;text-transform:uppercase">{html.escape(selo)}</div>
<img src="{logo}" style="position:absolute;right:66px;top:282px;width:92px;filter:drop-shadow(0 4px 12px rgba(0,0,0,.45))">""")


def html_abertura(css, cor, ab):
    return pagina(css, f"""
<div style="position:absolute;left:0;right:0;bottom:0;height:1150px;background:linear-gradient(180deg,rgba(0,0,0,0) 0%,rgba(0,0,0,.55) 45%,rgba(0,0,0,.82) 100%)"></div>
<div style="position:absolute;left:72px;right:90px;top:1060px">
<div style="color:#fff;font-weight:800;font-size:76px;line-height:1.05;letter-spacing:-.01em;text-shadow:0 4px 18px rgba(0,0,0,.35)">{ab['titulo'].replace('<em>', f'<em style="color:{cor["destaque_texto"]}">')}</div>
<div style="color:#fff;font-size:31px;margin-top:26px;font-weight:500"><b style="font-weight:800">{html.escape(ab.get('nome',''))}</b>{(' · ' if ab.get('nome') else '') + html.escape(ab.get('linha',''))}</div>
</div>""")


def html_legenda(css, cor, texto):
    texto = texto.replace("<em>", f'<em style="color:{cor["destaque_texto"]}">')
    return pagina(css, f"""
<div style="position:absolute;left:60px;right:60px;top:1235px;display:flex;justify-content:center">
<div style="color:#fff;font-weight:800;font-size:68px;line-height:1.1;text-align:center;
text-shadow:0 3px 0 rgba(0,0,0,.35),0 6px 22px rgba(0,0,0,.55)">{texto}</div></div>""")


def html_fechamento(css, cor, logo, fundo_uri, f, selo):
    t2 = f'<br><span style="color:{cor["destaque_texto"]}">{html.escape(f["titulo2"])}</span>' if f.get("titulo2") else ""
    return pagina(css, f"""
<img src="{fundo_uri}" style="position:absolute;inset:0;width:{W}px;height:{H}px;object-fit:cover">
<div style="position:absolute;inset:0;background:linear-gradient(180deg,rgba(1,40,20,.80),rgba(1,73,36,.86) 55%,rgba(1,50,26,.92))"></div>
<div style="position:absolute;left:80px;right:80px;top:0;bottom:0;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;color:#fff">
<img src="{logo}" style="width:232px;margin-bottom:40px">
<div style="background:{cor['destaque']};color:{cor['texto_sobre_destaque']};font-weight:800;font-size:27px;letter-spacing:.12em;padding:9px 18px;border-radius:6px;text-transform:uppercase">{html.escape(f.get('selo', selo))}</div>
<div style="font-weight:800;font-size:58px;line-height:1.12;margin-top:30px">{html.escape(f['titulo'])}{t2}</div>
<div style="font-size:32px;line-height:1.4;margin-top:24px;color:#d9e8d0;max-width:860px">{html.escape(f.get('sub',''))}</div>
<div style="width:880px;height:1px;background:rgba(255,255,255,.18);margin:52px 0 40px"></div>
<div style="font-weight:700;font-size:24px;letter-spacing:.28em;color:#d9e8d0">{html.escape(f.get('cta','CHAME NO WHATSAPP · LINK NA BIO'))}</div>
<div style="font-weight:800;font-size:46px;margin-top:14px">{html.escape(f.get('fone',''))}</div>
</div>""", fundo="#014924")


def renderizar(paginas: dict[str, str], pasta: Path) -> None:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        nav = p.chromium.launch()
        pg = nav.new_page(viewport={"width": W, "height": H})
        for nome, conteudo in paginas.items():
            arq = pasta / f"{nome}.html"
            arq.write_text(conteudo, encoding="utf-8")
            pg.goto(arq.as_uri()); pg.wait_for_timeout(250)
            pg.screenshot(path=str(pasta / f"{nome}.png"), omit_background=True)
        nav.close()


# ------------------------------------------------------------------ vídeo
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("job")
    ap.add_argument("--out", default="out")
    a = ap.parse_args()
    job = json.loads(Path(a.job).read_text(encoding="utf-8"))
    marca = json.loads((ROOT / "brands" / f"{job['marca']}.json").read_text(encoding="utf-8"))
    cor = marca["cores"]
    css = fontes_css(marca["fonte"])
    logo = (ROOT / marca["logo"]).resolve().as_uri()
    saida = Path(a.out).resolve() / job["id"]
    tmp = saida / "_trabalho"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    video = Path(job["video"]).resolve()
    transc = json.loads(Path(job["transcricao"]).read_text(encoding="utf-8"))
    legendas = montar_legendas(job, transc)
    trechos = job["trechos"]
    S = sum(f - i for i, f in trechos)
    fe = job["fechamento"]
    DF = fe.get("dur", 3.0)
    D = S + DF
    log(f"{len(trechos)} trechos, {S:.1f}s de fala + {DF}s de fechamento; {len(legendas)} legendas")

    # fundo do fechamento: um quadro do vídeo, desfocado
    q = job.get("quadro", {})
    t_fundo = trechos[-1][1] - 0.5
    run(["ffmpeg", "-v", "error", "-y", "-ss", str(t_fundo), "-i", str(video), "-frames:v", "1",
         "-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=40:3", str(tmp / "fundo.jpg")])
    paginas = {"fixo": html_fixo(css, cor, logo, job["selo"]),
               "fech": html_fechamento(css, cor, logo, (tmp / "fundo.jpg").as_uri(), fe, job["selo"])}
    if job.get("abertura"):
        paginas["abertura"] = html_abertura(css, cor, job["abertura"])
    for k, l in enumerate(legendas):
        paginas[f"leg_{k:02d}"] = html_legenda(css, cor, l["texto"])
    renderizar(paginas, tmp)
    (saida / f"{job['id']}_legendas.json").write_text(json.dumps(legendas, ensure_ascii=False, indent=1), encoding="utf-8")

    # 1ª passada do loudnorm no áudio já cortado
    partes = "".join(f"[0:a]atrim={i}:{f},asetpts=PTS-STARTPTS[a{k}];" for k, (i, f) in enumerate(trechos))
    conc = "".join(f"[a{k}]" for k in range(len(trechos))) + f"concat=n={len(trechos)}:v=0:a=1[ac]"
    med = run(["ffmpeg", "-hide_banner", "-i", str(video), "-filter_complex", partes + conc + ";[ac]loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json[o]",
               "-map", "[o]", "-f", "null", "-"])
    m = json.loads(med[med.rfind("{"):med.rfind("}") + 1])
    log(f"áudio: {m['input_i']} LUFS -> -14")

    zooms = q.get("zooms", [1.15, 1.32])
    cx, cy = q.get("cx", 0.5), q.get("cy", 0.38)
    eq = job.get("cor", "eq=contrast=1.05:saturation=1.08:brightness=-0.005,unsharp=5:5:0.45:5:5:0")
    f = []
    for k, (i, fim) in enumerate(trechos):
        z = zooms[k % len(zooms)]
        if q.get("pos"):  # enquadramento por trecho: [[cx, cy], ...]
            cx, cy = q["pos"][k % len(q["pos"])]
        sw, sh = int(W * z) // 2 * 2, int(H * z) // 2 * 2
        x = max(0, min(sw - W, int(cx * sw - W / 2)))
        y = max(0, min(sh - H, int(cy * sh - H / 2)))
        # cada trecho entra como uma entrada separada (-ss/-t): evita guardar o vídeo inteiro na memória
        f.append(f"[{k}:v]setpts=PTS-STARTPTS,fps={FPS},scale={sw}:{sh}:flags=lanczos,crop={W}:{H}:{x}:{y},setsar=1,{eq},format=yuv420p,trim=duration={fim - i:.3f}[v{k}]")
        f.append(f"[{k}:a]asetpts=PTS-STARTPTS,atrim=duration={fim - i:.3f},afade=t=in:d=0.02,afade=t=out:st={fim - i - 0.03:.3f}:d=0.03[a{k}]")
    n = len(trechos)
    f.append("".join(f"[v{k}][a{k}]" for k in range(n)) + f"concat=n={n}:v=1:a=1[vc][ac]")
    # uma faixa única de sobreposição (bem mais rápido que dezenas de overlays):
    # cada intervalo recebe um PNG já composto (fixo + abertura ou fixo + legenda)
    from PIL import Image
    fixo = Image.open(tmp / "fixo.png").convert("RGBA")
    camadas = []
    ab_ate = job["abertura"]["ate"] if job.get("abertura") else 0
    if ab_ate:
        camadas.append((0.0, ab_ate, tmp / "abertura.png"))
    for k, l in enumerate(legendas):
        camadas.append((max(l["de"], ab_ate), min(l["ate"], S), tmp / f"leg_{k:02d}.png"))
    marcos = sorted({0.0, S, *[c[0] for c in camadas], *[c[1] for c in camadas]})
    cache, linhas = {}, []
    for a0, a1 in zip(marcos, marcos[1:]):
        if a1 - a0 < 1e-3:
            continue
        meio = (a0 + a1) / 2
        ativa = next((c[2] for c in camadas if c[0] <= meio < c[1]), None)
        if ativa not in cache:
            img = fixo.copy()
            if ativa:
                img.alpha_composite(Image.open(ativa).convert("RGBA"))
            arq = tmp / f"ov_{len(cache):03d}.png"
            img.save(arq)
            cache[ativa] = arq
        linhas.append((cache[ativa], a1 - a0))
    lista = tmp / "sobreposicao.txt"
    lista.write_text("".join(f"file '{a}'\nduration {d:.4f}\n" for a, d in linhas) + f"file '{linhas[-1][0]}'\n", encoding="utf-8")
    entradas = []
    for i, fim in trechos:
        entradas += ["-ss", f"{i:.3f}", "-t", f"{fim - i:.3f}", "-i", str(video)]
    entradas += ["-f", "concat", "-safe", "0", "-i", str(lista),
                 "-loop", "1", "-t", str(DF + 0.2), "-framerate", str(FPS), "-i", str(tmp / "fech.png")]
    f.append(f"[{n}:v]fps={FPS},format=rgba,setpts=PTS-STARTPTS[ov]")
    f.append("[vc][ov]overlay=0:0:eof_action=pass:shortest=0[f0]")
    atual = "f0"
    f.append(f"[{atual}]format=yuv420p,settb=1/{FPS}[fala]")
    f.append(f"[{n + 1}:v]fps={FPS},format=yuv420p,settb=1/{FPS}[fe]")
    f.append(f"[fala][fe]xfade=transition=fade:duration=0.35:offset={S - 0.35:.3f}[v]")
    norm = (f"loudnorm=I=-14:TP=-1.5:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}"
            f":measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true,aresample=48000")
    f.append(f"[ac]{norm},afade=t=out:st={S - 0.4:.3f}:d=0.4,apad=whole_dur={D}[a]")
    grafo = ";".join(f)
    mp4 = saida / f"{job['id']}_9x16.mp4"
    kbps = job.get("kbps", 2100)
    base = ["ffmpeg", "-v", "error", "-y", *entradas, "-filter_complex", grafo, "-map", "[v]", "-map", "[a]", "-t", f"{D:.3f}",
            "-c:v", "libx264", "-preset", "slow", "-b:v", f"{kbps}k", "-maxrate", f"{int(kbps * 1.4)}k", "-bufsize", f"{kbps * 3}k",
            "-pix_fmt", "yuv420p", "-r", str(FPS)]
    log("1ª passada de vídeo")
    run(base + ["-pass", "1", "-passlogfile", str(tmp / "x264"), "-an", "-f", "null", "-"])
    log("2ª passada de vídeo")
    run(base + ["-pass", "2", "-passlogfile", str(tmp / "x264"), "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(mp4)])
    # capa: abertura sobre o primeiro quadro
    run(["ffmpeg", "-v", "error", "-y", "-ss", "0.4", "-i", str(mp4), "-frames:v", "1", "-q:v", "2", str(saida / f"{job['id']}_capa.jpg")])
    shutil.rmtree(tmp)
    tam = mp4.stat().st_size / 1e6
    log(f"pronto: {mp4.name} ({D:.1f}s, {tam:.1f} MB)")


if __name__ == "__main__":
    main()
