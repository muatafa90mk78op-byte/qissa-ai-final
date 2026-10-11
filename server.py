#!/usr/bin/env python3
"""Local backend for Qissa wa Ibrah using Google's Veo video-generation API.
API key stays on the server in GEMINI_API_KEY, never in browser JavaScript.
"""
import json, os, time, uuid, threading
from pathlib import Path
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / 'static'
GENERATED = STATIC / 'generated'
GENERATED.mkdir(parents=True, exist_ok=True)
BASE = 'https://generativelanguage.googleapis.com/v1beta'
API_KEY = os.environ.get('GEMINI_API_KEY', '').strip()

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, fmt, *args):
        print('[qissa]', fmt % args)

    def _json(self, code, obj):
        data = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == '/api/health':
            return self._json(200, {'ok': True, 'configured': bool(API_KEY), 'model': 'veo-3.1-generate-preview'})
        if self.path == '/':
            self.path = '/index.html'
        return super().do_GET()

    def do_POST(self):
        if self.path != '/api/generate':
            return self._json(404, {'error': 'المسار غير موجود.'})
        if not API_KEY:
            return self._json(503, {'error': 'لم تتم إضافة مفتاح GEMINI_API_KEY إلى الخادم بعد. اتبع ملف README_AR.txt.'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if length < 1 or length > 50000:
                return self._json(400, {'error': 'حجم الطلب غير صالح.'})
            body = json.loads(self.rfile.read(length).decode('utf-8'))
            prompt = str(body.get('prompt', '')).strip()
            ratio = str(body.get('aspectRatio', '9:16'))
            if not prompt:
                return self._json(400, {'error': 'اكتب وصف الفيديو أولًا.'})
            if len(prompt) > 15000:
                return self._json(400, {'error': 'الوصف طويل جدًا؛ اختصره إلى أقل من 15000 حرف.'})
            if ratio not in ('9:16', '16:9'):
                ratio = '9:16'
            prompt += '\n\nGenerate one coherent, realistic cinematic video. Natural human movement, historically appropriate setting and clothing, no cartoon or animation style. Avoid inaccurate written text in the image. This generation is one short clip, not a complete long-form biography.'
            payload = {'instances': [{'prompt': prompt}], 'parameters': {'aspectRatio': ratio, 'durationSeconds': '8', 'resolution': '720p', 'numberOfVideos': 1}}
            operation = self._api('POST', f'{BASE}/models/veo-3.1-generate-preview:predictLongRunning', payload)
            op_name = operation.get('name')
            if not op_name:
                return self._json(502, {'error': 'لم يرجع محرك الفيديو رقم عملية. الرد: ' + json.dumps(operation, ensure_ascii=False)[:1000]})
            deadline = time.time() + 600
            while time.time() < deadline:
                time.sleep(10)
                status = self._api('GET', f'{BASE}/{op_name}')
                if status.get('done'):
                    if status.get('error'):
                        return self._json(502, {'error': 'تعذّر توليد الفيديو: ' + json.dumps(status['error'], ensure_ascii=False)[:1200]})
                    samples = status.get('response', {}).get('generateVideoResponse', {}).get('generatedSamples', [])
                    if not samples or not samples[0].get('video', {}).get('uri'):
                        return self._json(502, {'error': 'انتهت العملية لكن لم يصل رابط الفيديو.'})
                    video_uri = samples[0]['video']['uri']
                    video_data = self._download(video_uri)
                    fname = f'{uuid.uuid4().hex}.mp4'
                    (GENERATED / fname).write_bytes(video_data)
                    return self._json(200, {'ok': True, 'videoUrl': f'/static/generated/{fname}', 'message': 'اكتمل الفيديو بنجاح.'})
            return self._json(504, {'error': 'استغرق التوليد وقتًا أطول من المتوقع. جرّب مرة أخرى لاحقًا.'})
        except HTTPError as e:
            detail = e.read().decode('utf-8', 'replace')[:1800]
            return self._json(502, {'error': f'رفضت خدمة التوليد الطلب ({e.code}): {detail}'})
        except (URLError, TimeoutError) as e:
            return self._json(502, {'error': f'تعذر الاتصال بخدمة التوليد: {e}'})
        except Exception as e:
            return self._json(500, {'error': 'حدث خطأ في الخادم: ' + str(e)[:1000]})

    def _api(self, method, url, payload=None):
        data = json.dumps(payload).encode('utf-8') if payload is not None else None
        req = Request(url, data=data, method=method, headers={'x-goog-api-key': API_KEY, 'Content-Type': 'application/json'})
        with urlopen(req, timeout=90) as resp:
            return json.loads(resp.read().decode('utf-8'))

    def _download(self, uri):
        req = Request(uri, headers={'x-goog-api-key': API_KEY})
        with urlopen(req, timeout=180) as resp:
            data = resp.read()
        if not data or len(data) < 1000:
            raise RuntimeError('ملف الفيديو الذي أعادته الخدمة فارغ أو غير مكتمل.')
        return data

if __name__ == '__main__':
    print('قصة وعبرة — backend محلي')
    print('API key configured:', bool(API_KEY))
    print('Open http://127.0.0.1:8000')
    port = int(os.environ.get('PORT', '8000'))
    ThreadingHTTPServer(('0.0.0.0', port), Handler).serve_forever()
