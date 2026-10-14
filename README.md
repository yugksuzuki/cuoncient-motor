# Motor de vídeo — Cuoncient

Gera vídeos de anúncio na identidade de cada cliente, sozinho, a partir de um **job** (um JSON com o que cortar e o que escrever).

O roteiro é o que deu certo com a BR Oxigênio em 14/10/2026:

1. **Gancho com a voz real** (trecho do vídeo do cliente) sobre cenas limpas, com leve zoom.
2. **Legendas exatas da fala**, na fonte e nas cores da marca, com destaque nas palavras-chave.
3. **Logo** no canto durante as cenas.
4. **Fechamento animado em forma de conversa** (cliente pergunta, marca responde 24h) + "Chame agora no WhatsApp" + **seta apontando para o botão real da Meta**. Não existe botão desenhado.
5. Saem **9x16** (Reels e Stories) e **4x5** (feed), cada um com e sem legenda, mais o fechamento separado, as legendas em `.srt` e o logo.

## Como roda

```
Claude (monta o job)  ──►  n8n "Vídeo — pedir render"  ──►  GitHub Actions (render.yml)
                                                                   │  ffmpeg + Playwright
                                                                   ▼
Drive do cliente  ◄──  n8n "Vídeo — receber resultado"  ◄──  release com os arquivos
```

- **Claude**: assiste/lê o material, escolhe o trecho com a voz, escreve as legendas e o fechamento, e devolve o job.
- **n8n**: recebe o job, dispara o Actions e, quando o render termina, salva os arquivos na pasta do cliente no Drive.
- **GitHub Actions**: renderiza (cerca de 3 minutos por job, contando a instalação; o teste de 14/10 levou 2min41s).
- **CapCut Pro**: opcional, só para acabamento manual em cima da versão **sem legenda** + `.srt`.

Custo extra: perto de zero. Cada job usa uns 3 minutos de máquina do GitHub, dentro da cota grátis mensal. O n8n já é pago.

## Instalar (uma vez)

1. Crie um repositório **privado** e suba esta pasta (ex.: `yugksuzuki/cuoncient-motor`).
2. No repositório, em *Settings › Secrets and variables › Actions*, crie:
   - `N8N_CALLBACK_URL`: a URL de produção do webhook `video-pronto` do fluxo 2.
   - `N8N_CALLBACK_TOKEN`: uma senha qualquer. Use a mesma no fluxo 2.
3. No n8n, importe `n8n/01-video-pedir-render.json` e `n8n/02-video-receber-resultado.json`.
   - Nos dois nós HTTP, escolha uma credencial **GitHub API** com acesso a este repositório (Actions: escrita; Contents: leitura). No n8n do Gui é a credencial **"Github"**; a "GitHub account" dá *Forbidden* aqui.
   - No nó do Drive, escolha a credencial do Google Drive.
   - Troque `TROQUE-ESTE-TOKEN` (fluxo 1) e `TROQUE-ESTE-TOKEN-DE-RETORNO` (fluxo 2).
   - Se o repositório tiver outro nome, ajuste a URL no nó "Disparar GitHub Actions".
   - Ative os dois fluxos.
4. As mídias do job precisam estar no Drive **compartilhadas por link** ("qualquer pessoa com o link pode ver"). Sem isso o download falha com aviso claro.

## Usar

Mande um POST para o webhook `video-render` com:

```json
{ "token": "TROQUE-ESTE-TOKEN", "job": { ...conteúdo de um job... } }
```

Ou rode à mão no GitHub: *Actions › Render de vídeo › Run workflow* e informe `job_path` (ex.: `jobs/exemplo-broxigenio-24h.json`).

Para testar no computador:

```
pip install -r requirements.txt && python -m playwright install chromium
python motor/render.py jobs/exemplo-broxigenio-24h.json --out out \
  --media reel=/caminho/IMG_1306.MOV --media montagem=/caminho/IMG_1302.MOV
```

## O job

Veja `jobs/exemplo-broxigenio-24h.json`. Campos:

| Campo | O que é |
|---|---|
| `id` | nome curto do vídeo, vira o nome dos arquivos |
| `marca` | arquivo em `brands/<marca>.json` (cores, fonte, logo) |
| `midias` | cada vídeo de origem: `drive` (id do arquivo), `url` ou `caminho` |
| `audio` | de qual mídia vem a voz, `inicio` e `duracao` (= duração total do vídeo) |
| `cenas` | trechos de imagem limpa em ordem: `midia`, `inicio`, `duracao`, `zoom` |
| `legendas` | `de`/`ate` em segundos do vídeo final, `texto` (use `<em>` para destaque; `destaque: "tudo"` destaca a frase toda) |
| `fechamento` | `assinatura` (frases com `em` = segundos depois do início do fechamento), `conversa` (balões `cliente`/`marca`), `chamada`, `sub`, `toque` |
| `formatos` | `9x16` e/ou `4x5` |
| `extras` | `sem_legenda`, `srt`, `fechamento_separado` |

O fechamento começa 0,25 s antes de acabarem as cenas e vai até o fim do áudio. Ele precisa de uns 4 segundos para a conversa, a chamada e a seta aparecerem.

## Nova marca

1. Crie `brands/<slug>.json` copiando `brands/broxigenio.json` e trocando as cores.
2. Ponha o logo branco com fundo transparente em `brands/<slug>/logo-branco.png`.
3. Se a fonte não for Montserrat, coloque os `.woff2` em `fonts/<fonte>/` com nomes `<fonte>-latin-<peso>-normal.woff2` e ajuste `"fonte"`.

## Regras que não mudam

- Os 340 px de baixo do 9x16 ficam livres: é onde a Meta põe o botão.
- Nada importante nos 270 px de cima do 9x16.
- Sem botão desenhado: a seta aponta para o botão real.
- Produto regulado (ex.: oxigênio medicinal): sem promessa de saúde, sem indicação de uso, sem preço no anúncio.

Fontes: Montserrat (SIL Open Font License), em `fonts/montserrat/`.
