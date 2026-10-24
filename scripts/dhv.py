#!/usr/bin/env python3
"""digital-human-video: Agent Skill CLI. Python 3.10+.

API references are in references/api.md. No credentials are embedded.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import textwrap
import time
from typing import Any
from urllib.parse import urlparse

import requests

ROOT = Path(__file__).resolve().parent.parent


def load_dotenv() -> None:
    # Prefer cwd settings, then skill root. Do not overwrite shell environment.
    for f in [ROOT / '.env', Path.cwd() / '.env']:
        if f.exists():
            for line in f.read_text(encoding='utf-8').splitlines():
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                k, v = line.split('=', 1)
                if k.strip() and k.strip() not in os.environ:
                    os.environ[k.strip()] = v.strip().strip('"').strip("'")


def config(key: str, default: str = '') -> str:
    return os.environ.get(key, default).strip()


def required(key: str) -> str:
    value = config(key)
    if not value:
        raise RuntimeError(f'缺少 {key}，请在 .env 或环境变量中填写（不要把 API Key 发到对话中）')
    return value


def need_file(p: str) -> Path:
    path = Path(p).expanduser().resolve()
    if not path.is_file():
        raise RuntimeError(f'文件不存在：{path}')
    return path


def as_json(r: requests.Response, service: str) -> dict:
    try:
        payload = r.json()
    except ValueError:
        raise RuntimeError(f'{service} HTTP {r.status_code}: 返回非 JSON 响应')
    if not r.ok:
        detail = payload.get('error') or payload.get('base_resp') or payload
        raise RuntimeError(f'{service} HTTP {r.status_code}: {str(detail)[:600]}')
    if service == 'MiniMax' and payload.get('base_resp', {}).get('status_code', 0) != 0:
        raise RuntimeError(f"MiniMax API 错误：{payload['base_resp']}")
    if service == 'HeyGen' and payload.get('error'):
        raise RuntimeError(f"HeyGen API 错误：{payload['error']}")
    return payload


def json_write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)


def run_cmd(argv: list[str], cwd: Path | None = None) -> str:
    p = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if p.returncode:
        raise RuntimeError(f"命令失败（{p.returncode}）：{' '.join(argv[:5])}\n{p.stderr[-1300:]}")
    return p.stdout


def ffprobe_duration(path: Path) -> float:
    return float(run_cmd(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', str(path)]).strip())


def validate_url(url: str) -> str:
    # Signed HeyGen URL. Do not forward API keys or arbitrary file:// URLs.
    parsed = urlparse(url)
    if parsed.scheme != 'https' or not parsed.netloc:
        raise RuntimeError('视频/字幕下载链接必须为 HTTPS')
    return url


def stream_download(url: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(validate_url(url), stream=True, timeout=(20, 180)) as r:
        r.raise_for_status()
        with target.open('wb') as fout:
            total = 0
            for chunk in r.iter_content(1024 * 256):
                if chunk:
                    total += len(chunk)
                    if total > 1_500_000_000:
                        raise RuntimeError('下载视频超出最大安全大小 1.5GB')
                    fout.write(chunk)


def minimax_headers() -> dict:
    return {'Authorization': f'Bearer {required("MINIMAX_API_KEY")}'}


def minimax_base() -> str:
    return config('MINIMAX_BASE_URL', 'https://api.minimax.cn').rstrip('/')


def heygen_headers() -> dict:
    return {'x-api-key': required('HEYGEN_API_KEY')}


def heygen_base() -> str:
    return 'https://api.heygen.com'


def upload_minimax_clone(path: Path) -> int:
    if path.suffix.lower() not in {'.mp3', '.wav', '.m4a'}:
        raise RuntimeError('声音样本仅支持 mp3/m4a/wav')
    if path.stat().st_size > 20 * 1024 * 1024:
        raise RuntimeError('声音样本不能超过 20MB')
    duration = ffprobe_duration(path)
    if not 10 <= duration <= 300:
        raise RuntimeError(f'声音样本须 10秒~5分钟，当前为 {duration:.1f} 秒')
    with path.open('rb') as f:
        r = requests.post(f'{minimax_base()}/v1/files/upload', headers=minimax_headers(),
                          files={'file': (path.name, f)}, data={'purpose': 'voice_clone'}, timeout=(20, 120))
    return int(as_json(r, 'MiniMax')['file']['file_id'])


def clone_voice(path: Path, voice_id: str) -> None:
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{6,254}[A-Za-z0-9]', voice_id):
        raise RuntimeError('voice_id 长度 8~256，英文字母开头、字母/数字结尾，中间可用字母数字-_')
    file_id = upload_minimax_clone(path)
    payload = {'file_id': file_id, 'voice_id': voice_id, 'model': config('MINIMAX_SPEECH_MODEL', 'speech-2.8-turbo'),
               'need_noise_reduction': False, 'need_volume_normalization': False}
    r = requests.post(f'{minimax_base()}/v1/voice_clone', headers=minimax_headers(), json=payload, timeout=(20, 180))
    as_json(r, 'MiniMax')
    print(f'声音复刻请求成功。Voice ID: {voice_id}\n请放入 .env: MINIMAX_VOICE_ID={voice_id}')


def upload_heygen_asset(path: Path) -> str:
    if path.stat().st_size > 50 * 1024 * 1024:
        raise RuntimeError('HeyGen v3 简单上传上限 50MB；大文件需使用分片上传/官方网页')
    with path.open('rb') as f:
        r = requests.post(f'{heygen_base()}/v3/assets', headers=heygen_headers(),
                          files={'file': (path.name, f)}, timeout=(20, 180))
    response = as_json(r, 'HeyGen')
    return response['data']['asset_id']


def create_avatar(path: Path, kind: str, name: str) -> None:
    if kind == 'photo' and path.suffix.lower() not in {'.jpg', '.jpeg', '.png'}:
        raise RuntimeError('Photo Avatar 需要 jpg/jpeg/png')
    if kind == 'digital_twin' and path.suffix.lower() not in {'.mp4', '.webm'}:
        raise RuntimeError('Digital Twin 需要 mp4/webm')
    asset_id = upload_heygen_asset(path)
    r = requests.post(f'{heygen_base()}/v3/avatars', headers=heygen_headers(),
                      json={'type': kind, 'name': name, 'file': {'type': 'asset_id', 'asset_id': asset_id}}, timeout=(20, 120))
    response = as_json(r, 'HeyGen')
    print('已提交数字人建立请求（异步，需要核查授权/验证及训练状态）：')
    print(json.dumps(response.get('data', response), ensure_ascii=False, indent=2))
    print('训练完成后执行 `avatars` 获取 Look ID，填入 HEYGEN_AVATAR_ID。')


def list_avatars() -> None:
    r = requests.get(f'{heygen_base()}/v3/avatars/looks', headers=heygen_headers(), timeout=(15, 60))
    data = as_json(r, 'HeyGen')
    for a in data.get('data', []):
        print(f"{a.get('id')}  {a.get('name')}  {a.get('avatar_type')}  {a.get('status')}")
    if data.get('has_more'):
        print('还有更多 Avatar，请在 HeyGen 控制台按名称查找或增加分页支持。')


def synthesize(text: str, output: Path, voice_id: str) -> None:
    req = {'model': config('MINIMAX_SPEECH_MODEL', 'speech-2.8-turbo'), 'text': text, 'stream': False,
           'voice_setting': {'voice_id': voice_id, 'speed': 1, 'vol': 1, 'pitch': 0},
           'audio_setting': {'sample_rate': 32000, 'bitrate': 128000, 'format': 'mp3', 'channel': 1}}
    r = requests.post(f'{minimax_base()}/v1/t2a_v2', headers=minimax_headers(), json=req, timeout=(20, 180))
    resp = as_json(r, 'MiniMax')
    hex_audio = (resp.get('data') or {}).get('audio')
    if not hex_audio:
        raise RuntimeError('MiniMax TTS 未返回 data.audio，请核对 speech model、配额和 API 版本')
    output.write_bytes(bytes.fromhex(hex_audio))
    if output.stat().st_size < 1000:
        raise RuntimeError('MiniMax TTS 返回异常短音频')


def generate_script(topic: str, seconds: int, audience: str, tone: str) -> str:
    # OpenAI-compatible chat completions. Defaults to MiniMax OpenAI-compatible endpoint,
    # if LLM_API_KEY is configured. Also works with DeepSeek, Qwen etc.
    api_key = config('LLM_API_KEY') or config('MINIMAX_API_KEY')
    if not api_key:
        raise RuntimeError('自动写稿需要 LLM_API_KEY 或 MINIMAX_API_KEY；否则请使用 --script-file')
    url = config('LLM_API_URL', 'https://api.minimax.cn/v1/chat/completions')
    model = config('LLM_MODEL', 'MiniMax-M3')
    prompt = (f'为中文短视频生成一篇可以直接口播的稿子。主题：{topic}；目标受众：{audience}；风格：{tone}；'
              f'目标时长{seconds}秒（中文约每分钟200~240字）。\n'
              '结构：前3秒明确钩子→2~3个具体、有逻辑的观点→一句总结/自然行动号召。'
              '句子简短，口语自然，事实性断言不确定时使用审慎表述；禁止捏造数据、来源和亲身经历。'
              '只输出可以朗读的正文，不能包含标题、Markdown、括号舞台指示、镜头注释或标签。')
    r = requests.post(url, headers={'Authorization': f'Bearer {api_key}'},
                      json={'model': model, 'messages': [{'role': 'user', 'content': prompt}],
                            'temperature': 0.5, 'stream': False}, timeout=(20, 180))
    body = as_json(r, 'LLM')
    msg = body['choices'][0]['message']['content']
    if isinstance(msg, list):
        msg = ''.join((chunk.get('text', '') if isinstance(chunk, dict) else str(chunk)) for chunk in msg)
    msg = str(msg).strip().strip('"“”')
    if not msg:
        raise RuntimeError('LLM 返回空文案')
    return msg


def preview_script(full: str, chars: int = 55) -> str:
    full = ' '.join(full.split())
    if len(full) <= chars:
        return full
    # Break at a sentence boundary near 15s (nominal 3.5~4.0 CN chars/second).
    segments = re.split(r'(?<=[。！？!?；;])', full)
    picked = ''
    for seg in segments:
        if len(picked) + len(seg) > chars and picked:
            break
        picked += seg
    return picked.strip() or full[:chars]


def wait_for_heygen(video_id: str, max_wait: int) -> dict:
    deadline = time.monotonic() + max_wait
    delay = 10
    while time.monotonic() < deadline:
        r = requests.get(f'{heygen_base()}/v3/videos/{video_id}', headers=heygen_headers(), timeout=(15, 60))
        details = as_json(r, 'HeyGen')['data']
        status = details.get('status', '')
        print(f'  HeyGen job {video_id}: {status}', flush=True)
        if status in {'completed', 'success'} and details.get('video_url'):
            return details
        if status in {'failed', 'error', 'cancelled', 'canceled'}:
            raise RuntimeError(f"HeyGen 视频失败：{details.get('failure_code')} {details.get('failure_message')}")
        time.sleep(delay)
        delay = min(delay + 5, 25)
    raise TimeoutError(f'HeyGen 尚未生成完成（job={video_id}）；再次运行同一命令会继续查询，避免重复扣费')


def heygen_create_video(audio: Path, avatar_id: str, title: str, aspect: str, key: str) -> str:
    aid = upload_heygen_asset(audio)
    payload = {'type': 'avatar', 'avatar_id': avatar_id, 'title': title[:100],
               'aspect_ratio': aspect, 'output_format': 'mp4', 'audio_asset_id': aid,
               'caption': {'file_format': 'srt', 'style': 'default'}}
    headers = {**heygen_headers(), 'Idempotency-Key': key}
    r = requests.post(f'{heygen_base()}/v3/videos', headers=headers, json=payload, timeout=(20, 120))
    return as_json(r, 'HeyGen')['data']['video_id']


def split_sentences(script: str) -> list[str]:
    chunks = [s.strip() for s in re.split(r'(?<=[。！？!?；;，,])', ' '.join(script.split())) if s.strip()]
    lines: list[str] = []
    for c in chunks:
        if len(c) < 22:
            lines.append(c)
        else:
            lines += [c[i:i+18] for i in range(0, len(c), 18)]
    return lines or [script]


def srt_time(sec: float) -> str:
    milliseconds = max(0, int(round(sec * 1000)))
    h, remainder = divmod(milliseconds, 3600000)
    m, remainder = divmod(remainder, 60000)
    s, ms = divmod(remainder, 1000)
    return f'{h:02d}:{m:02d}:{s:02d},{ms:03d}'


def approx_srt(script: str, seconds: float, target: Path) -> None:
    segments = split_sentences(script)
    lengths = [max(len(x.strip(' ，。！？')), 3) for x in segments]
    total = sum(lengths)
    pos = 0.0
    blocks = []
    for i, (segment, length) in enumerate(zip(segments, lengths), start=1):
        nxt = seconds if i == len(segments) else min(seconds, pos + seconds * length / total)
        blocks.append(f'{i}\n{srt_time(pos)} --> {srt_time(nxt)}\n{segment}\n')
        pos = nxt
    target.write_text('\n'.join(blocks), encoding='utf-8-sig')


def choose_font() -> str:
    # Fonts are NOT packaged. Local installed font needed to display Chinese.
    explicit = config('VIDEO_FONT_PATH')
    if explicit and Path(explicit).exists():
        return explicit
    paths = ['/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
             '/usr/share/fonts/truetype/wqy/wqy-microhei.ttc',
             '/System/Library/Fonts/PingFang.ttc',
             'C:/Windows/Fonts/msyh.ttc', 'C:/Windows/Fonts/simhei.ttf']
    return next((p for p in paths if Path(p).exists()), '')


def draw_title(path: Path, headline: str, brand: str, font_path: str) -> None:
    from PIL import Image, ImageDraw, ImageFont
    canvas = Image.new('RGBA', (1080, 1920), (0, 0, 0, 0))
    d = ImageDraw.Draw(canvas)
    d.rounded_rectangle([54, 90, 1026, 250], radius=28, fill=(5, 12, 24, 200))
    d.rounded_rectangle([54, 90, 66, 250], radius=5, fill=(57, 207, 224, 255))
    regular = lambda size: ImageFont.truetype(font_path, size) if font_path else ImageFont.load_default(size=size)
    # User-provided title is clipped to avoid overlay overflowing.
    heading = headline[:22]
    if len(heading) > 16:
        heading = heading[:15] + '…'
    d.text((98, 110), heading, font=regular(66), fill=(255, 255, 255, 255))
    d.text((98, 194), brand[:45] or 'DIGITAL STUDIO', font=regular(26), fill=(124, 227, 226, 255))
    d.rounded_rectangle([820, 1780, 1024, 1854], radius=18, fill=(0, 0, 0, 150))
    d.text((842, 1795), 'AI生成内容', font=regular(29), fill=(240, 240, 240, 255))
    canvas.save(path)


def highlight_image(path: Path, phrase: str, font_path: str) -> None:
    from PIL import Image, ImageDraw, ImageFont
    canvas = Image.new('RGBA', (1080, 1920), (0, 0, 0, 0))
    d = ImageDraw.Draw(canvas)
    d.rounded_rectangle([65, 1315, 1015, 1455], radius=32, fill=(1, 17, 30, 225))
    d.rounded_rectangle([65, 1315, 82, 1455], radius=5, fill=(255, 188, 50, 255))
    font = ImageFont.truetype(font_path, 53) if font_path else ImageFont.load_default(size=53)
    d.text((106, 1350), phrase[:15] + ('…' if len(phrase) > 15 else ''), font=font,
           fill=(255, 248, 223, 255))
    canvas.save(path)


def render(raw: Path, script: str, title: str, brand: str, output: Path,
           bgm: Path | None = None, broll: Path | None = None, srt: Path | None = None,
           edit_plan: dict | None = None) -> dict:
    # All video filters are local and deterministic; opacity, subtitle and montage do not require LLM.
    output.parent.mkdir(parents=True, exist_ok=True)
    work = output.parent
    duration = ffprobe_duration(raw)
    edit_plan = edit_plan or {}
    subtitle = work / f'{output.stem}.srt'
    subtitle_type = 'approximate'
    if srt and srt.exists() and srt.stat().st_size > 10:
        shutil.copyfile(srt, subtitle)
        subtitle_type = 'heygen'
    else:
        approx_srt(script, duration, subtitle)
    try:
        font = choose_font()
        overlay_img = work / f'{output.stem}_overlay.png'
        draw_title(overlay_img, title, brand, font)
    except Exception as e:
        raise RuntimeError(f'生成标题图失败（Pillow/字体）：{e}')
    ffmpeg = ['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error', '-i', str(raw), '-loop', '1', '-i', str(overlay_img)]
    if broll:
        if broll.suffix.lower() in {'.png', '.jpg', '.jpeg'}:
            ffmpeg += ['-loop', '1', '-i', str(broll)]
        else:
            ffmpeg += ['-stream_loop', '-1', '-i', str(broll)]
    points = edit_plan.get('key_points', [])
    if not isinstance(points, list):
        raise RuntimeError('edit_plan.key_points 必须是数组')
    if len(points) > 5:
        raise RuntimeError('一个视频最多支持 5 个重点卡片')
    cards = []
    for ix, item in enumerate(points):
        if not isinstance(item, dict):
            raise RuntimeError('key_points 每条必须含 text/start/end')
        start, end = float(item['start']), float(item['end'])
        if start < 0 or end <= start:
            raise RuntimeError('key_points 开始/结束时间非法')
        card = work / f'{output.stem}_point_{ix}.png'
        highlight_image(card, str(item['text']), font)
        ffmpeg += ['-loop', '1', '-i', str(card)]
        cards.append((start, end))
    if bgm:
        ffmpeg += ['-stream_loop', '-1', '-i', str(bgm)]
    vf = [
        '[0:v]split=2[bg][fg]',
        '[bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=20:5[blur]',
        '[fg]scale=1080:1920:force_original_aspect_ratio=decrease,setsar=1[small]',
        '[blur][small]overlay=(W-w)/2:(H-h)/2[v0]',
        '[v0][1:v]overlay=0:0:shortest=1[v1]'
    ]
    current = '[v1]'
    next_input = 2
    if broll:
        start = float(edit_plan.get('pip_start', 4))
        end = float(edit_plan.get('pip_end', 12))
        if start < 0 or end <= start:
            raise RuntimeError('edit_plan 中画中画时间不合法')
        vf += [f'[{next_input}:v]scale=370:350:force_original_aspect_ratio=decrease,pad=370:350:(ow-iw)/2:(oh-ih)/2[pip]',
               f'{current}[pip]overlay=650:465:enable=\'between(t,{start},{end})\'[v2]']
        current = '[v2]'
        next_input += 1
    for ix, (start, end) in enumerate(cards):
        vf.append(f"{current}[{next_input}:v]overlay=0:0:shortest=1:enable='between(t,{start},{end})'[key{ix}]")
        current = f'[key{ix}]'
        next_input += 1
    # Relative SRT filename in cwd avoids FFmpeg path quoting issues on Win/Mac.
    fontsize = max(16, min(40, int(edit_plan.get('subtitle_font_size', 22))))
    style = f"FontName=Noto Sans CJK SC,FontSize={fontsize},PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=1,Alignment=2,MarginV=240"
    vf += [f'{current}subtitles={subtitle.name}:force_style=\'{style}\'[vout]']
    audio_map = '0:a:0'
    if bgm:
        volume = max(0, min(float(edit_plan.get('music_volume', 0.10)), 0.30))
        vf += [f'[0:a]volume=1.0[voice]', f'[{next_input}:a]volume={volume:.3f}[bgmusic]',
               '[voice][bgmusic]amix=inputs=2:duration=first:dropout_transition=2[aout]']
        audio_map = '[aout]'
    ffmpeg += ['-filter_complex', ';'.join(vf), '-map', '[vout]', '-map', audio_map,
               '-t', f'{duration:.3f}', '-c:v', 'libx264', '-preset', config('VIDEO_PRESET', 'veryfast'),
               '-crf', config('VIDEO_CRF', '23'), '-pix_fmt', 'yuv420p', '-r', '25',
               '-c:a', 'aac', '-b:a', '160k', '-movflags', '+faststart', str(output)]
    run_cmd(ffmpeg, cwd=work)
    return {'subtitle_source': subtitle_type, 'duration': ffprobe_duration(output), 'output': str(output)}


def produce_text_assets(out: Path, script: str, topic: str) -> None:
    (out / 'script.txt').write_text(script, encoding='utf-8')
    publish = (f'# 发布素材\n\n主题：{topic}\n\n'
               f'## 标题（待人工事实核对）\n{topic[:28]}｜一分钟说清楚\n\n'
               f'## 简介\n{script[:135]}…\n\n'
               '## 发布前确认\n- 内容事实、肖像/声音授权、素材和音乐版权\n'
               '- 按平台规则标识 AI 生成内容\n- 各平台登录和实际发布需额外的 OAuth/官方接口授权，本 Skill 不会擅自发布\n')
    (out / 'publish.md').write_text(publish, encoding='utf-8')


def do_run(args) -> None:
    out = Path(args.out).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    state_file = out / 'state.json'
    state = json.loads(state_file.read_text(encoding='utf-8')) if state_file.exists() else {}
    topic = args.topic or state.get('topic', '')
    if not topic and not args.script_file:
        raise RuntimeError('请提供 --topic 或 --script-file')
    if state.get('topic') and topic and state['topic'] != topic:
        raise RuntimeError('该 --out 目录已有不同主题的任务，请换一个输出目录，防止状态串稿。')
    if args.mode == 'full' and not (args.approve or args.auto_approve or (out/'preview.approved').exists()):
        raise RuntimeError('完整成片之前请审看预览，然后传 --approve；也可用 --auto-approve 一次自动生成两段（会产生两次 HeyGen 用量）')
    if args.dry_run:
        print(json.dumps({'topic': topic, 'mode': args.mode, 'out': str(out),
                          'has_script_file': bool(args.script_file), 'avatar_id_set': bool(args.avatar_id or config('HEYGEN_AVATAR_ID')),
                          'voice_id_set': bool(args.voice_id or config('MINIMAX_VOICE_ID')),
                          'steps': ['LLM 文案', 'MiniMax TTS', 'HeyGen 音频上传及头像渲染', 'FFmpeg 合成+字幕+可选画中画/BGM'],
                          'note': 'dry-run 不调用付费 API'}, ensure_ascii=False, indent=2))
        return
    for cmd in ['ffmpeg', 'ffprobe']:
        if not shutil.which(cmd):
            raise RuntimeError(f'缺少 {cmd}。macOS: brew install ffmpeg；Windows: winget install Gyan.FFmpeg')
    avatar_id = args.avatar_id or required('HEYGEN_AVATAR_ID')
    voice_id = args.voice_id or required('MINIMAX_VOICE_ID')
    if args.script_file:
        manuscript = need_file(args.script_file).read_text(encoding='utf-8').strip()
        if state.get('script') and state['script'] != manuscript:
            raise RuntimeError('现有状态已存在不同的文案，请使用新 --out 目录')
    elif state.get('script'):
        manuscript = state['script']
    else:
        manuscript = generate_script(topic, args.seconds, args.audience, args.tone)
    if not manuscript:
        raise RuntimeError('文案不能为空')
    state.update({'topic': topic, 'script': manuscript})
    json_write(state_file, state)
    produce_text_assets(out, manuscript, topic)
    edit_plan = {}
    if args.edit_plan:
        edit_plan = json.loads(need_file(args.edit_plan).read_text(encoding='utf-8'))
        if not isinstance(edit_plan, dict):
            raise RuntimeError('--edit-plan 必须是 JSON 对象')
    bgm = need_file(args.music) if args.music else None
    broll = need_file(args.broll) if args.broll else None
    modes = ['preview', 'full'] if args.auto_approve and args.mode == 'full' else [args.mode]
    for mode in modes:
        stage = state.setdefault(mode, {})
        portion = preview_script(manuscript) if mode == 'preview' else manuscript
        run_hash = hashlib.sha256(f'{mode}|{portion}|{avatar_id}|{voice_id}|{args.aspect}'.encode()).hexdigest()[:32]
        if stage.get('hash') and stage['hash'] != run_hash:
            raise RuntimeError(f'{mode} 阶段参数已变化；请使用新的输出目录避免错误复用已付费视频')
        stage['hash'] = run_hash
        json_write(state_file, state)
        audio = out / f'{mode}_voice.mp3'
        raw = out / f'{mode}_raw.mp4'
        final = out / f'{mode}_final.mp4'
        if not audio.exists():
            print(f'[{mode}] MiniMax 合成声音…', flush=True)
            synthesize(portion, audio, voice_id)
        if not raw.exists():
            if not stage.get('video_id'):
                print(f'[{mode}] HeyGen 提交数字人视频…', flush=True)
                job = heygen_create_video(audio, avatar_id, topic, args.aspect, run_hash)
                stage['video_id'] = job
                json_write(state_file, state)
            info = wait_for_heygen(stage['video_id'], args.max_wait)
            stream_download(info['video_url'], raw)
            if info.get('subtitle_url'):
                try:
                    stream_download(info['subtitle_url'], out / f'{mode}_heygen.srt')
                except requests.RequestException:
                    pass
        if not final.exists():
            print(f'[{mode}] FFmpeg 包装剪辑…', flush=True)
            subtitle_file = out / f'{mode}_heygen.srt'
            # Avoid stale subtitles not compatible with narration on audio-asset input: use if valid only.
            result = render(raw, portion, args.headline or edit_plan.get('headline') or topic,
                            edit_plan.get('brand') or args.brand, final, bgm, broll,
                            subtitle_file if subtitle_file.exists() else None, edit_plan)
            stage['render'] = result
            json_write(state_file, state)
        print(f'[{mode}] 成品：{final}', flush=True)
    if args.approve and args.mode == 'full':
        (out / 'preview.approved').write_text('approved via CLI by operator\n', encoding='utf-8')
    print(f'发布文案：{out / "publish.md"}；生产状态：{state_file}')


def doctor() -> None:
    print('Digital Human Video Skill · 环境检测')
    for prog in ['ffmpeg', 'ffprobe']:
        print(f'{prog}: {shutil.which(prog) or "缺少"}')
    for key in ['MINIMAX_API_KEY', 'HEYGEN_API_KEY', 'MINIMAX_VOICE_ID', 'HEYGEN_AVATAR_ID']:
        print(f'{key}: {"已设置" if config(key) else "未设置"}')
    print('LLM: ' + ('已配置（默认 MiniMax 或指定 LLM）' if config('LLM_API_KEY') or config('MINIMAX_API_KEY') else '使用 --script-file 可跳过'))
    print('中文字体: ' + (choose_font() or '未找到，请设置 VIDEO_FONT_PATH'))
    print('注意：doctor 不调用 API，不验证配额/账户可用性。')


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description='AI 数字人口播视频 Skill（MiniMax + HeyGen v3 + FFmpeg）')
    subs = p.add_subparsers(dest='command', required=True)
    subs.add_parser('doctor', help='检测本机环境（不发生费用）')
    av = subs.add_parser('avatar', help='首次创建数字人（肖像授权后使用）')
    av.add_argument('--file', required=True)
    av.add_argument('--kind', required=True, choices=['photo', 'digital_twin'])
    av.add_argument('--name', required=True)
    av.add_argument('--i-own-the-likeness', action='store_true', help='本人肖像或有明确合法授权')
    subs.add_parser('avatars', help='查看自己的数字人 Look ID')
    c = subs.add_parser('clone', help='首次声音复刻（需要认证）')
    c.add_argument('--file', required=True)
    c.add_argument('--voice-id', required=True)
    c.add_argument('--i-own-the-voice', action='store_true', help='本人声音或有明确合法授权')
    r = subs.add_parser('run', help='按主题自动写稿、语音合成、数字人、字幕剪辑')
    r.add_argument('--topic', default='')
    r.add_argument('--script-file', default='')
    r.add_argument('--seconds', type=int, default=60)
    r.add_argument('--audience', default='普通观众')
    r.add_argument('--tone', default='自然、专业、略带幽默')
    r.add_argument('--out', required=True)
    r.add_argument('--mode', choices=['preview', 'full'], default='preview')
    r.add_argument('--approve', action='store_true', help='已审看预览，继续完整生成')
    r.add_argument('--auto-approve', action='store_true', help='自动跑预览再跑完整成片（不人工审看）')
    r.add_argument('--dry-run', action='store_true', help='仅展示任务计划，不调用任何API')
    r.add_argument('--avatar-id', default='')
    r.add_argument('--voice-id', default='')
    r.add_argument('--aspect', choices=['9:16', '16:9', '1:1'], default='9:16')
    r.add_argument('--brand', default='MAX STORM STUDIO')
    r.add_argument('--headline', default='')
    r.add_argument('--music', default='')
    r.add_argument('--broll', default='')
    r.add_argument('--edit-plan', default='', help='Opus/Codex 可编辑的剪辑方案 JSON')
    r.add_argument('--max-wait', type=int, default=1800)
    return p


def main() -> int:
    load_dotenv()
    args = parser().parse_args()
    try:
        if args.command == 'doctor':
            doctor()
        elif args.command == 'clone':
            if not args.i_own_the_voice:
                raise RuntimeError('声音克隆需明确授权，请确认后传 --i-own-the-voice')
            clone_voice(need_file(args.file), args.voice_id)
        elif args.command == 'avatar':
            if not args.i_own_the_likeness:
                raise RuntimeError('创建数字人需肖像授权，请确认后传 --i-own-the-likeness')
            create_avatar(need_file(args.file), args.kind, args.name)
        elif args.command == 'avatars':
            list_avatars()
        elif args.command == 'run':
            do_run(args)
    except (RuntimeError, KeyError, ValueError, TimeoutError, requests.RequestException) as exc:
        print(f'错误：{exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
