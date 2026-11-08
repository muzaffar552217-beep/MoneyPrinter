"""MindFacto auto Shorts: Gemini script -> edge-tts Hindi voice -> Pexels clips -> ffmpeg -> YouTube."""
import asyncio, json, os, pathlib, random, re, subprocess, sys
import requests

WORK = pathlib.Path("work"); WORK.mkdir(exist_ok=True)
HIST = pathlib.Path("history.json")
TOPIC = os.getenv("TOPIC", "everyday life hacks")
VOICE = os.getenv("VOICE", "hi-IN-MadhurNeural")
MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
PRIVACY = os.getenv("PRIVACY", "public")
DRY = os.getenv("DRY_RUN", "0") == "1"
SOURCE = {"name": ""}


def sh(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        print(r.stderr[-2000:]); raise SystemExit(f"command failed: {cmd[0]}")
    return r.stdout


def load_history():
    try: return json.loads(HIST.read_text())
    except Exception: return []


# 1) स्क्रिप्ट -----------------------------------------------------------
def make_script(history):
    prompt = f"""You write viral YouTube Shorts for a Hindi channel called MindFacto. Topic area: {TOPIC}.
Pick ONE practical, safe, genuinely useful life hack (quick, cheap, easy to try today, no medical or dangerous advice). Do NOT repeat these earlier titles: {history[-40:]}.
Return ONLY JSON with keys:
  "title": catchy Hindi title under 70 characters (no hashtags),
  "script": Hindi narration in Devanagari, 95-115 words, strong hook in the first sentence, short sentences, ends with a question or call to follow,
  "keywords": list of 6 English stock-video search words (visual, concrete, e.g. "brain", "city night", "person thinking"),
  "description": 2 Hindi lines + hashtags #Shorts #MindFacto #lifehacks,
  "tags": list of up to 8 short tags."""
    r = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent",
        headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]},
        json={"contents": [{"parts": [{"text": prompt}]}],
              "generationConfig": {"responseMimeType": "application/json", "temperature": 1.0}},
        timeout=120)
    r.raise_for_status()
    data = json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"])
    if isinstance(data, list): data = data[0]
    for k in ("title", "script", "keywords", "description", "tags"):
        assert k in data, f"missing {k}"
    return data


# 2) आवाज़ ----------------------------------------------------------------
async def _tts(text, path):
    import edge_tts
    await edge_tts.Communicate(text, VOICE).save(str(path))


def make_voice(text):
    p = WORK / "voice.mp3"
    asyncio.run(_tts(text, p))
    dur = float(sh(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                    "-of", "default=nw=1:nk=1", str(p)]).strip())
    return p, dur


# 3) फ़ुटेज (Pexels -> Pixabay -> अपने आप बनी बैकग्राउंड) -----------------------
def _download(url, out):
    with requests.get(url, stream=True, timeout=120) as d:
        d.raise_for_status()
        with open(out, "wb") as fh:
            for chunk in d.iter_content(1 << 20): fh.write(chunk)


def _pexels(keywords, n):
    headers = {"Authorization": os.environ["PEXELS_API_KEY"]}
    paths = []
    for kw in (keywords * 3)[: n * 2]:
        if len(paths) >= n: break
        r = requests.get("https://api.pexels.com/videos/search", headers=headers, timeout=60,
                         params={"query": kw, "orientation": "portrait", "per_page": 10})
        if r.status_code != 200: continue
        vids = r.json().get("videos", []); random.shuffle(vids)
        for v in vids:
            files = [f for f in v["video_files"] if f.get("file_type") == "video/mp4" and f.get("width", 0) >= 720]
            if not files: continue
            out = WORK / f"raw{len(paths)}.mp4"
            _download(min(files, key=lambda x: x["width"])["link"], out)
            paths.append(out); break
    return paths


def _pixabay(keywords, n):
    paths = []
    for kw in (keywords * 3)[: n * 2]:
        if len(paths) >= n: break
        r = requests.get("https://pixabay.com/api/videos/", timeout=60,
                         params={"key": os.environ["PIXABAY_API_KEY"], "q": kw, "per_page": 10, "safesearch": "true"})
        if r.status_code != 200: continue
        hits = r.json().get("hits", []); random.shuffle(hits)
        for h in hits:
            url = (h.get("videos", {}).get("medium") or {}).get("url") or (h.get("videos", {}).get("small") or {}).get("url")
            if not url: continue
            out = WORK / f"raw{len(paths)}.mp4"
            _download(url, out)
            paths.append(out); break
    return paths


def _generated(n):
    """कोई key न हो तो रंग बदलती साफ़ बैकग्राउंड बनाता है।"""
    colors = ["2b5876", "4e4376", "134e5e", "614385", "0f2027", "7b4397", "1d4350", "42275a"]
    random.shuffle(colors)
    paths = []
    for i in range(n):
        out = WORK / f"raw{i}.mp4"
        sh(["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=0x{colors[i % len(colors)]}:s=1080x1920:r=30:d=8",
            "-vf", "hue=h=t*18:s=1.3,vignette=PI/4", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", str(out)])
        paths.append(out)
    return paths


def fetch_clips(keywords, n):
    paths = []
    if os.getenv("PEXELS_API_KEY"):
        try:
            paths = _pexels(keywords, n)
            if len(paths) >= 2: SOURCE["name"] = "Pexels"
        except Exception as e: print("Pexels failed:", e)
    if len(paths) < 2 and os.getenv("PIXABAY_API_KEY"):
        try:
            paths = _pixabay(keywords, n)
            if len(paths) >= 2: SOURCE["name"] = "Pixabay"
        except Exception as e: print("Pixabay failed:", e)
    if len(paths) < 2:
        print("फ़ुटेज नहीं मिला, बनी हुई बैकग्राउंड इस्तेमाल हो रही है")
        paths = _generated(n)
    return paths


# 4) कैप्शन (ASS) -----------------------------------------------------------
def ts(t):
    h, m, s = int(t // 3600), int(t % 3600 // 60), t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def make_ass(script, dur):
    words = script.split()
    chunks = [" ".join(words[i:i + 4]) for i in range(0, len(words), 4)]
    total = sum(len(c) for c in chunks) or 1
    head = ("[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n\n"
            "[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,"
            "Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,"
            "MarginL,MarginR,MarginV,Encoding\n"
            "Style: Default,Noto Sans Devanagari,78,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,5,2,2,60,60,430,1\n\n"
            "[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n")
    t, lines = 0.0, []
    for c in chunks:
        d = dur * len(c) / total
        lines.append(f"Dialogue: 0,{ts(t)},{ts(t + d)},Default,,0,0,0,,{c}")
        t += d
    p = WORK / "subs.ass"; p.write_text(head + "\n".join(lines), encoding="utf-8")
    return p


# 5) वीडियो जोड़ना -----------------------------------------------------------
def assemble(clips, voice, dur, ass):
    seg = (dur + 0.6) / len(clips)
    norm = []
    for i, c in enumerate(clips):
        o = WORK / f"seg{i}.mp4"
        sh(["ffmpeg", "-y", "-stream_loop", "-1", "-i", str(c), "-t", f"{seg:.2f}",
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
        "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", str(final)],)
    return final


# 6) YouTube अपलोड -----------------------------------------------------------
def upload(video, meta):
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    creds = Credentials(None, refresh_token=os.environ["YT_REFRESH_TOKEN"],
                        token_uri="https://oauth2.googleapis.com/token",
                        client_id=os.environ["YT_CLIENT_ID"], client_secret=os.environ["YT_CLIENT_SECRET"],
                        scopes=["https://www.googleapis.com/auth/youtube.upload"])
    yt = build("youtube", "v3", credentials=creds)
    body = {"snippet": {"title": meta["title"][:95] + " #Shorts", "description": meta["description"] + (f"\n\nFootage: {SOURCE['name']}" if SOURCE["name"] else ""),
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
    print("Title:", meta["title"])
    voice, dur = make_voice(meta["script"])
    print(f"Voice: {dur:.1f}s")
    clips = fetch_clips(meta["keywords"], 6)
    ass = make_ass(meta["script"], dur)
    final = assemble(clips, voice, dur, ass)
    print("Video ready:", final)
    if DRY:
        print("DRY_RUN: upload skipped"); return
    upload(final, meta)
    hist.append(meta["title"]); HIST.write_text(json.dumps(hist[-200:], ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
