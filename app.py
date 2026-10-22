from flask import Flask, request, send_file, jsonify, Response
from pathlib import Path
import tempfile, zipfile, threading, uuid, re, shutil, time, os
import yt_dlp

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 1024 * 1024
JOBS = {}
LOCK = threading.Lock()
MAX_ACTIVE_JOBS = 1
JOB_TTL_SECONDS = 45 * 60

HTML = r'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="theme-color" content="#0b1020"><title>Instagram 媒体批量下载</title>
<style>
:root{color-scheme:dark;--bg:#0b1020;--panel:#131a2b;--line:#29344b;--text:#eef2ff;--muted:#a4afc6;--accent:#c4ceff}*{box-sizing:border-box}body{margin:0;min-height:100svh;background:radial-gradient(ellipse at top,#1c2440 0,#0b1020 58%);font:16px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif;color:var(--text);padding:24px 16px;display:flex;align-items:center;justify-content:center}main{width:min(100%,620px)}.brand{font-size:12px;letter-spacing:.18em;color:var(--accent);font-weight:750}.panel{margin-top:14px;padding:clamp(22px,5vw,36px);background:rgba(19,26,43,.96);border:1px solid var(--line);border-radius:22px;box-shadow:0 24px 80px #0005}h1{font-size:clamp(27px,7vw,38px);line-height:1.2;margin:8px 0 12px;letter-spacing:-.04em}p{color:var(--muted);margin:0 0 22px}.label{display:block;font-size:14px;font-weight:650;margin:20px 0 8px}input{width:100%;padding:15px;border:1px solid #35415a;border-radius:12px;background:#0d1424;color:var(--text);font:inherit;min-height:50px}.hint{font-size:12px;color:var(--muted);margin-top:8px}button,.download{display:flex;align-items:center;justify-content:center;width:100%;border:0;border-radius:12px;background:var(--accent);color:#10162a;font:750 15px system-ui;padding:15px 18px;margin-top:22px;cursor:pointer;text-decoration:none;min-height:50px}button:disabled{opacity:.6;cursor:wait}.note{margin-top:20px;padding:14px;border:1px solid var(--line);border-radius:12px;font-size:12px;color:var(--muted)}.status{margin-top:16px;padding:14px;border-radius:12px;background:#0d1424;font-size:14px;display:none;overflow-wrap:anywhere;white-space:pre-wrap}.error{border:1px solid #814c59;color:#ffc2cb}.success{border:1px solid #426c60;color:#b6f1d8}footer{text-align:center;font-size:11px;color:#78849c;margin-top:16px}.small{font-size:12px;color:var(--muted)}
</style></head><body><main><div class="brand">PUBLIC MEDIA TOOL</div><section class="panel"><h1>Instagram 媒体批量下载</h1><p>输入公开博主主页，尝试收集可访问的图片、视频及轮播媒体，并打包为 ZIP。</p><form id="form"><label class="label" for="profile">公开主页链接或用户名</label><input id="profile" name="profile" placeholder="https://www.instagram.com/username/" autocomplete="url" required><div class="hint">仅支持公开可访问的主页。不要输入密码或上传 Cookie。</div><button id="submit" type="submit">开始批量下载</button></form><div id="status" class="status" role="status" aria-live="polite"></div><div class="note">下载的是服务端能够获取的媒体文件，不会由本工具添加水印，也不会自动去除原文件已有的水印。Instagram 的访问限制可能导致部分内容无法获取；不保证完整下载全部历史帖子。请遵守版权及平台规则。任务文件会在约 45 分钟后清理。</div></section><footer>手机浏览器可用 · 不需要安装 App · 不收集 Instagram 密码</footer></main>
<script>
const form=document.getElementById('form'),btn=document.getElementById('submit'),box=document.getElementById('status');let pollTimer;
function show(t,k=''){box.style.display='block';box.className='status '+k;box.textContent=t}
form.addEventListener('submit',async e=>{e.preventDefault();clearTimeout(pollTimer);btn.disabled=true;btn.textContent='正在创建任务…';show('正在启动。下载时间取决于主页大小和平台访问限制。');try{let r=await fetch('/api/download',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({profile:document.getElementById('profile').value})});let j=await r.json();if(!r.ok)throw Error(j.error||'无法启动任务');const poll=async()=>{let sr=await fetch('/api/status/'+j.job_id);let s=await sr.json();if(!sr.ok)throw Error(s.error||'任务状态不可用');if(s.status==='running'){show(s.message+'\n正在检查状态…');pollTimer=setTimeout(()=>poll().catch(err=>fail(err.message)),2500)}else if(s.status==='done'){show(s.message,'success');let a=document.createElement('a');a.className='download';a.href=s.download_url;a.textContent='下载 ZIP 压缩包';box.appendChild(document.createElement('br'));box.appendChild(a);btn.disabled=false;btn.textContent='下载另一个主页'}else{fail(s.message||'下载失败')}};await poll()}catch(err){fail(err.message)}});
function fail(t){show(t,'error');btn.disabled=false;btn.textContent='重试'}
</script></body></html>'''


def normalize_profile(value):
    value = (value or '').strip()
    if value.startswith('@'): value = value[1:]
    if 'instagram.com' in value.lower():
        m = re.search(r'(?:https?://)?(?:www\.)?instagram\.com/([A-Za-z0-9._]+)/?', value, re.I)
        if not m: raise ValueError('主页链接格式不正确。请使用 https://www.instagram.com/用户名/ 格式。')
        value = m.group(1)
    if not re.fullmatch(r'[A-Za-z0-9._]{1,30}', value): raise ValueError('用户名格式不正确。')
    reserved = {'p','reel','reels','stories','explore','accounts','direct'}
    if value.lower() in reserved: raise ValueError('请输入博主主页链接，而不是帖子或功能页面链接。')
    return value


def cleanup_old_jobs():
    now = time.time()
    with LOCK:
        old = [(jid, j) for jid, j in JOBS.items() if now - j.get('created', now) > JOB_TTL_SECONDS and j.get('status') != 'running']
        for jid, _ in old: JOBS.pop(jid, None)
    for jid, _ in old:
        shutil.rmtree(Path(tempfile.gettempdir()) / 'ig_bulk' / jid, ignore_errors=True)


def run_download(job_id, username):
    job_dir = Path(tempfile.gettempdir()) / 'ig_bulk' / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    try:
        url = f'https://www.instagram.com/{username}/'
        opts = {
            'outtmpl': str(job_dir / '%(upload_date)s_%(id)s_%(title).60s.%(ext)s'),
            'format': 'best', 'noplaylist': False, 'ignoreerrors': True,
            'quiet': True, 'no_warnings': True, 'retries': 1,
            'extractor_retries': 1, 'socket_timeout': 20,
            'windowsfilenames': True,
            'match_filter': None,
        }
        with yt_dlp.YoutubeDL(opts) as ydl: ydl.download([url])
        files = [p for p in job_dir.iterdir() if p.is_file() and p.name != 'media.zip']
        if not files:
            raise RuntimeError('没有获取到媒体。Instagram 可能限制了访问，或当前版本无法遍历该主页。请稍后重试；本工具不支持私密主页。')
        zip_path = job_dir / f'{username}_media.zip'
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_STORED, allowZip64=True) as zf:
            for p in files: zf.write(p, arcname=p.name)
        with LOCK: JOBS[job_id].update(status='done', message=f'处理完成：已打包 {len(files)} 个媒体文件。', count=len(files), zip=str(zip_path))
    except Exception as e:
        with LOCK: JOBS[job_id].update(status='error', message=('下载失败：' + str(e))[:700])
    finally:
        with LOCK: JOBS[job_id]['finished'] = time.time()


@app.get('/')
def index(): return Response(HTML, mimetype='text/html')

@app.get('/health')
def health(): return jsonify(ok=True)

@app.post('/api/download')
def start_download():
    cleanup_old_jobs()
    data = request.get_json(silent=True) or {}
    try: username = normalize_profile(data.get('profile'))
    except ValueError as e: return jsonify(error=str(e)), 400
    with LOCK:
        active = sum(1 for j in JOBS.values() if j.get('status') == 'running')
        if active >= MAX_ACTIVE_JOBS: return jsonify(error='当前已有下载任务，请等任务结束后再试。免费服务一次只运行一个任务。'), 429
        job_id = uuid.uuid4().hex
        JOBS[job_id] = {'status':'running','message':'任务已开始。正在读取公开主页；大型主页可能耗时较长。','count':0,'created':time.time()}
    threading.Thread(target=run_download, args=(job_id, username), daemon=True).start()
    return jsonify(job_id=job_id)

@app.get('/api/status/<job_id>')
def status(job_id):
    with LOCK:
        job = JOBS.get(job_id)
        if not job: return jsonify(error='任务不存在；免费服务休眠或重启后，任务状态可能丢失。'), 404
        result = {k:v for k,v in job.items() if k not in ('zip','created','finished')}
        if job.get('status') == 'done': result['download_url'] = f'/api/file/{job_id}'
        return jsonify(result)

@app.get('/api/file/<job_id>')
def download_zip(job_id):
    with LOCK:
        job = JOBS.get(job_id)
        path = job.get('zip') if job and job.get('status') == 'done' else None
    if not path or not Path(path).is_file(): return '压缩包已过期或不存在，请重新运行任务。', 404
    return send_file(path, as_attachment=True, download_name=Path(path).name, mimetype='application/zip')

if __name__ == '__main__': app.run(host='0.0.0.0', port=int(os.environ.get('PORT', '10000')))
