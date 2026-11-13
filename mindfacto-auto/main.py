"""MindFacto auto Shorts: हर वाक्य के हिसाब से दृश्य। Gemini -> edge-tts -> Pexels/Pixabay -> ffmpeg -> YouTube."""
import asyncio, json, os, pathlib, random, subprocess, time
import requests

WORK = pathlib.Path("work"); WORK.mkdir(exist_ok=True)
HIST = pathlib.Path("history.json")
TOPIC = os.getenv("TOPIC", "everyday life hacks")
VOICE = os.getenv("VOICE", "hi-IN-MadhurNeural")
RATE = os.getenv("VOICE_RATE", "+20%")
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
Return ONLY JSON with these keys, in this exact order:
  "scenes": list of 7 objects in story order. Each object has:
     "narration": one or two SHORT, punchy Hindi sentences in Devanagari, spoken like an excited friend sharing a secret (lively, conversational, use ! and ? naturally, no formal or bookish words). All narrations together are 75-90 words in total (short and fast). Scene 1 is a strong hook, the last scene ends with a question or asks to follow.
     "caption_en": natural English subtitle for this narration, same meaning, simple words, max 14 words, no emojis,
     "query": 1-3 simple English words for a stock-video search that shows EXACTLY what this scene shows: a visible object or action, e.g. "pouring tea", "washing dishes", "banana peel", "polishing shoes". For hook and call-to-action scenes use the main object of the hack (e.g. "banana peel", "leather shoes"). NEVER use emotions, people-only words, "subscribe", "button", "text" or abstract words,
     "alt": one simple English noun for the main object of the whole life hack, e.g. "banana peel",
     "alt2": a very common related setting or action word, e.g. "kitchen", "hands", "cleaning", "home".
  "title": catchy Hindi title under 70 characters (no hashtags) that describes EXACTLY the life hack told in the scenes above,
  "description": 2 Hindi lines about that same hack + hashtags #Shorts #MindFacto #lifehacks,
  "tags": list of up to 8 short tags.
"""
    models = [first or MODEL]; models += [m for m in ("gemini-2.5-flash", "gemini-flash-latest", "gemini-flash-lite-latest", "gemini-2.5-flash-lite") if m not in models]
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


# 2) आवाज़ (हर सीन की अलग; पहले Gemini की जानदार आवाज़, न चले तो edge-tts) -------------
GEMINI_VOICE = os.getenv("GEMINI_VOICE", "Puck")
TTS_MODEL = os.getenv("GEMINI_TTS_MODEL", "gemini-2.5-flash-preview-tts")
ENGINE = {"name": ""}


def _polish(src, dst, tempo):
    """शुरू और आख़िर की चुप्पी हटाओ, थोड़ा तेज़ करो, WAV बनाओ (सटीक समय के लिए)।"""
    trim = "silenceremove=start_periods=1:start_threshold=-48dB:start_silence=0.05"
    sh(["ffmpeg", "-y", "-i", str(src), "-af", f"{trim},areverse,{trim},areverse,atempo={tempo},apad=pad_dur=0.06",
        "-ar", "24000", "-ac", "1", str(dst)])


def _tts_gemini(text, dst):
    import base64
    prompt = f"Say this in Hindi in an energetic, friendly, upbeat, fast-paced tone like a popular YouTube Shorts storyteller: {text}"
    r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{TTS_MODEL}:generateContent",
                      headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]},
                      json={"contents": [{"parts": [{"text": prompt}]}],
                            "generationConfig": {"responseModalities": ["AUDIO"],
                                                 "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": GEMINI_VOICE}}}}},
                      timeout=180)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code} {r.text[:150]!r}")
    data = base64.b64decode(r.json()["candidates"][0]["content"]["parts"][0]["inlineData"]["data"])
    raw = dst.with_suffix(".pcm"); raw.write_bytes(data)
    tmp = dst.with_suffix(".raw.wav")
    sh(["ffmpeg", "-y", "-f", "s16le", "-ar", "24000", "-ac", "1", "-i", str(raw), str(tmp)])
    _polish(tmp, dst, 1.10)


async def _tts_edge(texts, paths):
    import edge_tts, re
    variants = [dict(voice=VOICE, rate=RATE, pitch=PITCH), dict(voice=VOICE, rate=RATE), dict(voice=VOICE),
                dict(voice="hi-IN-SwaraNeural", rate=RATE), dict(voice="hi-IN-SwaraNeural"), dict(voice=VOICE, rate="+10%")]
    for t, p in zip(texts, paths):
        t = re.sub(r"[#*_~`|<>\[\]{}\"\u201c\u201d]|[\U00010000-\U0010ffff]", " ", t).strip() or "."
        for v in variants:
            try:
                kw = dict(v); voice = kw.pop("voice")
                await edge_tts.Communicate(t, voice, **kw).save(str(p))
                if pathlib.Path(p).exists() and pathlib.Path(p).stat().st_size > 800: break
            except Exception as e:
                print("TTS retry:", v.get("voice"), e); await asyncio.sleep(2)
        else:
            raise SystemExit("आवाज़ नहीं बन पाई")


def make_voice(scenes):
    wavs = [WORK / f"scene{i}.wav" for i in range(len(scenes))]
    ok = False
    if os.getenv("USE_GEMINI_TTS", "0") == "1":
        try:
            for i, s in enumerate(scenes):
                _tts_gemini(s["narration"], wavs[i]); time.sleep(5)
            ok = True; ENGINE["name"] = f"Gemini TTS ({GEMINI_VOICE})"
        except Exception as e:
            print("Gemini TTS नहीं चला, edge-tts पर जा रहे हैं:", e)
    if not ok:
        mp3s = [WORK / f"scene{i}.mp3" for i in range(len(scenes))]
        asyncio.run(_tts_edge([s["narration"] for s in scenes], mp3s))
        for m, w in zip(mp3s, wavs): _polish(m, w, 1.0)
        ENGINE["name"] = f"edge-tts ({VOICE})"
    print("Voice engine:", ENGINE["name"])
    durs = [duration(w) for w in wavs]
    lst = WORK / "voice_list.txt"
    lst.write_text("".join(f"file '{w.name}'\n" for w in wavs))
    out = WORK / "voice.wav"
    sh(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(out)])
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
                     params={"key": os.environ["PIXABAY_API_KEY"], "q": q, "per_page": 14, "safesearch": "true", "video_type": "film"})
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
                      "Below are candidate thumbnails numbered from 0. Choose the ONE that best shows the object or action of this scene in a clear, sharp, realistic, well-lit shot "
                      "(prefer close-ups of the actual object or action). REJECT a candidate if it is blurry or out of focus, a green screen or solid-color background, "
                      "a cartoon or animation, has text, buttons or logos, or only shows unrelated scenery. A clip of the main object of the video is acceptable only if no better scene match exists. "
                      "Answer -1 if no candidate passes. Reply ONLY JSON like {\"best\": 2}."}]
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


def _gemini(parts, temp=1.0, first=None):
    import base64  # noqa
    models = [MODEL] + [m for m in ("gemini-flash-lite-latest", "gemini-flash-latest", "gemini-2.5-flash", "gemini-2.5-flash-lite") if m != MODEL]
    for model in models:
        for attempt in range(3):
            try:
                r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                                  headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]},
                                  json={"contents": [{"parts": parts}],
                                        "generationConfig": {"responseMimeType": "application/json", "temperature": temp}}, timeout=120)
            except requests.RequestException as e:
                print(model, "network", e); time.sleep(8); continue
            if r.status_code == 200:
                d = json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"])
                return d[0] if isinstance(d, list) else d
            print(f"{model}: HTTP {r.status_code}")
            if r.status_code in (429, 500, 503): time.sleep(12 * (attempt + 1)); continue
            break
    raise RuntimeError("Gemini failed")


def footage_first(history):
    """पहले फुटेज चुनो, फिर Gemini उसी फुटेज को देखकर स्क्रिप्ट लिखे -> आवाज़ और विज़ुअल हमेशा मेल खाते हैं।"""
    import base64
    plan = _gemini([{"text": f"""Plan a YouTube Short about ONE safe, useful everyday life hack (topic area: {TOPIC}). ONLY use real, true, widely known and safe hacks; never invent facts or add ingredients that do nothing (no myths). Do NOT repeat: {history[-40:]}.
Stock-video libraries only have COMMON footage. Choose ONLY a hack about fruits, vegetables, rice/dal/milk/eggs, lemon, water, washing dishes or clothes, plants, or kitchen cleaning, so every step has a clearly filmable shot. Never choose hacks about price tags, stickers, glue, tools, wires, screws or small objects. Every search phrase must be a very common stock-video subject (e.g. 'lemon', 'pouring water', 'washing hands', 'cutting vegetables').
Return ONLY JSON: {{"hack": "one English sentence describing the hack", "queries": [9 different stock-video search phrases, 1-3 plain English words each, each a common visible object or action that fits the hack in story order]}}"""}])
    hack, queries = plan["hack"], [str(q) for q in plan["queries"]][:9]
    print("Hack:", hack, queries)
    TITLE["t"] = hack
    chosen = []; fb = []
    for i, q in enumerate(queries):
        cands = []
        try: cands = [c for c in _pixabay_cands(q, 8) if c["id"] not in {x["id"] for x in chosen if x}]
        except Exception as e: print("pixabay failed:", e)
        if not cands: chosen.append(None); fb.append(None); continue
        fb.append(cands[0])
        b = pick_best(f"Shot {i + 1} of a video about: {hack}", q, cands)
        time.sleep(4)
        chosen.append(cands[b] if b >= 0 else None)
        print(f"shot {i}: '{q}' ->", None if b < 0 else cands[b]["id"])
    keep = [(q, c) for q, c in zip(queries, chosen) if c]
    if len(keep) < 6:  # सख़्त चुनाव में कम पड़ें तो सबसे relevant बाकी क्लिप भरो
        used = {c["id"] for c in chosen if c}
        for i, (q, c) in enumerate(zip(queries, chosen)):
            if not c and fb[i] and fb[i]["id"] not in used and len(keep) < 6:
                chosen[i] = fb[i]; used.add(fb[i]["id"])
        keep = [(q, c) for q, c in zip(queries, chosen) if c]
    if len(keep) < 6: raise AssertionError("not enough footage")
    parts = [{"text": f"""You write a viral Hindi YouTube Short (channel MindFacto) about this life hack: {hack}.
Below are {len(keep)} stock-video thumbnails in story order. For EACH image write the narration that is spoken while that exact shot is on screen. The narration must describe or fit what is truly visible in that image, no contradictions.
Hindi in Devanagari, one or two short lively sentences per image, like an excited friend. Tell the HACK step by step (what to do and why it works), do NOT just describe what the picture shows, all together 105-125 words (about 40 seconds when spoken). First = a shocking curiosity hook under 8 words, no greeting. the LAST scene must give a clear reason to subscribe: first ask ONE simple question viewers answer in the comments (e.g. 'Did you know this? Comment YES or NO!'), then say that MindFacto brings one new life hack EVERY DAY and tease tomorrow's hack by name (e.g. 'Subscribe to MindFacto, tomorrow: a trick to stop milk from boiling over!').
Return ONLY JSON: {{"scenes": [{{"narration": "...", "caption_en": "same meaning in simple English, max 14 words"}} one per image in order], "title": "Hindi title under 70 chars describing exactly this hack", "description": "2 Hindi lines + #Shorts #MindFacto #lifehacks", "tags": [up to 8]}}"""}]
    for i, (q, c) in enumerate(keep):
        try:
            img = requests.get(c["thumb"], timeout=30).content
            parts += [{"text": f"Image {i}:"}, {"inlineData": {"mimeType": "image/jpeg", "data": base64.b64encode(img).decode()}}]
        except Exception as e:
            print("thumb failed:", e); parts.append({"text": f"Image {i}: (search: {q})"})
    data = _gemini(parts, 0.9, first="gemini-2.5-flash")
    sc = data["scenes"][:len(keep)]
    assert len(sc) == len(keep), "scene count mismatch"
    for s, (q, c) in zip(sc, keep): s["_cand"] = c; s["query"] = q
    data["scenes"] = sc
    for k in ("title", "description", "tags"): assert k in data
    assert sum(len(x["narration"].split()) for x in sc) >= 75, "script too short"
    return data


def _cf_image(prompt, dst):
    url = f"https://api.cloudflare.com/client/v4/accounts/{os.environ['CF_ACCOUNT_ID']}/ai/run/@cf/black-forest-labs/flux-1-schnell"
    for attempt in range(3):
        try:
            r = requests.post(url, headers={"Authorization": f"Bearer {os.environ['CF_API_TOKEN']}"},
                              json={"prompt": prompt, "steps": 6}, timeout=120)
            if r.status_code == 200:
                import base64
                dst.write_bytes(base64.b64decode(r.json()["result"]["image"])); return True
            print("cf image HTTP", r.status_code, r.text[:150])
        except Exception as e: print("cf image error:", e)
        time.sleep(6 * (attempt + 1))
    return False


def ai_images(history):
    """AI हर सीन के लिए असली जैसी फोटो बनाता है -> दृश्य हमेशा बोले हुए से मेल खाता है।"""
    data = _gemini([{"text": f"""You write a viral Hindi YouTube Short for channel MindFacto. Pick ONE safe, useful, easy everyday life hack (topic area: {TOPIC}). ONLY use real, true, widely known and safe hacks; never invent facts or add ingredients that do nothing (no myths). Do NOT repeat: {history[-40:]}.
Return ONLY JSON: {{"scenes": [10 objects in story order, each: "narration": one or two SHORT lively Hindi sentences in Devanagari like an excited friend (all together 105-125 words (about 40 seconds when spoken)). SCENE 1 MUST be a shocking curiosity hook in under 8 words that makes people stop scrolling (e.g. a surprising claim or 'you have been doing this wrong!'), NO greeting. Use a surprising fact or a 'before vs after' payoff, build tension, reveal the trick in the middle, the LAST scene must give a clear reason to subscribe: first ask ONE simple question viewers answer in the comments (e.g. 'Did you know this? Comment YES or NO!'), then say that MindFacto brings one new life hack EVERY DAY and tease tomorrow's hack by name (e.g. 'Subscribe to MindFacto, tomorrow: a trick to stop milk from boiling over!'), "caption_en": same meaning in simple English max 14 words, "image_prompt": English prompt for ONE realistic vertical photo of EXACTLY what is happening in this narration: name the objects, hands, place, lighting. Style: realistic smartphone photo, natural light, sharp focus, wide shot, no text, no logos, no cartoon],
 "title": Hindi title under 70 chars describing exactly this hack, "description": 2 Hindi lines + #Shorts #MindFacto #lifehacks, "tags": [up to 8]}}"""}])
    sc = [x for x in data["scenes"] if x.get("narration") and x.get("image_prompt")]
    assert len(sc) >= 5
    for i, x in enumerate(sc):
        img = WORK / f"img{i}.jpg"
        if not _cf_image(x["image_prompt"] + ", photorealistic, ultra detailed, sharp focus", img): raise RuntimeError("image failed")
        x["_img"] = img; x["query"] = x["image_prompt"][:60]
    data["scenes"] = sc
    for k in ("title", "description", "tags"): assert k in data
    assert sum(len(x["narration"].split()) for x in sc) >= 75, "script too short"
    SOURCE["name"] = "AI-generated images (Cloudflare FLUX)"
    return data


def scene_clip(scene, idx, dur):
    out = WORK / f"raw{idx}.mp4"
    if scene.get("_img"):
        sh(["ffmpeg", "-y", "-loop", "1", "-framerate", "30", "-i", str(scene["_img"]), "-t", f"{dur + 1:.2f}",
            "-vf", f"scale=w='1080*(1+0.07*t/{dur + 1:.2f})':h=-2:eval=frame,crop=1080:1080,format=yuv420p", "-c:v", "libx264", "-preset", "veryfast", "-r", "30", str(out)])
        return out
    if scene.get("_cand"):
        try:
            _download(scene["_cand"]["url"], out); USED.add(("x", scene["_cand"]["id"])); SOURCE["name"] = SOURCE["name"] or "Pixabay"
            return out
        except Exception as e: print("download failed:", e)
    queries = [q for q in (scene.get("query"), scene.get("alt"), scene.get("alt2")) if q]
    if os.getenv("PIXABAY_API_KEY"):
        pool, seen = [], set()
        for q, lim in zip(queries, (6, 3, 2)):
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


# 4) कैप्शन (अंग्रेज़ी) -----------------------------------------------------------
def ts(t):
    h, m, s = int(t // 3600), int(t % 3600 // 60), t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def make_ass(scenes, durs):
    head = ("[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n\n"
            "[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,"
            "Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,"
            "MarginL,MarginR,MarginV,Encoding\n"
            "Style: Default,Noto Sans,100,&H0000E5FF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,6,2,2,70,70,420,1\n\n"
            "[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n")
    t0, lines = 0.0, []
    for s, d in zip(scenes, durs):
        text = (s.get("caption_en") or s["narration"]).replace("{", "(").replace("}", ")").replace("\n", " ")
        words = text.split()
        chunks = [" ".join(words[i:i + 3]).upper() for i in range(0, len(words), 3)] or [""]
        total = sum(len(c) for c in chunks) or 1
        t = t0
        for c in chunks:
            cd = d * len(c) / total
            lines.append(f"Dialogue: 0,{ts(t)},{ts(t + cd)},Default,,0,0,0,,{c}")
            t += cd
        t0 += d
    p = WORK / "subs.ass"; p.write_text(head + "\n".join(lines), encoding="utf-8")
    return p


# 5) वीडियो जोड़ना (फ़्रेम-सटीक, बिना ज़ूम के झटके) ------------------------------------
FPS = 30


def _dims(path):
    w, h = sh(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
               "-of", "csv=p=0:s=x", str(path)]).strip().split("x")
    return int(w), int(h)


def _vf(c, stretch=""):
    w, h = _dims(c)
    grade = "eq=contrast=1.04:saturation=1.06"
    if w / h <= 0.75:  # खड़ी क्लिप: पूरा फ़्रेम भरो
        return f"{stretch}scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps={FPS},setsar=1,{grade}"
    # चौड़ी क्लिप: ज़्यादा दृश्य दिखे, पीछे उसी की धुंधली परत
    return (f"{stretch}split[a][b];[b]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=28:6[bg];"
            "[a]scale=1080:-2[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2,fps={FPS},setsar=1,{grade}")


def assemble(clips, durs, voice, ass):
    norm, prev, cum = [], 0, 0.0
    for i, (c, d) in enumerate(zip(clips, durs)):
        cum += d
        end = round(cum * FPS)
        n = max(end - prev, 2) + (6 if i == len(clips) - 1 else 0)
        prev = end
        seg, cd = n / FPS, duration(c)
        loop, stretch = [], ""
        if cd < seg:
            r = seg / cd
            if r <= 1.6: stretch = f"setpts=PTS*{r:.4f},"  # थोड़ी धीमी करके खींचो, कटाव नहीं
            else: loop = ["-stream_loop", "-1"]
        o = WORK / f"seg{i}.mp4"
        sh(["ffmpeg", "-y"] + loop + ["-i", str(c), "-vf", _vf(c, stretch), "-frames:v", str(n), "-an", "-r", str(FPS),
            "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", str(o)])
        norm.append(o)
    lst = WORK / "list.txt"
    lst.write_text("".join(f"file '{p.name}'\n" for p in norm))
    joined = WORK / "joined.mp4"
    sh(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(joined)])
    final = WORK / "final.mp4"
    sh(["ffmpeg", "-y", "-i", str(joined), "-i", str(voice), "-vf", f"ass={ass.as_posix()}", "-af", "highpass=f=80,equalizer=f=3000:t=q:w=1:g=3,acompressor=threshold=-20dB:ratio=3:attack=5:release=80,loudnorm=I=-14:TP=-1.5:LRA=7,aresample=44100",
        "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(final)])
    return final


# पूर्वावलोकन (मैं खुद जाँच सकूँ कि दृश्य बोले हुए से मेल खाते हैं) ------------------
def make_preview(final, scenes, durs, meta):
    pdir = pathlib.Path("preview"); pdir.mkdir(exist_ok=True)
    frames, t0 = [], 0.0
    for i, d in enumerate(durs):
        f = WORK / f"pv{i}.jpg"
        sh(["ffmpeg", "-y", "-ss", f"{t0 + d / 2:.2f}", "-i", str(final), "-frames:v", "1", "-vf", "scale=216:-2", str(f)])
        frames.append(f); t0 += d
    cmd = ["ffmpeg", "-y"]
    for f in frames: cmd += ["-i", str(f)]
    cmd += ["-filter_complex", f"hstack={len(frames)}", str(pdir / "latest.jpg")]
    sh(cmd)
    info = {"title": meta["title"], "voice_engine": ENGINE["name"], "footage": SOURCE["name"], "scenes": [
        {"i": i, "dur": round(d, 2), "narration": s["narration"], "caption_en": s.get("caption_en"),
         "query": s.get("query"), "alt": s.get("alt"), "alt2": s.get("alt2")} for i, (s, d) in enumerate(zip(scenes, durs))]}
    (pdir / "latest.json").write_text(json.dumps(info, ensure_ascii=False, indent=1))


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
    try:
        if not (os.getenv("CF_ACCOUNT_ID") and os.getenv("CF_API_TOKEN")): raise RuntimeError("no cloudflare keys")
        meta = ai_images(hist)
    except Exception as e0:
        print("ai-images skipped:", e0); meta = None
    try:
        if meta: pass
        elif not os.getenv("PIXABAY_API_KEY"): raise RuntimeError("no pixabay")
        else:
            for _try in range(3):
                try: meta = footage_first(hist); break
                except AssertionError as e: print("retry:", e)
            if not meta: raise RuntimeError("footage-first retries failed")
    except Exception as e:
        print("footage-first failed, old method:", e)
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
    try: make_preview(final, scenes, durs, meta)
    except Exception as e: print("preview failed:", e)
    if not (DRY or not os.getenv("YT_REFRESH_TOKEN")):
        upload(final, meta)
    else:
        print("अपलोड छोड़ा गया (DRY_RUN या YouTube की key नहीं है). वीडियो Artifacts में मिलेगी।")
    if not DRY:
        hist.append(meta["title"]); HIST.write_text(json.dumps(hist[-200:], ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
