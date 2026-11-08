"""MindFacto auto Shorts: हर वाक्य के हिसाब से दृश्य। Gemini -> edge-tts -> Pexels/Pixabay -> ffmpeg -> YouTube."""
import asyncio, json, os, pathlib, random, subprocess, time
import requests

WORK = pathlib.Path("work"); WORK.mkdir(exist_ok=True)
HIST = pathlib.Path("history.json")
TOPIC = os.getenv("TOPIC", "everyday life hacks")
VOICE = os.getenv("VOICE", "hi-IN-MadhurNeural")
RATE = os.getenv("VOICE_RATE", "+25%")
PITCH = os.getenv("VOICE_PITCH", "+3Hz")
MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest")
PRIVACY = os.getenv("PRIVACY", "public")
DRY = os.getenv("DRY_RUN", "0") == "1"
SOURCE = {"name": ""}
USED = set()
TITLE = {'t': ''}


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
     "narration": one or two SHORT, punchy Hindi sentences in Devanagari, spoken like an excited friend sharing a secret (lively, conversational, use ! and ? naturally, no formal or bookish words). All narrations together are 75-90 words in total (short and fast). Scene 1 is a strong hook, the last scene ends with a question or asks to follow.
     "query": 1-3 simple English words, the most common stock-footage term for what is shown in this scene, e.g. "pouring tea", "washing dishes", "cutting lemon", "garlic cloves". Concrete and visible, never abstract words like "smart ideas".
     "alt": one simple English noun for the main object of the whole life hack, e.g. "garlic" (same noun is fine in many scenes),
     "alt2": a very common general setting or action word, e.g. "kitchen", "hands", "cooking", "home"."""
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
                await edge_tts.Communicate(t, VOICE, rate=RATE, pitch=PITCH).save(str(p)); break
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


def _pixabay_cands(q, limit=4):
    r = requests.get("https://pixabay.com/api/videos/", timeout=60,
                     params={"key": os.environ["PIXABAY_API_KEY"], "q": q, "per_page": 12, "safesearch": "true"})
    if r.status_code != 200: return []
    out = []
    for h in r.json().get("hits", []):
        if ("x", h["id"]) in USED: continue
        v = h.get("videos", {})
        m = v.get("medium") or v.get("small") or {}
        if m.get("url"):
            out.append({"id": h["id"], "url": m["url"], "q": q, "thumb": m.get("thumbnail") or (v.get("small") or {}).get("thumbnail")})
        if len(out) >= limit: break
    return out


def pick_best(narration, query, cands):
    """Gemini छोटी तस्वीरें देखकर बताता है कि कौन-सी क्लिप इस वाक्य से सबसे ज़्यादा मेल खाती है। -1 = कोई नहीं।"""
    import base64
    parts = [{"text": f"A short vertical video scene says (Hindi): {narration}\nStock-video search used: {query}\n"
                      f"The whole video is about: {TITLE['t']}\n"
                      "Below are candidate thumbnails numbered from 0. Choose the ONE that best shows what the scene talks about, "
                      "or at least the main object or topic of the video, in a clear realistic way. A clip of the right object or setting is acceptable "
                      "even if the exact action differs. Answer -1 ONLY if every image is unrelated to the video topic. Reply ONLY JSON like {\"best\": 2}."}]
    used = 0
    for i, c in enumerate(cands):
        if not c.get("thumb"): continue
        try:
            img = requests.get(c["thumb"], timeout=30).content
            parts.append({"text": f"Image {i}:"})
            parts.append({"inlineData": {"mimeType": "image/jpeg", "data": base64.b64encode(img).decode()}})
            used += 1
        except Exception as e:
            print("thumb failed:", e)
    if used == 0: return 0
    for attempt in range(3):
        try:
            r = requests.post("https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-lite-latest:generateContent",
                              headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]},
                              json={"contents": [{"parts": parts}], "generationConfig": {"responseMimeType": "application/json", "temperature": 0}},
                              timeout=90)
            if r.status_code == 200:
                v = json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"])
                idx = int(v["best"] if isinstance(v, dict) else v[0]["best"])
                return idx if -1 <= idx < len(cands) else 0
            print("pick_best HTTP", r.status_code)
            time.sleep(8 * (attempt + 1))
        except Exception as e:
            print("pick_best error:", e); time.sleep(5)
    return 0


def _generated(idx, dur):
    colors = ["2b5876", "4e4376", "134e5e", "614385", "0f2027", "7b4397", "1d4350", "42275a"]
    out = WORK / f"raw{idx}.mp4"
    sh(["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=0x{random.choice(colors)}:s=1080x1920:r=30:d={dur + 1:.1f}",
        "-vf", "hue=h=t*18:s=1.3,vignette=PI/4", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", str(out)])
    return out


def scene_clip(scene, idx, dur):
    out = WORK / f"raw{idx}.mp4"
    queries = [q for q in (scene.get("query"), scene.get("alt"), scene.get("alt2")) if q]
    if os.getenv("PIXABAY_API_KEY"):
        pool, seen = [], set()
        for q, lim in zip(queries, (4, 3, 2)):
            try: cands = _pixabay_cands(q, lim)
            except Exception as e: print(f"pixabay '{q}' failed: {e}"); continue
            for c in cands:
                if c["id"] not in seen: seen.add(c["id"]); pool.append(c)
        if pool:
            best = pick_best(scene["narration"], queries[0] if queries else "", pool)
            time.sleep(4)
            if best < 0:  # कुछ भी मेल नहीं खाया: विषय वाली चीज़ की क्लिप लो, वरना पहली
                best = next((i for i, c in enumerate(pool) if c["q"] == scene.get("alt")), 0)
            c = pool[best]
            print(f"scene {idx}: '{c['q']}' (pool {len(pool)}, pick {best})")
            try:
                _download(c["url"], out); USED.add(("x", c["id"])); SOURCE["name"] = SOURCE["name"] or "Pixabay"
                return out
            except Exception as e: print("download failed:", e)
    if os.getenv("PEXELS_API_KEY"):
        for q in queries:
            try: res = _find_pexels(q)
            except Exception as e: print("pexels failed:", e); continue
            if res:
                try: _download(res[0], out); SOURCE["name"] = SOURCE["name"] or "Pexels"; return out
                except Exception as e: print("download failed:", e)
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
def _dims(path):
    w, h = sh(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
               "-of", "csv=p=0:s=x", str(path)]).strip().split("x")
    return int(w), int(h)


def _vf(c, seg):
    w, h = _dims(c)
    frames = max(int(seg * 30), 30)
    grade = "eq=contrast=1.04:saturation=1.08"
    zoom = f"zoompan=z='min(1+0.0004*on,1.07)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=1080x1920:fps=30"
    if w / h <= 0.75:  # खड़ी क्लिप: पूरा फ़्रेम भरो
        base = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30,setsar=1"
        return f"{base},{zoom},{grade}"
    # चौड़ी क्लिप: बीच में थोड़ी बड़ी तस्वीर, पीछे उसी की धुंधली परत (कम कटाव, ज़्यादा बाहर का दृश्य)
    return ("split[a][b];[b]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=28:6[bg];"
            "[a]scale=1250:-2:force_original_aspect_ratio=decrease,crop='min(iw,1080)':ih[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2,fps=30,setsar=1,{zoom},{grade}")


def assemble(clips, durs, voice, ass):
    norm = []
    for i, (c, d) in enumerate(zip(clips, durs)):
        seg = d + (0.15 if i == len(clips) - 1 else 0)
        o = WORK / f"seg{i}.mp4"
        sh(["ffmpeg", "-y", "-stream_loop", "-1", "-i", str(c), "-t", f"{seg:.3f}",
            "-vf", _vf(c, seg),
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
    TITLE["t"] = meta["title"]
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
