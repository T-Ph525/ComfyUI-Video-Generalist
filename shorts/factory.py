"""Local Shorts production: Ollama + ComfyUI + Kokoro + FFmpeg."""
import argparse,json,os,random,re,subprocess,time,uuid
from datetime import datetime,timezone
from pathlib import Path
import requests
ROOT=Path(__file__).parent
for line in (ROOT/".env").read_text().splitlines() if (ROOT/".env").exists() else []:
    if "=" in line and not line.startswith("#"):
        k,v=line.split("=",1); os.environ.setdefault(k.strip(),v.strip())
C=os.getenv("COMFY_URL","http://127.0.0.1:8188").rstrip("/")
O=os.getenv("OLLAMA_URL","http://127.0.0.1:11434").rstrip("/")
OUT=Path(os.getenv("SHORTS_OUTPUT_DIR","/workspace/shorts-output"))
def request(method,url,**kw):
    r=requests.request(method,url,timeout=kw.pop("timeout",180),**kw);r.raise_for_status();return r.json()
def story(topic):
    n=int(os.getenv("SHORTS_SCENES","5"))
    instruction=f'Write a factual engaging documentary Short about {topic}. Output JSON object with scenes array of exactly {n} objects, each with narration (one short sentence) and prompt (detailed cinematic English text-to-video scene; no text or subtitles).'
    result=request("POST",O+"/api/generate",json={"model":os.getenv("OLLAMA_MODEL","qwen2.5:7b"),"prompt":instruction,"stream":False,"format":"json"},timeout=300)
    scenes=json.loads(result["response"])["scenes"]
    if len(scenes)!=n or any(not isinstance(s.get("prompt"),str) or not isinstance(s.get("narration"),str) for s in scenes):raise ValueError("Invalid storyboard")
    return scenes
def clip(prompt,target):
    flow=json.loads(Path(os.environ["SHORTS_WORKFLOW"]).read_text())
    flow=flow.get("prompt",flow)
    node=os.environ["SHORTS_PROMPT_NODE"];field=os.getenv("SHORTS_PROMPT_FIELD","text")
    if field not in flow[node]["inputs"]:raise ValueError("Check prompt node field in exported API workflow")
    flow[node]["inputs"][field]=prompt
    if os.getenv("SHORTS_SEED_NODE"):
        flow[os.environ["SHORTS_SEED_NODE"]]["inputs"][os.getenv("SHORTS_SEED_FIELD","seed")]=random.randrange(1,2**31)
    job=request("POST",C+"/prompt",json={"prompt":flow,"client_id":str(uuid.uuid4())})
    pid=job["prompt_id"];deadline=time.monotonic()+int(os.getenv("SHORTS_JOB_TIMEOUT","3600"))
    while time.monotonic()<deadline:
        entry=request("GET",C+"/history/"+pid).get(pid)
        if entry:
            if entry.get("status",{}).get("status_str")=="error":raise RuntimeError(str(entry["status"]))
            output=entry.get("outputs",{}).get(os.environ["SHORTS_OUTPUT_NODE"],{})
            candidates=[m for key in ("videos","gifs","images") for m in output.get(key,[]) if m.get("filename","").lower().endswith((".mp4",".webm",".mov"))]
            if candidates:
                m=candidates[0]
                r=requests.get(C+"/view",params={"filename":m["filename"],"subfolder":m.get("subfolder",""),"type":m.get("type","output")},timeout=600);r.raise_for_status();target.write_bytes(r.content);return
            if entry.get("status",{}).get("completed"):raise RuntimeError("Output node did not expose video file; adapt workflow output")
        time.sleep(5)
    raise TimeoutError("Video generation timed out")
def voice(text,path):
    import numpy as np,soundfile as sf
    from kokoro import KPipeline
    name=os.getenv("SHORTS_VOICE","af_heart")
    audio=[np.asarray(a,dtype=np.float32) for _,_,a in KPipeline(lang_code=name[0])(text,voice=name)]
    if not audio:raise RuntimeError("Kokoro returned no audio")
    sf.write(str(path),np.concatenate(audio),24000)
def seconds(path):
    return float(subprocess.check_output(["ffprobe","-v","error","-show_entries","format=duration","-of","default=noprint_wrappers=1:nokey=1",str(path)],text=True))
def subtitles(scenes,duration,path):
    weights=[max(1,len(s["narration"].split())) for s in scenes];current=0
    def stamp(n):
        n=round(n*1000);return f"{n//3600000:02}:{n//60000%60:02}:{n//1000%60:02},{n%1000:03}"
    with path.open("w") as f:
        for i,(scene,w) in enumerate(zip(scenes,weights),1):
            end=duration if i==len(scenes) else current+duration*w/sum(weights)
            f.write(f'{i}\n{stamp(current)} --> {stamp(end)}\n{scene["narration"]}\n\n');current=end
def render(clips,audio,captions,out):
    normalized=[]
    for i,p in enumerate(clips):
        target=out.parent/f"norm_{i}.mp4"
        subprocess.run(["ffmpeg","-y","-v","error","-i",str(p),"-vf","scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=24,format=yuv420p","-an","-c:v","libx264","-crf","23",str(target)],check=True)
        normalized.append(target)
    concat=out.parent/"concat.txt"
    concat.write_text("".join("file '"+str(p)+"'\n" for p in normalized))
    joined=out.parent/"joined.mp4"
    subprocess.run(["ffmpeg","-y","-v","error","-f","concat","-safe","0","-i",str(concat),"-c","copy",str(joined)],check=True)
    # Caption path is controlled by this program; use relative name from cwd.
    length=max(seconds(joined),seconds(audio)+0.3)
    subprocess.run(["ffmpeg","-y","-v","error","-stream_loop","-1","-i",str(joined),"-i",str(audio),"-t",str(length),"-vf","subtitles=captions.srt","-map","0:v:0","-map","1:a:0","-c:v","libx264","-crf","23","-pix_fmt","yuv420p","-c:a","aac","-movflags","+faststart",str(out)],check=True,cwd=str(out.parent))
def main(count,dry):
    topics=[s.strip() for s in (ROOT/"topics.txt").read_text().splitlines() if s.strip() and not s.startswith("#")]
    done=0
    for topic in topics:
        if done>=count:break
        slug=re.sub("[^a-z0-9]+","-",topic.lower()).strip("-")[:64]
        path=OUT/datetime.now(timezone.utc).strftime("%Y-%m-%d")/slug
        if (path/"short.mp4").exists():continue
        path.mkdir(parents=True,exist_ok=True)
        try:
            scenes=story(topic);(path/"storyboard.json").write_text(json.dumps(scenes,indent=2))
            if dry:print("DRY RUN",topic);done+=1;continue
            clips=[]
            for i,s in enumerate(scenes):
                p=path/f"clip_{i}.mp4"
                if not p.exists():clip(s["prompt"],p)
                clips.append(p)
            narration=path/"narration.wav"
            if not narration.exists():voice(" ".join(s["narration"] for s in scenes),narration)
            captions=path/"captions.srt"
            subtitles(scenes,seconds(narration),captions)
            render(clips,narration,captions,path/"short.mp4")
            print("COMPLETE",path/"short.mp4");done+=1
        except Exception as exc:
            (path/"error.txt").write_text(str(exc));print("FAILED",topic,exc,flush=True)
    if done<count:raise SystemExit(f"Completed {done}/{count}; inspect output errors or add topics")
if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--count",type=int,default=1)
    parser.add_argument("--dry-run",action="store_true")
    a=parser.parse_args();main(a.count,a.dry_run)
