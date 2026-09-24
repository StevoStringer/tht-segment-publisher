import os, re, json, uuid, shutil, subprocess, zipfile
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel

BASE = Path(__file__).parent
DATA = BASE / "data"
SHOWS = DATA / "shows"
EXPORTS = DATA / "exports"
for p in (SHOWS, EXPORTS): p.mkdir(parents=True, exist_ok=True)

STREAM_URL = os.getenv("STREAM_URL", "")
CONFIG = DATA / "config.json"
TZ = os.getenv("TZ", "Africa/Johannesburg")
scheduler = BackgroundScheduler(timezone=TZ)
scheduler.start()

def load_config():
    if CONFIG.exists():
        try: return json.loads(CONFIG.read_text())
        except: pass
    return {"enabled":False,"days":"mon,tue,wed,thu,fri","hour":18,"minute":0,"duration":7200,"stream_url":STREAM_URL}

def save_config(c):
    CONFIG.write_text(json.dumps(c,indent=2))

def scheduled_capture():
    c=load_config()
    if not c.get("enabled"): return
    capture_show(int(c.get("duration",7200)), c.get("stream_url",""))

def reschedule():
    try: scheduler.remove_job("tht_capture")
    except: pass
    c=load_config()
    if c.get("enabled"):
        scheduler.add_job(scheduled_capture, CronTrigger(day_of_week=c["days"],hour=int(c["hour"]),minute=int(c["minute"]),timezone=TZ),
                          id="tht_capture",replace_existing=True,misfire_grace_time=1800)
reschedule()
RECORD_SECONDS = int(os.getenv("RECORD_SECONDS", "7200"))
app = FastAPI(title="THT Segment Publisher")

def ffmpeg():
    exe = shutil.which("ffmpeg")
    if not exe:
        raise HTTPException(500, "FFmpeg is not installed or not on PATH.")
    return exe

def show_dir(show_id): return SHOWS / show_id
def state_path(show_id): return show_dir(show_id) / "state.json"

def load_state(show_id):
    p = state_path(show_id)
    if not p.exists(): raise HTTPException(404, "Show not found")
    return json.loads(p.read_text())

def save_state(s):
    d = show_dir(s["id"]); d.mkdir(parents=True, exist_ok=True)
    state_path(s["id"]).write_text(json.dumps(s, indent=2))

def duration(path):
    probe = shutil.which("ffprobe")
    if not probe: return 0
    r = subprocess.run([probe,"-v","error","-show_entries","format=duration","-of","default=nw=1:nk=1",str(path)],capture_output=True,text=True)
    try: return round(float(r.stdout.strip()),2)
    except: return 0

def transcribe(path):
    key = os.getenv("OPENAI_API_KEY")
    if not key: return []
    from openai import OpenAI
    client = OpenAI(api_key=key)
    with open(path, "rb") as f:
        tr = client.audio.transcriptions.create(model="whisper-1", file=f, response_format="verbose_json", timestamp_granularities=["segment"])
    out=[]
    for x in getattr(tr, "segments", []) or []:
        if isinstance(x, dict): out.append({"start":x["start"],"end":x["end"],"text":x["text"].strip()})
        else: out.append({"start":x.start,"end":x.end,"text":x.text.strip()})
    return out

def propose_segments(transcript, total):
    if not transcript:
        return [{"id":str(uuid.uuid4())[:8],"start":0,"end":total or 600,"title":"Segment 1","guest":"","description":"","status":"review"}]
    # Heuristic cues common to talk radio. Boundaries remain human-reviewable.
    intro = re.compile(r"\b(join(?:ing|s) us|welcome|on the line|in studio|speaking to|our guest)\b", re.I)
    outro = re.compile(r"\b(thank you (?:so much )?for joining|thanks for joining|thank you for your time|we'll leave it there)\b", re.I)
    starts=[i for i,x in enumerate(transcript) if intro.search(x["text"])]
    segs=[]
    for n, idx in enumerate(starts):
        st=max(0, transcript[idx]["start"]-2)
        next_st = transcript[starts[n+1]]["start"] if n+1 < len(starts) else total
        end=next_st
        for x in transcript[idx:]:
            if x["start"] > next_st: break
            if outro.search(x["text"]):
                end=min(total, x["end"]+3); break
        if end-st >= 60:
            context=" ".join(x["text"] for x in transcript[idx:min(idx+8,len(transcript))])
            segs.append({"id":str(uuid.uuid4())[:8],"start":round(st,1),"end":round(end,1),
                         "title":f"Interview {len(segs)+1}","guest":"","description":context[:280],
                         "status":"review"})
    if not segs:
        segs=[{"id":str(uuid.uuid4())[:8],"start":0,"end":total,"title":"Full programme","guest":"","description":"","status":"review"}]
    return segs

@app.get("/", response_class=HTMLResponse)
def home():
    return (BASE/"static"/"index.html").read_text()

@app.get("/api/shows")
def shows():
    out=[]
    for p in SHOWS.glob("*/state.json"):
        try: out.append(json.loads(p.read_text()))
        except: pass
    return sorted(out,key=lambda x:x.get("created",""),reverse=True)

@app.post("/api/upload")
async def upload(file: UploadFile=File(...)):
    sid=datetime.now().strftime("%Y%m%d")+"-"+str(uuid.uuid4())[:6]
    d=show_dir(sid); d.mkdir(parents=True)
    ext=Path(file.filename or "show.mp3").suffix or ".mp3"
    src=d/f"source{ext}"
    with src.open("wb") as f: shutil.copyfileobj(file.file,f)
    total=duration(src)
    transcript=transcribe(src)
    s={"id":sid,"created":datetime.now().isoformat(timespec="seconds"),"source":src.name,"duration":total,
       "transcript":transcript,"segments":propose_segments(transcript,total)}
    save_state(s); return s

class RecordReq(BaseModel):
    seconds:int=RECORD_SECONDS

def capture_show(seconds, stream_url=None):
    seconds=max(30,min(int(seconds),14400))
    url=stream_url or load_config().get("stream_url") or STREAM_URL
    if not url: raise HTTPException(400,"Set the direct playable stream URL in Settings first.")
    sid=datetime.now(ZoneInfo(TZ)).strftime("%Y%m%d")+"-"+str(uuid.uuid4())[:6]
    d=show_dir(sid); d.mkdir(parents=True)
    src=d/"source.aac"
    cmd=[ffmpeg(),"-y","-hide_banner","-loglevel","error","-reconnect","1","-reconnect_streamed","1","-reconnect_delay_max","10",
         "-i",url,"-t",str(seconds),"-c","copy",str(src)]
    try: subprocess.run(cmd,check=True,timeout=seconds+120)
    except Exception as e: raise HTTPException(500,f"Recording failed: {e}")
    total=duration(src); transcript=transcribe(src)
    s={"id":sid,"created":datetime.now(ZoneInfo(TZ)).isoformat(timespec="seconds"),"source":src.name,"duration":total,
       "transcript":transcript,"segments":propose_segments(transcript,total)}
    save_state(s); return s

@app.post("/api/record")
def record(req:RecordReq):
    return capture_show(req.seconds)

@app.get("/api/shows/{sid}")
def get_show(sid:str): return load_state(sid)

@app.post("/api/shows/{sid}/segments/{segid}")
def update_segment(sid:str, segid:str, payload:dict):
    s=load_state(sid)
    seg=next((x for x in s["segments"] if x["id"]==segid),None)
    if not seg: raise HTTPException(404,"Segment not found")
    for k in ("start","end","title","guest","description","status"):
        if k in payload: seg[k]=payload[k]
    seg["start"]=max(0,float(seg["start"])); seg["end"]=min(float(s["duration"]),float(seg["end"]))
    if seg["end"]<=seg["start"]: raise HTTPException(400,"OUT must be after IN")
    save_state(s); return seg

@app.post("/api/shows/{sid}/segments/{segid}/export")
def export_segment(sid:str,segid:str):
    s=load_state(sid); seg=next((x for x in s["segments"] if x["id"]==segid),None)
    if not seg: raise HTTPException(404,"Segment not found")
    src=show_dir(sid)/s["source"]; outdir=EXPORTS/f"{sid}-{segid}"; outdir.mkdir(parents=True,exist_ok=True)
    safe=re.sub(r"[^A-Za-z0-9 _-]+","",seg["title"]).strip() or f"THT-{segid}"
    mp3=outdir/(safe+".mp3")
    length=float(seg["end"])-float(seg["start"])
    cmd=[ffmpeg(),"-y","-hide_banner","-loglevel","error","-ss",str(seg["start"]),"-i",str(src),"-t",str(length),
         "-af","loudnorm=I=-16:TP=-1.5:LRA=11,afade=t=in:st=0:d=0.15,afade=t=out:st="+str(max(0,length-.2))+":d=0.2",
         "-codec:a","libmp3lame","-b:a","160k",str(mp3)]
    subprocess.run(cmd,check=True)
    meta={"title":seg["title"],"guest":seg.get("guest",""),"description":seg.get("description",""),
          "broadcast_id":sid,"in":seg["start"],"out":seg["end"],"iono_channel":"7560"}
    (outdir/"metadata.json").write_text(json.dumps(meta,indent=2))
    (outdir/"README.txt").write_text("Manual iono.fm publish package\nChannel: https://iono.fm/c/7560\n\nTITLE:\n"+seg["title"]+
        "\n\nDESCRIPTION:\n"+seg.get("description","")+"\n")
    zpath=EXPORTS/f"{sid}-{segid}.zip"
    with zipfile.ZipFile(zpath,"w",zipfile.ZIP_DEFLATED) as z:
        for p in outdir.iterdir(): z.write(p,p.name)
    seg["status"]="exported"; save_state(s)
    return {"download":f"/api/download/{zpath.name}"}

@app.get("/api/audio/{sid}")
def audio(sid:str):
    s=load_state(sid); return FileResponse(show_dir(sid)/s["source"])

@app.get("/api/download/{name}")
def download(name:str):
    p=EXPORTS/name
    if not p.exists() or p.suffix!=".zip": raise HTTPException(404)
    return FileResponse(p,filename=p.name)

@app.get("/health")
def health(): return {"ok":True}

@app.get("/api/settings")
def settings(): return load_config()

@app.post("/api/settings")
def settings_save(payload:dict):
    c=load_config()
    for k in ("enabled","days","hour","minute","duration","stream_url"):
        if k in payload: c[k]=payload[k]
    c["hour"]=max(0,min(23,int(c["hour"])))
    c["minute"]=max(0,min(59,int(c["minute"])))
    c["duration"]=max(60,min(14400,int(c["duration"])))
    if not re.fullmatch(r"(mon|tue|wed|thu|fri|sat|sun)(,(mon|tue|wed|thu|fri|sat|sun))*",str(c["days"])):
        raise HTTPException(400,"Days must look like mon,tue,wed")
    save_config(c); reschedule(); return c

@app.delete("/api/shows/{sid}")
def delete_show(sid:str):
    d=show_dir(sid)
    if not d.exists(): raise HTTPException(404)
    shutil.rmtree(d); return {"ok":True}

@app.get("/publish/{sid}/{segid}", response_class=HTMLResponse)
def publish_handoff(sid:str, segid:str):
    s=load_state(sid)
    seg=next((x for x in s["segments"] if x["id"]==segid),None)
    if not seg: raise HTTPException(404,"Segment not found")
    title=str(seg.get("title","")).replace("&","&amp;").replace("<","&lt;").replace('"',"&quot;")
    desc=str(seg.get("description","")).replace("&","&amp;").replace("<","&lt;")
    return f"""<!doctype html><meta name=viewport content="width=device-width,initial-scale=1">
    <style>body{{font-family:system-ui;max-width:720px;margin:30px auto;padding:0 18px}}textarea,input{{width:100%;box-sizing:border-box;padding:10px;margin:5px 0 14px}}a{{display:inline-block;padding:12px 15px;background:#222;color:#fff;border-radius:9px;text-decoration:none}}p{{color:#555}}</style>
    <h1>Ready for iono.fm</h1><p>This handoff uses your existing authorised iono publisher session. The app does not store your iono password.</p>
    <label>Title</label><input value="{title}" readonly>
    <label>Description</label><textarea rows=7 readonly>{desc}</textarea>
    <p>Download the publication ZIP from the main dashboard, extract the MP3, then open THT's publisher page below and choose <b>Publish Episode</b>.</p>
    <a href="https://iono.fm/c/7560" target="_blank" rel="noopener">Open The Honest Truth on iono.fm</a>"""
