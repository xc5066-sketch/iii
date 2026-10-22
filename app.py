from flask import Flask, request, send_file, jsonify, Response
from pathlib import Path
import tempfile, zipfile, threading, uuid, re, shutil, time, os, hashlib
import yt_dlp

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024
JOBS = {}
LOCK = threading.Lock()
MAX_ACTIVE_JOBS = 2
JOB_TTL_SECONDS = 45 * 60
MAX_SELECTED = 100

HTML = r'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="theme-color" content="#10131b"><title>Instagram 媒体选择下载</title>
<style>
:root{color-scheme:dark;--bg:#10131b;--panel:#191e29;--line:#30394a;--text:#f2f4f8;--muted:#a7b0bf;--accent:#d5defd;--bad:#ffb8c0;--good:#a8e8ce}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 system-ui,-apple-system,sans-serif}header{padding:22px 16px 12px;max-width:1100px;margin:auto}h1{font-size:25px;margin:0 0 6px}header p{color:var(--muted);font-size:13px;margin:0}main{max-width:1100px;margin:auto;padding:0 12px 36px}
.toolbar{position:sticky;top:0;z-index:3;background:#10131bf2;backdrop-filter:blur(12px);padding:12px 4px;border-bottom:1px solid var(--line)}form{display:flex;gap:8px}input[type=text]{min-width:0;flex:1;padding:13px;border:1px solid var(--line);border-radius:10px;background:#0b0e14;color:var(--text);font:inherit}
button,.btn{border:0;border-radius:10px;padding:12px 14px;background:var(--accent);color:#141927;font:700 14px system-ui;cursor:pointer;text-decoration:none;display:inline-flex;align-items:center;justify-content:center;min-height:44px}button:disabled{opacity:.45;cursor:wait}.tools{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:10px}.tools button{padding:9px 12px;min-height:38px}.count{font-size:13px;color:var(--muted);margin-right:auto}
.notice{margin:12px 2px;padding:12px;border:1px solid var(--line);border-radius:10px;color:var(--muted);font-size:12px;white-space:pre-wrap}.status{padding:12px;margin:12px 2px;border-radius:10px;background:#1b2230;white-space:pre-wrap;overflow-wrap:anywhere}.error{color:var(--bad);border:1px solid #70424b}.success{color:var(--good);border:1px solid #356252}
.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:7px;margin-top:14px}.item{position:relative;min-width:0;aspect-ratio:1;background:#202635;border:1px solid #333d50;border-radius:8px;overflow:hidden}.item img{width:100%;height:100%;object-fit:cover;display:block}.item .fallback{height:100%;display:grid;place-items:center;padding:8px;color:var(--muted);font-size:12px;text-align:center;overflow-wrap:anywhere}.item input{position:absolute;top:7px;left:7px;z-index:1;width:25px;height:25px;accent-color:#d5defd}.tag{position:absolute;bottom:5px;right:5px;background:#080b11d9;border-radius:5px;padding:2px 6px;font-size:10px}.item .open{position:absolute;bottom:5px;left:5px;background:#080b11d9;color:white;border-radius:5px;padding:2px 6px;font-size:10px;text-decoration:none}.pager{display:flex;gap:8px;margin-top:16px}.pager button{flex:1}.empty{padding:35px 10px;text-align:center;color:var(--muted)}
@media(min-width:700px){.grid{grid-template-columns:repeat(5,minmax(0,1fr));gap:10px}header{padding-top:30px}.item{border-radius:10px}}@media(max-width:360px){.grid{grid-template-columns:repeat(2,minmax(0,1fr))}form{flex-direction:column}form button{width:100%}}
</style></head><body><header><h1>Instagram 媒体选择下载</h1><p>公开主页 · 分页预览 · 勾选所需内容 · ZIP 打包</p></header><main>
<section class="toolbar"><form id="profileForm"><input id="profile" type="text" autocomplete="url" placeholder="公开主页链接或用户名" required><button id="loadBtn">读取主页</button></form><div class="tools"><span class="count" id="selectionCount">已选 0 项</span><button id="selectPage" type="button" disabled>选择本页</button><button id="clearSelection" type="button" disabled>清空选择</button><button id="downloadBtn" type="button" disabled>下载所选 ZIP</button></div></section>
<div id="status" class="status" role="status" aria-live="polite">输入公开主页后点击“读取主页”。</div><div id="grid" class="grid"></div><div class="pager"><button id="prevBtn" type="button" disabled>上一页</button><button id="nextBtn" type="button" disabled>下一页</button></div>
<div class="notice">只尝试读取公开可访问媒体；不收集 Instagram 密码或 Cookie，不添加水印，也不去除原文件水印。Instagram 可能要求登录、限制请求或改变页面结构，无法保证所有主页都能读取。轮播帖是否返回全部媒体取决于提取器支持情况。请只保存你有权下载的内容。</div></main>
<script>
const $=id=>document.getElementById(id);let jobId=null,items=[],page=0,pageSize=24,selected=new Set(),pollTimer=null;
function say(t,kind=''){ $('status').textContent=t;$('status').className='status '+kind}
function updateSelection(){ $('selectionCount').textContent=`已选 ${selected.size} 项`; $('downloadBtn').disabled=!selected.size; $('clearSelection').disabled=!selected.size; $('selectPage').disabled=!items.length}
function currentItems(){return items.slice(page*pageSize,(page+1)*pageSize)}
function render(){const grid=$('grid');grid.innerHTML='';const part=currentItems();if(!part.length)grid.innerHTML='<div class="empty">当前页没有媒体条目。</div>';
for(const item of part){const card=document.createElement('div');card.className='item';const cb=document.createElement('input');cb.type='checkbox';cb.checked=selected.has(item.id);cb.setAttribute('aria-label','选择媒体');cb.addEventListener('change',()=>{if(cb.checked)selected.add(item.id);else selected.delete(item.id);updateSelection()});card.appendChild(cb);
if(item.thumbnail){const img=document.createElement('img');img.loading='lazy';img.src=item.thumbnail;img.alt='媒体预览';img.referrerPolicy='no-referrer';img.onerror=()=>{img.remove();const f=document.createElement('div');f.className='fallback';f.textContent='预览不可用';card.appendChild(f)};card.appendChild(img)}else{const f=document.createElement('div');f.className='fallback';f.textContent='无可用缩略图';card.appendChild(f)}
const tag=document.createElement('span');tag.className='tag';tag.textContent=item.kind==='video'?'视频':(item.kind==='carousel'?'轮播/帖子':'图片/帖子');card.appendChild(tag);if(item.webpage_url){const a=document.createElement('a');a.className='open';a.href=item.webpage_url;a.target='_blank';a.rel='noopener';a.textContent='原帖';card.appendChild(a)}grid.appendChild(card)}
$('prevBtn').disabled=page===0;$('nextBtn').disabled=(page+1)*pageSize>=items.length;updateSelection()}
async function api(url,options){const r=await fetch(url,options);let j;try{j=await r.json()}catch{throw Error('服务器返回了无法识别的内容')}if(!r.ok)throw Error(j.error||j.message||'请求失败');return j}
$('profileForm').addEventListener('submit',async e=>{e.preventDefault();clearTimeout(pollTimer);$('loadBtn').disabled=true;items=[];selected.clear();page=0;render();say('正在读取主页媒体列表。主页较大时可能需要等待。');
try{const j=await api('/api/media',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({profile:$('profile').value})});jobId=j.job_id;
const poll=async()=>{const s=await api('/api/status/'+jobId);if(s.status==='running'){say(s.message||'正在读取…');pollTimer=setTimeout(()=>poll().catch(err=>say(err.message,'error')),1800)}else if(s.status==='done'){items=s.items||[];selected.clear();page=0;render();say(`读取完成：共发现 ${items.length} 个媒体条目。每页 ${pageSize} 项。`,items.length?'success':'error');if(!items.length)say(s.message||'没有读取到媒体。Instagram 可能限制了访问。','error');$('loadBtn').disabled=false}else{say(s.message||'读取失败','error');$('loadBtn').disabled=false}};await poll()}catch(err){say(err.message,'error');$('loadBtn').disabled=false}});
$('prevBtn').addEventListener('click',()=>{if(page>0){page--;render();window.scrollTo({top:0,behavior:'smooth'})}});$('nextBtn').addEventListener('click',()=>{if((page+1)*pageSize<items.length){page++;render();window.scrollTo({top:0,behavior:'smooth'})}});
$('selectPage').addEventListener('click',()=>{for(const item of currentItems())selected.add(item.id);render()});$('clearSelection').addEventListener('click',()=>{selected.clear();render()});
$('downloadBtn').addEventListener('click',async()=>{if(!jobId||!selected.size)return;const btn=$('downloadBtn');btn.disabled=true;btn.textContent='正在打包…';say(`正在下载并打包所选 ${selected.size} 项，请勿关闭页面。`);
try{const j=await api('/api/zip',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({job_id:jobId,ids:[...selected]})});const poll=async()=>{const s=await api('/api/status/'+j.job_id);if(s.status==='running'){say(s.message||'正在下载所选媒体…');pollTimer=setTimeout(()=>poll().catch(err=>say(err.message,'error')),1800)}else if(s.status==='done'){say(s.message||'ZIP 已准备好','success');const a=document.createElement('a');a.className='btn';a.style.margin='12px 2px';a.style.width='100%';a.href=s.download_url;a.textContent='下载 ZIP 压缩包';$('status').appendChild(document.createElement('br'));$('status').appendChild(a);btn.disabled=false;btn.textContent='下载所选 ZIP'}else{say(s.message||'打包失败','error');btn.disabled=false;btn.textContent='下载所选 ZIP'}};await poll()}catch(err){say(err.message,'error');btn.disabled=false;btn.textContent='下载所选 ZIP'}});
</script></body></html>'''


def normalize_profile(value):
    value = (value or "").strip()
    if value.startswith("@"): value = value[1:]
    if "instagram.com" in value.lower():
        m = re.search(r"(?:https?://)?(?:www\.)?instagram\.com/([A-Za-z0-9._]+)/?", value, re.I)
        if not m: raise ValueError("主页链接格式不正确。请使用 https://www.instagram.com/用户名/ 格式。")
        value = m.group(1)
    if not re.fullmatch(r"[A-Za-z0-9._]{1,30}", value): raise ValueError("用户名格式不正确。")
    if value.lower() in {"p","reel","reels","stories","explore","accounts","direct"}:
        raise ValueError("请输入博主主页链接，而不是帖子或功能页面链接。")
    return value


def cleanup_old_jobs():
    now = time.time()
    with LOCK:
        old = [(jid,j) for jid,j in JOBS.items() if now-j.get("created",now)>JOB_TTL_SECONDS and j.get("status")!="running"]
        for jid,_ in old: JOBS.pop(jid,None)
    for jid,_ in old: shutil.rmtree(Path(tempfile.gettempdir())/"ig_gallery"/jid,ignore_errors=True)


def new_job(kind, message):
    with LOCK:
        active=sum(1 for j in JOBS.values() if j.get("status")=="running")
        if active>=MAX_ACTIVE_JOBS: raise RuntimeError("当前已有任务正在运行，请等任务结束后再试。")
        job_id=uuid.uuid4().hex
        JOBS[job_id]={"status":"running","message":message,"created":time.time(),"kind":kind}
    return job_id


def base_opts():
    return {"quiet":True,"no_warnings":True,"ignoreerrors":True,"socket_timeout":18,"retries":1,"extractor_retries":1,"noplaylist":False}


def classify(entry):
    text=" ".join(str(entry.get(k,"")) for k in ("_type","media_type","format","title","url")).lower()
    if entry.get("duration") or "video" in text or "reel" in text: return "video"
    if entry.get("entries") or "carousel" in text: return "carousel"
    return "image"


def run_list(job_id, username):
    try:
        url=f"https://www.instagram.com/{username}/"
        opts=base_opts();opts.update({"skip_download":True,"extract_flat":"in_playlist"})
        with yt_dlp.YoutubeDL(opts) as ydl: info=ydl.extract_info(url,download=False)
        entries=[]
        if isinstance(info,dict):
            raw=info.get("entries")
            entries=[x for x in raw if isinstance(x,dict)] if raw else [info]
        normalized=[];seen=set()
        for idx,e in enumerate(entries):
            post_url=e.get("webpage_url") or e.get("original_url")
            if not post_url and e.get("id"): post_url=f"https://www.instagram.com/p/{e['id']}/"
            if not post_url: continue
            ident=str(e.get("id") or post_url or idx)
            if ident in seen: continue
            seen.add(ident)
            thumb=e.get("thumbnail")
            if not thumb and e.get("thumbnails"):
                ts=e.get("thumbnails") or []
                if ts: thumb=ts[-1].get("url")
            normalized.append({"id":hashlib.sha1((ident+"|"+post_url).encode()).hexdigest()[:18],"source_id":ident,"title":str(e.get("title") or f"media_{idx+1}")[:180],"thumbnail":thumb,"webpage_url":post_url,"kind":classify(e)})
        with LOCK: JOBS[job_id].update(status="done",message=f"读取完成，发现 {len(normalized)} 个条目。",items=normalized,username=username)
    except Exception as e:
        with LOCK: JOBS[job_id].update(status="error",message=("读取失败："+str(e))[:700])
    finally:
        with LOCK: JOBS[job_id]["finished"]=time.time()


def run_zip(job_id, source_job_id, chosen_ids):
    job_dir=Path(tempfile.gettempdir())/"ig_gallery"/job_id
    job_dir.mkdir(parents=True,exist_ok=True)
    try:
        with LOCK:
            source=JOBS.get(source_job_id)
            source_items=list(source.get("items",[])) if source and source.get("status")=="done" else []
        chosen=[x for x in source_items if x["id"] in chosen_ids]
        if not chosen: raise RuntimeError("没有找到所选条目，请重新读取主页后选择。")
        if len(chosen)>MAX_SELECTED: raise RuntimeError(f"一次最多下载 {MAX_SELECTED} 项，请减少选择数量。")
        failures=0
        for i,item in enumerate(chosen,1):
            with LOCK: JOBS[job_id]["message"]=f"正在处理第 {i}/{len(chosen)} 项：{item.get('title') or item['source_id']}"
            before={p.resolve() for p in job_dir.rglob("*") if p.is_file()}
            opts=base_opts();opts.update({"outtmpl":str(job_dir/f"{i:03d}_%(id)s_%(title).50s.%(ext)s"),"format":"best","skip_download":False,"extract_flat":False,"windowsfilenames":True,"overwrites":False})
            try:
                with yt_dlp.YoutubeDL(opts) as ydl: ydl.download([item["webpage_url"]])
            except Exception: failures+=1
            after=[p for p in job_dir.rglob("*") if p.is_file() and p.suffix.lower() not in {".part",".ytdl"}]
            if len(after)<=len(before): failures+=1
        files=[p for p in job_dir.rglob("*") if p.is_file() and p.suffix.lower() not in {".part",".ytdl"} and p.name!="selected_media.zip"]
        if not files: raise RuntimeError("没有成功获取所选媒体。Instagram 可能要求登录或限制访问；请尝试选择较少条目，或确认原帖仍公开可访问。")
        zip_path=job_dir/"selected_media.zip"
        with zipfile.ZipFile(zip_path,"w",zipfile.ZIP_STORED,allowZip64=True) as zf:
            for p in files: zf.write(p,arcname=p.relative_to(job_dir).as_posix())
        msg=f"打包完成：成功获取 {len(files)} 个文件。"
        if failures: msg+=f" 部分条目未能下载（失败计数 {failures}），请检查 ZIP 内容。"
        with LOCK: JOBS[job_id].update(status="done",message=msg,zip=str(zip_path),count=len(files))
    except Exception as e:
        with LOCK: JOBS[job_id].update(status="error",message=("打包失败："+str(e))[:700])
    finally:
        with LOCK: JOBS[job_id]["finished"]=time.time()


@app.get("/")
def index(): return Response(HTML,mimetype="text/html")

@app.get("/health")
def health(): return jsonify(ok=True)

@app.post("/api/media")
def start_media_list():
    cleanup_old_jobs();data=request.get_json(silent=True) or {}
    try: username=normalize_profile(data.get("profile"));job_id=new_job("list","正在读取公开主页媒体列表…")
    except ValueError as e: return jsonify(error=str(e)),400
    except RuntimeError as e: return jsonify(error=str(e)),429
    threading.Thread(target=run_list,args=(job_id,username),daemon=True).start()
    return jsonify(job_id=job_id)

@app.post("/api/zip")
def start_zip():
    cleanup_old_jobs();data=request.get_json(silent=True) or {};source_job_id=str(data.get("job_id") or "");ids=data.get("ids")
    if not isinstance(ids,list) or not ids: return jsonify(error="请先选择至少一项媒体。"),400
    ids=[str(x) for x in ids if isinstance(x,(str,int))]
    if len(ids)>MAX_SELECTED: return jsonify(error=f"一次最多选择 {MAX_SELECTED} 项。"),400
    with LOCK:
        source=JOBS.get(source_job_id);valid=source and source.get("status")=="done" and source.get("kind")=="list"
    if not valid: return jsonify(error="主页列表已过期，请重新读取。"),404
    try: job_id=new_job("zip","正在准备 ZIP…")
    except RuntimeError as e: return jsonify(error=str(e)),429
    threading.Thread(target=run_zip,args=(job_id,source_job_id,set(ids)),daemon=True).start()
    return jsonify(job_id=job_id)

@app.get("/api/status/<job_id>")
def status(job_id):
    with LOCK:
        job=JOBS.get(job_id)
        if not job: return jsonify(error="任务不存在；免费服务休眠或重启后，任务状态可能丢失。"),404
        result={k:v for k,v in job.items() if k not in ("zip","created","finished")}
        if job.get("status")=="done" and job.get("kind")=="zip": result["download_url"]=f"/api/file/{job_id}"
        return jsonify(result)

@app.get("/api/file/<job_id>")
def download_zip(job_id):
    with LOCK:
        job=JOBS.get(job_id);path=job.get("zip") if job and job.get("status")=="done" else None
    if not path or not Path(path).is_file(): return "压缩包已过期或不存在，请重新运行任务。",404
    return send_file(path,as_attachment=True,download_name=Path(path).name,mimetype="application/zip")

if __name__=="__main__": app.run(host="0.0.0.0",port=int(os.environ.get("PORT","10000")))
