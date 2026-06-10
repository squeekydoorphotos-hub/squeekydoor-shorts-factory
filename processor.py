"""
processor.py — Video processing functions for SDP Shorts Web
Called by main.py background tasks.
"""

import os, json, subprocess, shutil, tempfile, math
from pathlib import Path
from typing import Optional


def _find_bin(name: str) -> str:
    """Find a binary in common locations including nix store."""
    import shutil as _shutil
    # Check PATH first
    found = _shutil.which(name)
    if found:
        return found
    # Common nix/Railway paths
    candidates = [
        f"/nix/var/nix/profiles/default/bin/{name}",
        f"/root/.nix-profile/bin/{name}",
        f"/usr/local/bin/{name}",
        f"/usr/bin/{name}",
        f"/bin/{name}",
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    # Last resort: search nix store
    try:
        r = subprocess.run(["find", "/nix/store", "-name", name, "-type", "f"],
                           capture_output=True, text=True, timeout=10)
        hits = [l for l in r.stdout.strip().split("\n") if l and "/bin/" in l]
        if hits:
            return hits[0]
    except:
        pass
    return name  # Fall back to name and let it fail with a clear error


FFMPEG  = _find_bin("ffmpeg")
FFPROBE = _find_bin("ffprobe")


# ══════════════════════════════════════════════════════════════════
#  DOWNLOAD
# ══════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════
#  FALLBACK DOWNLOADERS
# ══════════════════════════════════════════════════════════════════

def _extract_video_id(url: str) -> str:
    import re as _re
    m = _re.search(r"(?:v=|youtu\.be/|embed/|shorts/)([A-Za-z0-9_-]{11})", url)
    return m.group(1) if m else ""





def download_video(url: str, out_dir: str, log_fn) -> str:
    import yt_dlp

    def _hook(d):
        if d.get("status") == "downloading":
            pct = d.get("_percent_str", "").strip()
            if pct: log_fn(f"  ⬇️  {pct}")
        elif d.get("status") == "finished":
            log_fn(f"  ✅ {Path(d['filename']).name}")

    # Find YouTube cookies — prefer file on persistent volume over env var
    cookie_file = None
    _cookies_owned = False  # True if we created a temp file we must delete
    # Derive cookies path from DB_PATH (same dir = persistent volume)
    _db_path = os.environ.get("DB_PATH", "/tmp/sdp_shorts.db")
    _vol_cookies = str(Path(_db_path).parent / "yt_cookies.txt")
    if Path(_vol_cookies).exists():
        cookie_file = _vol_cookies
        log_fn(f"🍪 Using YouTube cookies from volume ({Path(_vol_cookies).stat().st_size // 1024}KB)")
    else:
        yt_cookies = os.environ.get("YOUTUBE_COOKIES", "").strip()
        if yt_cookies:
            import tempfile as _tf
            cf = _tf.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
            cf.write(yt_cookies)
            cf.close()
            cookie_file = cf.name
            _cookies_owned = True
            log_fn(f"🍪 Using YouTube cookies from env var ({len(yt_cookies.splitlines())} lines)")

    proxy = os.environ.get("DOWNLOAD_PROXY", "").strip()
    if proxy:
        log_fn(f"🌐 Using proxy: {proxy[:30]}...")

    # Resolve ffmpeg at runtime
    ffmpeg_path = FFMPEG
    if not os.path.isfile(ffmpeg_path):
        ffmpeg_path = _find_bin("ffmpeg")
    if not os.path.isfile(ffmpeg_path):
        try:
            r = subprocess.run(
                ["find", "/nix/store", "-name", "ffmpeg", "-type", "f"],
                capture_output=True, text=True, timeout=15
            )
            hits = [l for l in r.stdout.strip().split("\n") if l and "/bin/" in l]
            if hits:
                ffmpeg_path = hits[0]
        except Exception:
            pass
    ffmpeg_dir = os.path.dirname(ffmpeg_path) if os.path.isfile(ffmpeg_path) else ""
    log_fn(f"🔧 ffmpeg: {ffmpeg_path or 'not found'}")
    log_fn(f"🔧 PATH: {os.environ.get('PATH','(unset)')[:120]}")

    log_fn(f"🔢 yt-dlp version: {yt_dlp.version.__version__}")

    def _base_opts(client: str, use_proxy: bool, use_cookies: bool) -> dict:
        o = {
            "outtmpl": str(Path(out_dir) / "%(title).60s.%(ext)s"),
            "format":  "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best",
            "merge_output_format": "mp4",
            "quiet": True, "no_warnings": True,
            "progress_hooks": [_hook],
            "extractor_args": {"youtube": {"player_client": [client]}},
            "socket_timeout": 60,
            "retries": 3,
            "fragment_retries": 3,
        }
        if ffmpeg_dir:
            o["ffmpeg_location"] = ffmpeg_dir
        if use_proxy and proxy:
            o["proxy"] = proxy
        if use_cookies and cookie_file:
            o["cookiefile"] = cookie_file
        return o

    def _attempt(opts):
        with yt_dlp.YoutubeDL(opts) as ydl:
            info  = ydl.extract_info(url, download=True)
            fname = ydl.prepare_filename(info)
            if not os.path.exists(fname):
                fname = str(Path(fname).with_suffix(".mp4"))
            dur = info.get("duration", 0) or 0
            try:
                with open(str(Path(fname).with_suffix(".duration")), "w") as f:
                    f.write(str(dur))
            except:
                pass
            return fname

    # Strategy ladder — try each in order, stop on first success
    # android: no PO token needed, works for public videos, uses DASH (high quality)
    # mweb: mobile web, accepts browser cookies
    # tv_embedded: embedded TV client, bypasses some restrictions
    strategies = [
        ("android",     True,  False, "android + proxy"),
        ("android",     False, False, "android no-proxy"),
        ("mweb",        True,  True,  "mweb + proxy + cookies"),
        ("mweb",        False, True,  "mweb no-proxy + cookies"),
        ("tv_embedded", True,  True,  "tv_embedded + proxy + cookies"),
        ("tv_embedded", False, True,  "tv_embedded no-proxy + cookies"),
    ]

    last_err = None
    for client, use_proxy, use_cookies, label in strategies:
        if use_proxy and not proxy:
            continue  # skip proxy strategies if no proxy configured
        if use_cookies and not cookie_file:
            continue  # skip cookie strategies if no cookies configured
        log_fn(f"🔄 Trying: {label}")
        try:
            result = _attempt(_base_opts(client, use_proxy, use_cookies))
            log_fn(f"✅ Download succeeded via {label}")
            if cookie_file:
                try: os.remove(cookie_file)
                except: pass
            return result
        except Exception as e:
            msg = str(e)
            log_fn(f"   ✗ {label} failed: {msg[:150]}")
            last_err = e

    if cookie_file:
        try: os.remove(cookie_file)
        except: pass
    raise RuntimeError(f"All download strategies failed. Last error: {str(last_err)[:300]}")


# ══════════════════════════════════════════════════════════════════
#  CLIP PICKING
# ══════════════════════════════════════════════════════════════════

def pick_clips_claude(segments, count, clip_len, api_key, log_fn):
    import anthropic
    text = "\n".join(f"[{s['start']:.1f}s] {s.get('text','').strip()}"
                     for s in segments if s.get("text","").strip())
    if not text: return []
    if len(text) > 20000: text = text[:20000] + "\n…"

    VIRALITY_TAGS = [
        "Strong Hook", "Emotional Peak", "Laugh Moment", "Shocking Reveal",
        "Tutorial Gold", "Controversial Take", "Relatable Story", "Hype Moment",
        "Mic Drop", "Cliffhanger"
    ]
    prompt = (
        f"You are a viral content expert. Analyze this transcript and find the {count} best "
        f"short-form video moments (~{clip_len}s each).\n\n"
        f"TRANSCRIPT:\n{text}\n\n"
        f"Return ONLY a JSON array with exactly {count} objects. Each object:\n"
        f'[{{\n"start": <float seconds>,\n"end": <float seconds>,\n"reason": "<why this moment works>",\n"hook": "<viral social media title, 8-12 words, attention-grabbing, specific to this moment, no generic phrases>",\n"virality_score": <int 0-100>,\n"virality_tag": "<one of: {", ".join(VIRALITY_TAGS)}>"\n}}]\n\n'
        f"virality_score rules:\n"
        f"- 85-100: Exceptional — strong emotion, controversy, or instant hook\n"
        f"- 70-84: Great — clear value, funny, or relatable\n"
        f"- 55-69: Good — solid content but missing a strong hook\n"
        f"- Below 55: Only use if no better options\n"
        f"Sort by virality_score descending. Return ONLY JSON, no other text."
    )
    client = anthropic.Anthropic(api_key=api_key)
    resp   = client.messages.create(model="claude-sonnet-4-6",
                                     max_tokens=4096,
                                     messages=[{"role":"user","content":prompt}])
    raw = resp.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"): raw = raw[4:]
    clips = json.loads(raw.strip())
    log_fn(f"✅ Claude picked {len(clips)} clips")
    return clips


def pick_clips_evenly(count: int, clip_len: int, duration: float) -> list:
    step = max(duration / (count + 1), clip_len + 5)
    clips = []
    for i in range(count):
        s = max(0, min(step * (i + 1) - clip_len / 2, duration - clip_len))
        clips.append({"start": s, "end": s + clip_len,
                      "reason": "Evenly spaced", "hook": f"Clip {i+1}"})
    return clips


# ══════════════════════════════════════════════════════════════════
#  SUBTITLES  (.ass)
# ══════════════════════════════════════════════════════════════════

def _ts(sec: float) -> str:
    h = int(sec // 3600); m = int((sec % 3600) // 60); s = sec % 60
    return f"{h}:{m:02d}:{s:05.2f}"


COLOUR_MAP = {
    "white":   ("&H00FFFFFF", "&H00000000"),
    "yellow":  ("&H0000FFFF", "&H00000000"),
    "emerald": ("&H0088FF00", "&H00000000"),
    "gold":    ("&H0000D7FF", "&H00000000"),
    "red":     ("&H000000FF", "&H00000000"),
    "cyan":    ("&H00FFFF00", "&H00000000"),
}


def build_ass_content(segments, clip_start, clip_end, vertical,
                      font_family="Arial", font_file=None,
                      font_size=52, colour="white") -> str:
    tc, oc = COLOUR_MAP.get(colour, COLOUR_MAP["white"])
    rx, ry = (1080, 1920) if vertical else (1920, 1080)
    mv     = 80 if vertical else 60

    header = f"""[Script Info]
ScriptType: v4.00+
WrapStyle: 0
PlayResX: {rx}
PlayResY: {ry}

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Default,{font_family},{font_size},{tc},&H000000FF,{oc},&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,20,20,{mv},1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    MAX_W = 6
    lines = []
    for seg in segments:
        ss, se = float(seg.get("start", 0)), float(seg.get("end", 0))
        if se < clip_start or ss > clip_end: continue
        rs = max(0, ss - clip_start)
        re = min(clip_end - clip_start, se - clip_start)
        words = seg.get("words", [])
        if words:
            chunk, cs, ce = [], None, None
            for w in words:
                ws = float(w.get("start", ss)) - clip_start
                we = float(w.get("end", se))   - clip_start
                if ws < 0 or we > clip_end - clip_start: continue
                if cs is None: cs = ws
                chunk.append(w.get("word", "").strip()); ce = we
                if len(chunk) >= MAX_W:
                    lines.append(f"Dialogue: 0,{_ts(cs)},{_ts(ce)},Default,,0,0,0,,{' '.join(chunk)}")
                    chunk, cs, ce = [], None, None
            if chunk:
                lines.append(f"Dialogue: 0,{_ts(cs)},{_ts(ce)},Default,,0,0,0,,{' '.join(chunk)}")
        else:
            wds  = seg.get("text", "").strip().split()
            dur  = re - rs
            step = dur / max(1, math.ceil(len(wds) / MAX_W))
            for i in range(0, len(wds), MAX_W):
                t  = " ".join(wds[i:i+MAX_W])
                cs = rs + (i // MAX_W) * step
                ce = min(re, cs + step)
                lines.append(f"Dialogue: 0,{_ts(cs)},{_ts(ce)},Default,,0,0,0,,{t}")
    return header + "\n".join(lines) + "\n"


# ══════════════════════════════════════════════════════════════════
#  CLIP EXTRACTION
# ═════════════════════════════════════════════════════════════════

def extract_clip(video: str, start: float, end: float, out_path: str,
                 vertical: bool, both: bool,
                 ass_content: Optional[str],
                 audio_norm: bool,
                 log_fn,
                 smart_reframe_mode: bool = False) -> list:
    """
    Extract clip(s). Returns list of output file paths created.
    """
    import uuid as _uuid
    dur  = end - start
    base, ext = os.path.splitext(out_path)
    created  = []

    def _run(output: str, vert: bool):
        ass_path = None
        if ass_content:
            ass_path = os.path.join(tempfile.gettempdir(),
                                    f"sdp_{_uuid.uuid4().hex[:8]}.ass")
            with open(ass_path, "w", encoding="utf-8") as f:
                f.write(ass_content)

        cmd = [FFMPEG, "-y", "-ss", str(start), "-i", video, "-t", str(dur)]
        vf, af = [], []

        if vert and not smart_reframe_mode:
            vf.append("scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920")
        if ass_path:
            safe = ass_path.replace("\\", "/").replace(":", "\\:")
            vf.append(f"ass='{safe}'")
        if vf: cmd += ["-vf", ",".join(vf)]

        if audio_norm:
            af.append("loudnorm=I=-16:TP=-1.5:LRA=11")
        if af: cmd += ["-af", ",".join(af)]

        cmd += ["-c:v", "libx264", "-threads", "4", "-preset", "fast", "-crf", "22",
                "-c:a", "aac", "-b:a", "128k", output]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if ass_path:
            try: os.remove(ass_path)
            except: pass
        if r.returncode != 0:
            raise RuntimeError(f"ffmpeg error:\n{r.stderr[-800:]}")
        created.append(output)

    if both:
        _run(base + "_16x9" + ext, False)
        _run(base + "_9x16" + ext, True)
    elif vertical:
        _run(out_path, True)
    else:
        _run(out_path, False)

    return created


# ══════════════════════════════════════════════════════════════════
#  SMART REFRAME
# ══════════════════════════════════════════════════════════════════

def smart_reframe(input_path: str, output_path: str,
                  smoothness: float, log_fn):
    """
    Two-pass smooth reframe:
      Pass 1 — detect face centre-x for every frame, fill gaps, Gaussian-smooth.
      Pass 2 — render each frame using the pre-computed smooth crop position.
    Eliminates jitter caused by frame-by-frame EMA.
    """
    import cv2
    import numpy as np

    cap    = cv2.VideoCapture(input_path)
    fps    = cap.get(cv2.CAP_PROP_FPS) or 30.0
    w      = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h      = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    crop_w = min(w, int(h * 9 / 16))
    OUT_W, OUT_H = 1080, 1920

    cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml")

    # ── PASS 1: collect raw face cx per frame ─────────────────────
    log_fn("   🎯 Reframe pass 1: scanning faces…")
    cx_raw, frames = [], []
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        frames.append(frame)
        scale = 640 / w
        small = cv2.resize(frame, (640, int(h * scale)))
        gray  = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        faces = cascade.detectMultiScale(gray, 1.1, 4, minSize=(25, 25))
        if len(faces):
            fx, fy, fw, fh = faces[0]
            cx_raw.append((fx + fw / 2) / scale)
        else:
            cx_raw.append(None)
    cap.release()

    n = len(frames)
    if n == 0:
        log_fn("   ⚠️  No frames to reframe")
        return

    tracked = sum(1 for c in cx_raw if c is not None)
    log_fn(f"   🎯 Face detected in {tracked}/{n} frames")

    # ── Fill gaps via linear interpolation ────────────────────────
    default_cx = float(w) / 2
    known = [(i, v) for i, v in enumerate(cx_raw) if v is not None]
    if not known:
        cx_filled = [default_cx] * n
    else:
        kx = [i for i, _ in known]
        ky = [v for _, v in known]
        # Extend sentinels so every frame is covered
        if kx[0] > 0:
            kx.insert(0, 0);     ky.insert(0, ky[0])
        if kx[-1] < n - 1:
            kx.append(n - 1);    ky.append(ky[-1])
        cx_filled = list(np.interp(range(n), kx, ky))

    # ── Gaussian smooth across the whole timeline ─────────────────
    # smoothness 0→1 maps window 15→90 frames (higher = lazier/smoother pan)
    win = max(15, int(smoothness * 75 + 15))
    if win % 2 == 0:
        win += 1
    kernel = cv2.getGaussianKernel(win, win / 3.0).flatten()
    pad    = win // 2
    padded = np.pad(cx_filled, pad, mode="reflect")
    cx_smooth = np.convolve(padded, kernel, mode="valid")[:n]

    # ── PASS 2: render with smoothed crop positions ───────────────
    log_fn("   🎯 Reframe pass 2: rendering…")
    tmp    = input_path + "_rf_raw.mp4"
    writer = cv2.VideoWriter(tmp, cv2.VideoWriter_fourcc(*"mp4v"),
                              fps, (OUT_W, OUT_H))
    half = crop_w / 2
    for i, frame in enumerate(frames):
        x1 = int(max(0, min(w - crop_w, cx_smooth[i] - half)))
        cropped = frame[:, x1:x1 + crop_w]
        writer.write(cv2.resize(cropped, (OUT_W, OUT_H),
                                 interpolation=cv2.INTER_LINEAR))
    writer.release()

    cmd = [FFMPEG, "-y", "-i", tmp, "-i", input_path,
           "-map", "0:v:0", "-map", "1:a:0?",
           "-c:v", "libx264", "-preset", "fast", "-crf", "22",
           "-c:a", "aac", "-b:a", "128k", output_path]
    r = subprocess.run(cmd, capture_output=True, text=True)
    try: os.remove(tmp)
    except: pass
    if r.returncode != 0:
        raise RuntimeError(f"reframe: {r.stderr[-300:]}")



# ══════════════════════════════════════════════════════════════════
#  FACE BLUR
# ══════════════════════════════════════════════════════════════════

def blur_faces_opencv(input_path: str, output_path: str,
                      strength: int, log_fn):
    import cv2

    cap    = cv2.VideoCapture(input_path)
    fps    = cap.get(cv2.CAP_PROP_FPS) or 30.0
    W      = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H      = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total  = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    kernel = max(3, int(strength * 18) | 1)
    tmp    = input_path + "_bl_raw.mp4"
    writer = cv2.VideoWriter(tmp, cv2.VideoWriter_fourcc(*"mp4v"), fps, (W, H))
    cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml")

    blurred = 0
    while True:
        ret, frame = cap.read()
        if not ret: break
        scale = 640 / W; dh = int(H * scale)
        small = cv2.resize(frame, (640, dh))
        gray  = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        faces = cascade.detectMultiScale(gray, 1.1, 4, minSize=(20, 20))
        if len(faces):
            PAD = 0.15
            for (fx, fy, fw, fh) in faces:
                x1 = max(0, int((fx - fw*PAD) / scale))
                y1 = max(0, int((fy - fh*PAD) / scale))
                x2 = min(W, int((fx + fw*(1+PAD)) / scale))
                y2 = min(H, int((fy + fh*(1+PAD)) / scale))
                roi = frame[y1:y2, x1:x2]
                if roi.size:
                    frame[y1:y2, x1:x2] = cv2.GaussianBlur(roi, (kernel, kernel), 0)
                    blurred += 1
        writer.write(frame)

    cap.release(); writer.release()
    log_fn(f"   👁️  Blurred {blurred} face instances")

    cmd = [FFMPEG, "-y", "-i", tmp, "-i", input_path,
           "-map", "0:v:0", "-map", "1:a:0?",
           "-c:v", "libx264", "-threads", "4", "-preset", "fast", "-crf", "22",
           "-c:a", "aac", "-b:a", "128k", output_path]
    r = subprocess.run(cmd, capture_output=True, text=True)
    try: os.remove(tmp)
    except: pass
    if r.returncode != 0:
        raise RuntimeError(f"blur: {r.stderr[-300:]}")
