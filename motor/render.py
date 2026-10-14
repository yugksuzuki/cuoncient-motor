#!/usr/bin/env python3
"""Motor de vídeo da Cuoncient.

Lê um job (JSON) e gera os vídeos de anúncio na identidade do cliente:
trecho com a voz original + cenas limpas + legendas exatas + logo +
fechamento animado em forma de conversa com seta para o botão da Meta.

Saídas por formato (9x16, 4x5): vídeo final, vídeo sem legenda, fechamento
separado, legendas .srt e um manifest.json com a lista de arquivos.

Uso:
  python motor/render.py jobs/exemplo-broxigenio-24h.json --out out/
  python motor/render.py --job-json '{...}' --out out/
  python motor/render.py job.json --media reel=/caminho/IMG_1306.MOV --media montagem=/caminho/IMG_1302.MOV
"""
from __future__ import annotations

import argparse
import html
import json
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FPS = 30
XFADE = 0.25
# Acabamento aplicado a todo vídeo (pode ser mudado no job em "acabamento").
ACABAMENTO = {"lufs": -14, "pico": -1.5, "contraste": 1.06, "saturacao": 1.12, "brilho": -0.01, "nitidez": 0.5}
RITMO_PADRAO = {"inicio": 350, "digitando": 700, "intervalo": 600}

FORMATOS = {
    "9x16": dict(W=1080, H=1920, cap_top=1210, logo=(72, 290, 130), faixa=dict(x=226, y=290, h=130, tf=56, sf=30),
                 fech=dict(wm=420, pad=72, head=285, logo=150, chat=560, bmax=900, bf=48, who=26, cta=1150, ctaf=80, subf=36, tap=1405, tapf=36, arr=96)),
    "4x5": dict(W=1080, H=1350, cap_top=990, logo=(56, 48, 118), faixa=dict(x=196, y=48, h=118, tf=50, sf=27),
                fech=dict(wm=200, pad=60, head=48, logo=120, chat=240, bmax=880, bf=43, who=24, cta=760, ctaf=68, subf=32, tap=1060, tapf=32, arr=88)),
}


# ---------------------------------------------------------------- utilidades
def log(msg: str) -> None:
    print(f"[motor] {msg}", flush=True)


def run(cmd: list[str]) -> None:
    log(" ".join(cmd[:6]) + (" ..." if len(cmd) > 6 else ""))
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write(r.stderr[-4000:])
        raise SystemExit(f"falhou: {cmd[0]} (código {r.returncode})")


def carregar_job(caminho: str | None, texto: str | None) -> dict:
    if texto:
        return json.loads(texto)
    with open(caminho, encoding="utf-8") as f:
        return json.load(f)


def fontes_css(familia: str) -> str:
    pasta = ROOT / "fonts" / familia
    regras = []
    for arq in sorted(pasta.glob("*-latin-*-normal.woff2")):
        peso = arq.name.split("-latin-")[1].split("-")[0]
        regras.append(
            f"@font-face{{font-family:'Marca';font-weight:{peso};font-style:normal;"
            f"src:url('{arq.as_uri()}') format('woff2');}}"
        )
    if not regras:
        raise SystemExit(f"nenhuma fonte encontrada em {pasta}")
    return "".join(regras)


# ---------------------------------------------------------------- mídias
def baixar_midias(job: dict, pasta: Path, sobrescritas: dict[str, str]) -> dict[str, Path]:
    pasta.mkdir(parents=True, exist_ok=True)
    caminhos: dict[str, Path] = {}
    for chave, fonte in job["midias"].items():
        if chave in sobrescritas:
            caminhos[chave] = Path(sobrescritas[chave]).resolve()
            continue
        ext = Path(fonte.get("nome", "x.mov")).suffix or ".mov"
        destino = pasta / f"{chave}{ext.lower()}"
        if destino.exists() and destino.stat().st_size > 0:
            caminhos[chave] = destino
            continue
        if "caminho" in fonte:
            caminhos[chave] = (ROOT / fonte["caminho"]).resolve()
            continue
        if "drive" in fonte:
            log(f"baixando {chave} do Drive ({fonte['drive']})")
            import gdown  # instalado no workflow

            gdown.download(id=fonte["drive"], output=str(destino), quiet=True)
        elif "url" in fonte:
            log(f"baixando {chave} de {fonte['url'][:60]}")
            urllib.request.urlretrieve(fonte["url"], destino)
        else:
            raise SystemExit(f"mídia '{chave}' sem 'drive', 'url' ou 'caminho'")
        if not destino.exists() or destino.stat().st_size == 0:
            raise SystemExit(f"não consegui baixar a mídia '{chave}' (o arquivo está compartilhado por link?)")
        caminhos[chave] = destino
    return caminhos


# ---------------------------------------------------------------- HTML
def html_legenda(css: str, cor: dict, W: int, H: int, top: int, texto: str, destaque: str | None) -> str:
    interno = f"<em>{texto}</em>" if destaque == "tudo" else texto
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{css}
html,body{{margin:0;background:transparent}}
.r{{width:{W}px;height:{H}px;position:relative}}
.c{{position:absolute;left:0;right:0;top:{top}px;display:flex;justify-content:center}}
.b{{background:{cor['fundo_escuro']}F2;color:{cor['texto']};font-family:'Marca',sans-serif;font-weight:800;font-size:64px;line-height:1.1;
padding:18px 34px 22px;border-radius:18px;max-width:900px;text-align:center;box-shadow:0 10px 30px rgba(0,0,0,.25)}}
em{{font-style:normal;color:{cor['destaque_texto']}}}
</style></head><body><div class="r"><div class="c"><div class="b">{interno}</div></div></div></body></html>"""


def html_faixa(css: str, cor: dict, W: int, H: int, L: dict, titulo: str, sub: str) -> str:
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{css}
html,body{{margin:0;background:transparent}}
.r{{width:{W}px;height:{H}px;position:relative}}
.f{{position:absolute;left:{L['x']}px;top:{L['y']}px;height:{L['h']}px;box-sizing:border-box;display:flex;flex-direction:column;justify-content:center;
background:{cor['destaque']};color:{cor['texto_sobre_destaque']};font-family:'Marca',sans-serif;padding:0 30px;border-radius:14px;
box-shadow:0 10px 30px rgba(0,0,0,.30)}}
.t{{font-weight:900;font-size:{L['tf']}px;line-height:1;text-transform:uppercase;letter-spacing:-.01em;white-space:nowrap}}
.s{{font-weight:700;font-size:{L['sf']}px;line-height:1.15;margin-top:6px;text-transform:uppercase;letter-spacing:.03em;white-space:nowrap}}
</style></head><body><div class="r"><div class="f"><div class="t">{titulo}</div><div class="s">{html.escape(sub)}</div></div></div></body></html>"""


def html_logo(W: int, H: int, logo_uri: str, x: int, y: int, w: int) -> str:
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>html,body{{margin:0;background:transparent}}
.r{{width:{W}px;height:{H}px;position:relative}}img{{position:absolute;left:{x}px;top:{y}px;width:{w}px;filter:drop-shadow(0 4px 14px rgba(0,0,0,.45))}}
</style></head><body><div class="r"><img src="{logo_uri}"></div></body></html>"""


def agenda_fechamento(fech: dict) -> dict:
    """Momentos (ms) de cada elemento do fechamento."""
    r = {**RITMO_PADRAO, **fech.get("ritmo", {})}
    t = r["inicio"]
    msgs = []
    for i, m in enumerate(fech["conversa"]):
        if m["quem"] == "marca":
            msgs.append(dict(tipo="digitando", ini=t, dur=r["digitando"]))
            t += r["digitando"]
        msgs.append(dict(tipo="msg", idx=i, ini=t))
        t += r["intervalo"]
    cta = t + 100
    return dict(msgs=msgs, cta=cta, toque=cta + 350, seta=cta + 550)


def html_fechamento(css: str, cor: dict, marca: dict, fech: dict, W: int, H: int, L: dict, logo_uri: str) -> str:
    ag = agenda_fechamento(fech)
    assin = fech["assinatura"]
    primeira = html.escape(assin[0]["texto"]) if assin else ""
    resto = " ".join(f'<span class="w" id="a{i}">{html.escape(a["texto"])}</span>' for i, a in enumerate(assin[1:], 1))
    baloes = []
    for i, m in enumerate(fech["conversa"]):
        if m["quem"] == "marca":
            baloes.append(f'<div class="typing" id="ty{i}"><i></i><i></i><i></i></div>')
            baloes.append(f'<div class="b br" id="m{i}"><span class="who">{html.escape(marca["nome"])}</span>{m["texto"]}</div>')
        else:
            baloes.append(f'<div class="b me" id="m{i}">{m["texto"]}</div>')
    js = ["const E='cubic-bezier(.2,.8,.2,1)';",
          "function pop(id,t,f){const el=document.getElementById(id);if(!el)return;el.animate([{opacity:0,transform:f},{opacity:1,transform:'none'}],{duration:380,delay:t,fill:'both',easing:E});}"]
    for i, a in enumerate(assin):
        js.append(f"pop('a{i}',{int(a['em']*1000)},'translateY(10px)');")
    for ev in ag["msgs"]:
        if ev["tipo"] == "digitando":
            idx = next(e["idx"] for e in ag["msgs"] if e["tipo"] == "msg" and e["ini"] >= ev["ini"] + ev["dur"])
            js.append(f"(function(){{const t=document.getElementById('ty{idx}');t.animate([{{opacity:0}},{{opacity:1,offset:.15}},{{opacity:1,offset:.85}},{{opacity:0}}],{{duration:{ev['dur']},delay:{ev['ini']},fill:'both'}});"
                      f"t.querySelectorAll('i').forEach((d,k)=>d.animate([{{transform:'translateY(0)'}},{{transform:'translateY(-10px)'}},{{transform:'translateY(0)'}}],{{duration:500,delay:{ev['ini']}+k*120,iterations:2,fill:'both'}}));}})();")
        else:
            m = fech["conversa"][ev["idx"]]
            desloc = "translateX(-60px) scale(.96)" if m["quem"] == "marca" else "translateX(60px) scale(.96)"
            js.append(f"pop('m{ev['idx']}',{ev['ini']},'{desloc}');")
    js.append(f"pop('cta',{ag['cta']},'translateY(40px)');pop('tap',{ag['toque']},'translateY(20px)');")
    js.append(f"document.getElementById('arr').animate([{{transform:'translateY(0)'}},{{transform:'translateY(16px)'}},{{transform:'translateY(0)'}}],{{duration:700,delay:{ag['seta']},iterations:6,easing:'ease-in-out',fill:'both'}});")
    seta = L["arr"] // 2
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{css}
html,body{{margin:0;background:{cor['fundo_escuro']}}}
.r{{width:{W}px;height:{H}px;position:relative;overflow:hidden;font-family:'Marca',sans-serif;color:{cor['texto']};
background:linear-gradient(165deg,{cor['fundo_escuro']} 0%,{cor['fundo_meio']} 50%,{cor['fundo_claro']} 100%)}}
.wm{{position:absolute;right:-260px;top:{L['wm']}px;width:900px;opacity:.07}}
.head{{position:absolute;left:{L['pad']}px;right:{L['pad']}px;top:{L['head']}px;display:flex;align-items:center;gap:26px}}
.head img{{width:{L['logo']}px;flex:none}}.head .t{{display:flex;flex-direction:column;gap:6px}}
.n{{font-weight:900;font-size:46px;line-height:1}}.s{{font-weight:600;font-size:30px;line-height:1.25;color:{cor['texto_suave']}}}
.w{{display:inline-block;opacity:0}}
.chat{{position:absolute;left:{L['pad']}px;right:{L['pad']}px;top:{L['chat']}px;display:flex;flex-direction:column;gap:22px}}
.b{{max-width:{L['bmax']}px;box-sizing:border-box;text-wrap:pretty;font-size:{L['bf']}px;line-height:1.25;font-weight:600;padding:24px 32px;border-radius:30px;opacity:0;box-shadow:0 14px 34px rgba(0,0,0,.25)}}
.me{{align-self:flex-end;background:{cor['balao_cliente']};color:{cor['texto_balao']};border-bottom-right-radius:8px}}
.br{{align-self:flex-start;background:{cor['balao_marca']};color:{cor['texto_balao']};border-bottom-left-radius:8px}}
.br b{{color:{cor['rotulo_marca']};font-weight:800}}
.who{{display:block;font-size:{L['who']}px;font-weight:800;color:{cor['rotulo_marca']};margin-bottom:6px;letter-spacing:.04em;text-transform:uppercase}}
.typing{{align-self:flex-start;background:{cor['balao_marca']};border-radius:30px;border-bottom-left-radius:8px;padding:24px 28px;display:flex;gap:12px;opacity:0}}
.typing i{{width:15px;height:15px;border-radius:50%;background:#8FB9A0;display:block}}
.cta{{position:absolute;left:{L['pad']}px;right:{L['pad']}px;top:{L['cta']}px;display:flex;flex-direction:column;align-items:center;text-align:center;gap:16px;opacity:0}}
.cta h2{{margin:0;font-weight:900;font-size:{L['ctaf']}px;line-height:1.0;letter-spacing:-.01em;text-transform:uppercase}}
.cta p{{margin:0;background:{cor['destaque']};color:{cor['texto_sobre_destaque']};font-weight:800;font-size:{L['subf']}px;padding:10px 22px;text-transform:uppercase;letter-spacing:.02em}}
.tap{{position:absolute;left:0;right:0;top:{L['tap']}px;display:flex;flex-direction:column;align-items:center;gap:12px;opacity:0}}
.tap span{{font-size:{L['tapf']}px;font-weight:700}}
.arrow{{width:{L['arr']}px;height:{L['arr']}px;border-radius:50%;background:{cor['destaque']};display:flex;align-items:center;justify-content:center}}
</style></head><body><div class="r">
<img class="wm" src="{logo_uri}">
<div class="head"><img src="{logo_uri}"><div class="t"><div class="n w" id="a0">{primeira}</div><div class="s">{resto}</div></div></div>
<div class="chat">{''.join(baloes)}</div>
<div class="cta" id="cta"><h2>{fech['chamada']}</h2><p>{html.escape(fech['sub'])}</p></div>
<div class="tap" id="tap"><span>{html.escape(fech['toque'])}</span><div class="arrow" id="arr"><svg width="{seta}" height="{seta}" viewBox="0 0 24 24" fill="none" stroke="{cor['texto_sobre_destaque']}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14"/><path d="M5 12l7 7 7-7"/></svg></div></div>
</div><script>{''.join(js)}</script></body></html>"""


# ---------------------------------------------------------------- render
def renderizar_pngs(job: dict, marca: dict, trabalho: Path, duracao_fech: float) -> None:
    from playwright.sync_api import sync_playwright

    css = fontes_css(marca["fonte"])
    cor = marca["cores"]
    logo_uri = (ROOT / marca["logo"]).resolve().as_uri()
    with sync_playwright() as p:
        nav = p.chromium.launch()
        for fmt in job["formatos"]:
            F = FORMATOS[fmt]
            W, H = F["W"], F["H"]
            pasta = trabalho / fmt
            (pasta / "fech").mkdir(parents=True, exist_ok=True)
            pg = nav.new_page(viewport={"width": W, "height": H})
            for i, leg in enumerate(job["legendas"]):
                arq = pasta / f"leg_{i:02d}.html"
                arq.write_text(html_legenda(css, cor, W, H, F["cap_top"], leg["texto"], leg.get("destaque")), encoding="utf-8")
                pg.goto(arq.as_uri()); pg.wait_for_timeout(150)
                pg.screenshot(path=str(pasta / f"leg_{i:02d}.png"), omit_background=True)
            x, y, w = F["logo"]
            arq = pasta / "logo.html"
            arq.write_text(html_logo(W, H, logo_uri, x, y, w), encoding="utf-8")
            pg.goto(arq.as_uri()); pg.wait_for_timeout(150)
            pg.screenshot(path=str(pasta / "logo.png"), omit_background=True)
            if job.get("faixa"):
                arq = pasta / "faixa.html"
                arq.write_text(html_faixa(css, cor, W, H, F["faixa"], job["faixa"]["titulo"], job["faixa"].get("sub", "")), encoding="utf-8")
                pg.goto(arq.as_uri()); pg.wait_for_timeout(150)
                pg.screenshot(path=str(pasta / "faixa.png"), omit_background=True)
            arq = pasta / "fech.html"
            arq.write_text(html_fechamento(css, cor, marca, job["fechamento"], W, H, F["fech"], logo_uri), encoding="utf-8")
            pg.goto(arq.as_uri()); pg.wait_for_timeout(600)
            pg.evaluate("document.getAnimations().forEach(a=>a.pause())")
            n = int(round(duracao_fech * FPS))
            for i in range(n):
                pg.evaluate(f"document.getAnimations().forEach(a=>a.currentTime={i * 1000 / FPS})")
                pg.screenshot(path=str(pasta / "fech" / f"f_{i:04d}.jpg"), type="jpeg", quality=92)
            log(f"{fmt}: {len(job['legendas'])} legendas, logo e {n} quadros de fechamento")
            pg.close()
        nav.close()


def acabamento(job: dict) -> dict:
    a = job.get("acabamento", {})
    if a is False:
        return {}
    return {**ACABAMENTO, **a}


def medir_audio(job: dict, midias: dict[str, Path]) -> dict | None:
    """1ª passada do loudnorm: mede o trecho de áudio para a normalização exata."""
    ac = acabamento(job)
    if not ac.get("lufs"):
        return None
    aud = job["audio"]
    r = subprocess.run(["ffmpeg", "-hide_banner", "-ss", str(aud["inicio"]), "-t", str(aud["duracao"]), "-i", str(midias[aud["midia"]]),
                        "-af", f"loudnorm=I={ac['lufs']}:TP={ac['pico']}:LRA=11:print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True)
    txt = r.stderr[r.stderr.rfind("{"):r.stderr.rfind("}") + 1]
    try:
        m = json.loads(txt)
        log(f"áudio medido: {m['input_i']} LUFS -> alvo {ac['lufs']}")
        return m
    except Exception:
        log("não consegui medir o áudio; uso normalização de uma passada")
        return {}


def montar_video(job: dict, midias: dict[str, Path], trabalho: Path, fmt: str, saida: Path, com_legenda: bool,
                 medida: dict | None = None) -> None:
    F = FORMATOS[fmt]
    W, H = F["W"], F["H"]
    pasta = trabalho / fmt
    aud = job["audio"]
    D = aud["duracao"]
    cenas = job["cenas"]
    S = sum(c["duracao"] for c in cenas)
    entradas = ["-ss", str(aud["inicio"]), "-t", str(D), "-i", str(midias[aud["midia"]])]
    for c in cenas:
        entradas += ["-ss", str(c["inicio"]), "-t", str(c["duracao"]), "-i", str(midias[c["midia"]])]
    idx_fech = 1 + len(cenas)
    entradas += ["-framerate", str(FPS), "-i", str(pasta / "fech" / "f_%04d.jpg")]
    legs = job["legendas"] if com_legenda else []
    for i, _ in enumerate(legs):
        entradas += ["-loop", "1", "-t", str(D + 0.5), "-i", str(pasta / f"leg_{i:02d}.png")]
    idx_logo = idx_fech + 1 + len(legs)
    if com_legenda:
        entradas += ["-loop", "1", "-t", str(D + 0.5), "-i", str(pasta / "logo.png")]
    tem_faixa = com_legenda and (pasta / "faixa.png").exists()
    idx_faixa = idx_logo + 1
    if tem_faixa:
        entradas += ["-loop", "1", "-t", str(D + 0.5), "-i", str(pasta / "faixa.png")]
    ac = acabamento(job)
    cor_cena = ""
    if ac.get("contraste") or ac.get("saturacao"):
        cor_cena += f"eq=contrast={ac.get('contraste', 1)}:saturation={ac.get('saturacao', 1)}:brightness={ac.get('brilho', 0)},"
    if ac.get("nitidez"):
        cor_cena += f"unsharp=5:5:{ac['nitidez']}:5:5:0,"

    f = []
    for i, c in enumerate(cenas, 1):
        z0 = 1 + c.get("zoom_inicial", 0.0)
        z = c.get("zoom", 0.0)
        d = c["duracao"]
        f.append(
            f"[{i}:v]fps={FPS},scale=w='{W}*({z0}+{z}*t/{d})':h='{H}*({z0}+{z}*t/{d})':force_original_aspect_ratio=increase:eval=frame,"
            f"crop={W}:{H},setsar=1,{cor_cena}trim=duration={d},setpts=PTS-STARTPTS,format=yuv420p,settb=1/{FPS}[s{i}]"
        )
    f.append("".join(f"[s{i}]" for i in range(1, len(cenas) + 1)) + f"concat=n={len(cenas)}:v=1:a=0,fps={FPS},settb=1/{FPS}[sc]")
    ultimo = "sc"
    if com_legenda:
        f.append(f"[sc][{idx_logo}:v]overlay=0:0:enable='lt(t,{S - XFADE})'[scl]")
        ultimo = "scl"
        if tem_faixa:
            f.append(f"[scl][{idx_faixa}:v]overlay=0:0:enable='lt(t,{S - XFADE})'[scf]")
            ultimo = "scf"
    f.append(f"[{idx_fech}:v]fps={FPS},scale={W}:{H},setsar=1,format=yuv420p,setpts=PTS-STARTPTS,settb=1/{FPS}[e]")
    f.append(f"[{ultimo}][e]xfade=transition=fade:duration={XFADE}:offset={S - XFADE},format=yuv420p[b0]")
    atual = "b0"
    for i, leg in enumerate(legs):
        prox = f"o{i}"
        f.append(f"[{atual}][{idx_fech + 1 + i}:v]overlay=0:0:enable='between(t,{leg['de']},{leg['ate']})'[{prox}]")
        atual = prox
    f.append(f"[{atual}]format=yuv420p[v]")
    norm = ""
    if ac.get("lufs"):
        norm = f"loudnorm=I={ac['lufs']}:TP={ac['pico']}:LRA=11"
        if medida:
            norm += (f":measured_I={medida['input_i']}:measured_TP={medida['input_tp']}:measured_LRA={medida['input_lra']}"
                     f":measured_thresh={medida['input_thresh']}:offset={medida['target_offset']}:linear=true")
        norm += ",aresample=48000,"
    f.append(f"[0:a]atrim=duration={D},asetpts=PTS-STARTPTS,{norm}afade=t=in:st=0:d=0.12,afade=t=out:st={D - 0.35}:d=0.35[au]")
    cmd = ["ffmpeg", "-v", "error", "-y", *entradas, "-filter_complex", ";".join(f),
           "-map", "[v]", "-map", "[au]", "-t", str(D), "-c:v", "libx264", "-preset", "slow", "-crf", "19",
           "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", "-r", str(FPS), str(saida)]
    run(cmd)


def srt(job: dict) -> str:
    S = sum(c["duracao"] for c in job["cenas"])
    D = job["audio"]["duracao"]
    ini_fech = S - XFADE
    itens = [(l["de"], l["ate"], l["texto"]) for l in job["legendas"]]
    assin = job["fechamento"]["assinatura"]
    for i, a in enumerate(assin):
        de = ini_fech + a["em"]
        ate = ini_fech + assin[i + 1]["em"] - 0.05 if i + 1 < len(assin) else D - 0.05
        itens.append((de, ate, a["texto"]))

    def ts(s: float) -> str:
        ms = int(round(s * 1000))
        h, ms = divmod(ms, 3600000)
        m, ms = divmod(ms, 60000)
        s2, ms = divmod(ms, 1000)
        return f"{h:02d}:{m:02d}:{s2:02d},{ms:03d}"

    limpo = lambda t: t.replace("<em>", "").replace("</em>", "").replace("<b>", "").replace("</b>", "")
    return "\n".join(f"{n}\n{ts(a)} --> {ts(b)}\n{limpo(t)}\n" for n, (a, b, t) in enumerate(itens, 1))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("job", nargs="?")
    ap.add_argument("--job-json")
    ap.add_argument("--out", default="out")
    ap.add_argument("--media", action="append", default=[], help="chave=caminho local (pula o download)")
    a = ap.parse_args()
    job = carregar_job(a.job, a.job_json)
    marca = json.loads((ROOT / "brands" / f"{job['marca']}.json").read_text(encoding="utf-8"))
    sobrescritas = dict(m.split("=", 1) for m in a.media)
    saida = Path(a.out).resolve() / job["id"]
    trabalho = saida / "_trabalho"
    if trabalho.exists():
        shutil.rmtree(trabalho)
    trabalho.mkdir(parents=True)

    D = job["audio"]["duracao"]
    S = sum(c["duracao"] for c in job["cenas"])
    if S >= D:
        raise SystemExit("as cenas somam mais que o áudio: sobra tempo zero para o fechamento")
    dur_fech = D - (S - XFADE)
    midias = baixar_midias(job, trabalho / "midias", sobrescritas)
    renderizar_pngs(job, marca, trabalho, dur_fech)
    medida = medir_audio(job, midias)

    extras = job.get("extras", {})
    arquivos = []
    for fmt in job["formatos"]:
        nome = f"{job['id']}_{fmt}"
        final = saida / f"{nome}.mp4"
        montar_video(job, midias, trabalho, fmt, final, com_legenda=True, medida=medida)
        arquivos.append(final.name)
        if extras.get("sem_legenda"):
            limpo = saida / f"{nome}_sem-legenda.mp4"
            montar_video(job, midias, trabalho, fmt, limpo, com_legenda=False, medida=medida)
            arquivos.append(limpo.name)
        if extras.get("fechamento_separado"):
            fech = saida / f"{nome}_fechamento.mp4"
            run(["ffmpeg", "-v", "error", "-y", "-framerate", str(FPS), "-i", str(trabalho / fmt / "fech" / "f_%04d.jpg"),
                 "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", "-r", str(FPS), str(fech)])
            arquivos.append(fech.name)
    if extras.get("srt"):
        (saida / f"{job['id']}_legendas.srt").write_text(srt(job), encoding="utf-8")
        arquivos.append(f"{job['id']}_legendas.srt")
    shutil.copy(ROOT / marca["logo"], saida / f"{marca['slug']}_logo.png")
    arquivos.append(f"{marca['slug']}_logo.png")
    (saida / "manifest.json").write_text(json.dumps({"id": job["id"], "marca": marca["slug"], "arquivos": arquivos,
                                                     "duracao": D}, ensure_ascii=False, indent=2), encoding="utf-8")
    shutil.rmtree(trabalho)
    log(f"pronto: {saida} ({len(arquivos)} arquivos)")


if __name__ == "__main__":
    main()
