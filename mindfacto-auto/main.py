"""MindFacto auto Shorts: हर वाक्य के हिसाब से दृश्य। Gemini -> edge-tts -> Pexels/Pixabay -> ffmpeg -> YouTube."""
import asyncio, json, os, pathlib, random, subprocess, time
import requests

WORK = pathlib.Path("work"); WORK.mkdir(exist_ok=True)
HIST = pathlib.Path("history.json")
TOPIC = os.getenv("TOPIC", "everyday life hacks")
VOICE = os.getenv("VOICE", "hi-IN-MadhurNeural")
MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest")
PRIVACY = os.getenv("PRIVACY", "public")
DRY = os.getenv("DRY_RUN", "0") == "1"
SOURCE = {"name": ""}
USED = set()


def sh(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        print(r.stderr[-2000:]); raise SystemExit(f"command failed: {cmd[0]}")
    return r.stdout


def load_history():
    try: return json.loads(HIST.read_text())
    except Exception: return []


def duration(path):
    return float(sh(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                     "-of", "default=nw=1:nk=1", str(path)]).strip())


# 1) स्क्रिप्ट (सीन-दर-सीन) ----------------------------------------------------
def make_script(history):
    prompt = f"""You write viral YouTube Shorts for a Hindi channel called MindFacto. Topic area: {TOPIC}.
Pick ONE practical, safe, genuinely useful life hack (quick, cheap, easy to try today, no medical or dangerous advice).
Do NOT repeat these earlier titles: {history[-40:]}.
Return ONLY JSON with these keys:
  "title": catchy Hindi title under 70 characters (no hashtags),
  "description": 2 Hindi lines + hashtags #Shorts #MindFacto #lifehacks,
  "tags": list of up to 8 short tags,
  "scenes": list of 7 objects in story order. Each object has:
     "narration": one or two SHORT Hindi sentences in Devanagari. All narrations together are 90-110 words. Scene 1 is a strong hook, the last scene ends with a question or asks to follow.
     "query": 2-3 English words for a stock-video search that show EXACTLY what this narration talks about. Concrete, visible and filmable, e.g. "pouring tea", "washing dishes", "hands cutting lemon". Never abstract words like "smart ideas" or "life hacks".
     "alt": one simple English noun for the main object in this scene, e.g. "tea cup"."""
    models = [MODEL] + [m for m in ("gemini-flash-lite-latest", "gemini-flash-latest", "gemini-2.5-flash", "gemini-2.5-flash-lite") if m != MODEL]
    r = None
    for model in models:
        for attempt in range(4):
            try:
                r = requests.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                    headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]},
                    json={"contents": [{"parts": [{"text": prompt}]}],
                          "generationConfig": {"responseMimeType": "application/json", "temperature": 1.0}},
                    timeout=120)
            except requests.RequestException as e:
                print(f"{model}: network error {e}"); r = None; time.sleep(10); continue
            if r.status_code == 200:
                print("Gemini model:", model); break
            print(f"{model}: HTTP {r.status_code} (try {attempt + 1})")
            if r.status_code in (429, 500, 503): time.sleep(15 * (attempt + 1)); continue
            break
        if r is not None and r.status_code == 200: break
    if r is None or r.status_code != 200:
        raise SystemExit(f"Gemini नहीं चला: {None if r is None else r.status_code} {None if r is None else r.text[:300]}")
    data = json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"])
    if isinstance(data, list): data = data[0]
    scenes = [s for s in data["scenes"] if str(s.get("narration", "")).strip()]
    assert len(scenes) >= 4, "too few scenes"
    data["scenes"] = scenes
    for k in ("title", "description", "tags"):
        assert k in data, f"missing {k}"
    return data


# 2) आवाज़ (हर सीन की अलग) --------------------------------------------------------
async def _tts_all(texts, paths):
    import edge_tts
    for t, p in zip(texts, paths):
        for attempt in range(3):
            try:
                await edge_tts.Communicate(t, VOICE).save(str(p)); break
            except Exception as e:
                print("TTS retry:", e); await asyncio.sleep(3)
        else:
            raise SystemExit("आवाज़ नहीं बन पाई")


def make_voice(scenes):
    paths = [WORK / f"scene{i}.mp3" for i in range(len(scenes))]
    asyncio.run(_tts_all([s["narration"] for s in scenes], paths))
    durs = [duration(p) for p in paths]
    lst = WORK / "voice_list.txt"
    lst.write_text("".join(f"file '{p.name}'\n" for p in paths))
    out = WORK / "voice.mp3"
    sh(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c:a", "libmp3lame", "-q:a", "4", str(out)])
    return out, durs


# 3) हर सीन का फ़ुटेज -------------------------------------------------------------
def _download(url, out):
    with requests.get(url, stream=True, timeout=120) as d:
        d.raise_for_status()
        with open(out, "wb") as fh:
            for chunk in d.iter_content(1 << 20): fh.write(chunk)


def _find_pexels(q):
    r = requests.get("https://api.pexels.com/videos/search", headers={"Authorization": os.environ["PEXELS_API_KEY"]},
                     params={"query": q, "orientation": "portrait", "per_page": 6}, timeout=60)
    if r.status_code != 200: return None
    vids = [v for v in r.json().get("videos", []) if ("p", v["id"]) not in USED]
    random.shuffle(vids)
    for v in vids[:4]:
        files = [f for f in v["video_files"] if f.get("file_type") == "video/mp4" and f.get("width", 0) >= 720]
        if files:
            USED.add(("p", v["id"])); return min(files, key=lambda x: x["width"])["link"], "Pexels"
    return None


def _find_pixabay(q):
    r = requests.get("https://pixabay.com/api/videos/", timeout=60,
                     params={"key": os.environ["PIXABAY_API_KEY"], "q": q, "per_page": 8, "safesearch": "true"})
    if r.status_code != 200: return None
    hits = [h for h in r.json().get("hits", []) if ("x", h["id"]) not in USED]
    top = hits[:5]  # सबसे मेल खाते नतीजे
    random.shuffle(top)
    for h in top:
        v = h.get("videos", {})
        url = (v.get("medium") or {}).get("url") or (v.get("small") or {}).get("url")
        if url:
            USED.add(("x", h["id"])); return url, "Pixabay"
    return None


def _generated(idx, dur):
    colors = ["2b5876", "4e4376", "134e5e", "614385", "0f2027", "7b4397", "1d4350", "42275a"]
    out = WORK / f"raw{idx}.mp4"
    sh(["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=0x{random.choice(colors)}:s=1080x1920:r=30:d={dur + 1:.1f}",
        "-vf", "hue=h=t*18:s=1.3,vignette=PI/4", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", str(out)])
    return out


def scene_clip(scene, idx, dur):
    finders = []
    if os.getenv("PEXELS_API_KEY"): finders.append(_find_pexels)
    if os.getenv("PIXABAY_API_KEY"): finders.append(_find_pixabay)
    for q in (scene.get("query"), scene.get("alt")):
        if not q: continue
        for find in finders:
            try:
                res = find(q)
            except Exception as e:
                print(f"{find.__name__} '{q}' failed: {e}"); continue
            if res:
                out = WORK / f"raw{idx}.mp4"
                try: _download(res[0], out)
                except Exception as e: print("download failed:", e); continue
                SOURCE["name"] = SOURCE["name"] or res[1]
                print(f"scene {idx}: '{q}' -> {res[1]}")
                return out
        time.sleep(0.7)
    print(f"scene {idx}: फ़ुटेज नहीं मिला, बैकग्राउंड")
    return _generated(idx, dur)


# 4) कैप्शन ------------------------------------------------------------------------
def ts(t):
    h, m, s = int(t // 3600), int(t % 3600 // 60), t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def make_ass(scenes, durs):
    head = ("[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n\n"
            "[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,"
            "Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,"
            "MarginL,MarginR,MarginV,Encoding\n"
            "Style: Default,Noto Sans Devanagari,78,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,5,2,2,60,60,430,1\n\n"
            "[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n")
    t0, lines = 0.0, []
    for s, d in zip(scenes, durs):
        words = s["narration"].split()
        chunks = [" ".join(words[i:i + 4]) for i in range(0, len(words), 4)] or [""]
        total = sum(len(c) for c in chunks) or 1
        t = t0
        for c in chunks:
            cd = d * len(c) / total
            lines.append(f"Dialogue: 0,{ts(t)},{ts(t + cd)},Default,,0,0,0,,{c}")
            t += cd
        t0 += d
    p = WORK / "subs.ass"; p.write_text(head + "\n".join(lines), encoding="utf-8")
    return p


# 5) वीडियो जोड़ना -----------------------------------------------------------------
def assemble(clips, durs, voice, ass):
    norm = []
    for i, (c, d) in enumerate(zip(clips, durs)):
        seg = d + (0.15 if i == len(clips) - 1 else 0)
        o = WORK / f"seg{i}.mp4"
        sh(["ffmpeg", "-y", "-stream_loop", "-1", "-i", str(c), "-t", f"{seg:.3f}",
            "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30,setsar=1",
            "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p", str(o)])
        norm.append(o)
    lst = WORK / "list.txt"
    lst.write_text("".join(f"file '{p.name}'\n" for p in norm))
    joined = WORK / "joined.mp4"
    sh(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(joined)])
    final = WORK / "final.mp4"
    sh(["ffmpeg", "-y", "-i", str(joined), "-i", str(voice), "-vf", f"ass={ass.as_posix()}",
        "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
        "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", str(final)])
    return final


# 6) YouTube अपलोड -----------------------------------------------------------------
def upload(video, meta):
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    creds = Credentials(None, refresh_token=os.environ["YT_REFRESH_TOKEN"],
                        token_uri="https://oauth2.googleapis.com/token",
                        client_id=os.environ["YT_CLIENT_ID"], client_secret=os.environ["YT_CLIENT_SECRET"],
                        scopes=["https://www.googleapis.com/auth/youtube.upload"])
    yt = build("youtube", "v3", credentials=creds)
    desc = meta["description"] + (f"\n\nFootage: {SOURCE['name']}" if SOURCE["name"] else "")
    body = {"snippet": {"title": meta["title"][:95] + " #Shorts", "description": desc,
                        "tags": meta["tags"][:8], "categoryId": "27"},
            "status": {"privacyStatus": PRIVACY, "selfDeclaredMadeForKids": False}}
    req = yt.videos().insert(part="snippet,status", body=body,
                             media_body=MediaFileUpload(str(video), chunksize=-1, resumable=True))
    resp = None
    while resp is None:
        _, resp = req.next_chunk()
    print("Uploaded: https://youtube.com/shorts/" + resp["id"])


def main():
    hist = load_history()
    meta = make_script(hist)
    scenes = meta["scenes"]
    print("Title:", meta["title"])
    voice, durs = make_voice(scenes)
    print(f"Voice: {sum(durs):.1f}s in {len(scenes)} scenes")
    clips = [scene_clip(s, i, d) for i, (s, d) in enumerate(zip(scenes, durs))]
    ass = make_ass(scenes, durs)
    final = assemble(clips, durs, voice, ass)
    print("Video ready:", final)
    if not (DRY or not os.getenv("YT_REFRESH_TOKEN")):
        upload(final, meta)
    else:
        print("अपलोड छोड़ा गया (DRY_RUN या YouTube की key नहीं है). वीडियो Artifacts में मिलेगी।")
    if not DRY:
        hist.append(meta["title"]); HIST.write_text(json.dumps(hist[-200:], ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
