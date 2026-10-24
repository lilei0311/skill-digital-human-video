import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest

FILE = Path(__file__).resolve().parents[1] / 'scripts' / 'dhv.py'
spec = importlib.util.spec_from_file_location('dhv', FILE)
dhv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dhv)


def test_preview_segmentation():
    source = '你知道 AI 可以每天节省一个小时吗？今天讲三个案例。第一，自动处理报告。第二，自动查资料。第三，自动追踪进度。'
    short = dhv.preview_script(source, 23)
    assert source.startswith(short)
    assert len(short) <= 23
    assert short.endswith('？')


def test_srt_order(tmp_path):
    p = tmp_path / 'sub.srt'
    dhv.approx_srt('第一条，欢迎。第二条，很棒。', 12.0, p)
    x = p.read_text(encoding='utf-8-sig')
    assert '00:00:00,000 --> ' in x
    assert '00:00:12,000' in x
    assert '第一条' in x and '第二条' in x


def test_bad_voice_id():
    with pytest.raises(RuntimeError, match='voice_id'):
        dhv.clone_voice(Path('/fake'), 'bad')


def test_api_payload(monkeypatch, tmp_path):
    class Response:
        ok = True
        status_code = 200
        def json(self):
            return {'data': {'video_id': 'v_test123'}}
    captured = {}
    monkeypatch.setenv('HEYGEN_API_KEY', 'not-a-real-key')
    def post(url, headers=None, json=None, timeout=None, files=None):
        captured.update(url=url, headers=headers, payload=json)
        return Response()
    monkeypatch.setattr(dhv, 'upload_heygen_asset', lambda p: 'as_test')
    monkeypatch.setattr(dhv.requests, 'post', post)
    assert dhv.heygen_create_video(tmp_path / 'voice.mp3', 'lk_test', 'title', '9:16', 'some_key') == 'v_test123'
    assert captured['url'].endswith('/v3/videos')
    assert captured['payload']['audio_asset_id'] == 'as_test'
    assert 'script' not in captured['payload']
    assert captured['headers']['Idempotency-Key'] == 'some_key'


def test_offline_render(tmp_path):
    if not dhv.shutil.which('ffmpeg'):
        pytest.skip('ffmpeg missing')
    raw = tmp_path / 'raw.mp4'
    subprocess.run(['ffmpeg','-y','-hide_banner','-loglevel','error',
                    '-f','lavfi','-i','color=c=blue:s=360x640:r=25:d=1.5',
                    '-f','lavfi','-i','sine=frequency=440:duration=1.5',
                    '-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(raw)], check=True)
    result = dhv.render(raw, '这是离线字幕样例。', '测试标题', 'TEST STUDIO', tmp_path / 'demo.mp4')
    assert result['subtitle_source'] == 'approximate'
    assert result['duration'] > 0.7
    assert (tmp_path / 'demo.mp4').stat().st_size > 1000


def test_highlights_and_pip(tmp_path):
    if not dhv.shutil.which('ffmpeg'):
        pytest.skip('ffmpeg missing')
    raw = tmp_path / 'raw.mp4'
    subprocess.run(['ffmpeg','-y','-hide_banner','-loglevel','error',
                    '-f','lavfi','-i','color=c=blue:s=360x640:r=25:d=1.5',
                    '-f','lavfi','-i','sine=frequency=440:duration=1.5',
                    '-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(raw)], check=True)
    plan = {'key_points': [{'text': 'AI重点', 'start': 0.1, 'end': 1.2}], 'subtitle_font_size': 24}
    result = dhv.render(raw, 'AI帮你完成任务。', '标题', 'STUDIO', tmp_path / 'highlight.mp4', edit_plan=plan)
    assert result['duration'] > 1.0
