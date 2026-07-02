"""
processor.py — Video processing functions for SDP Shorts Web
Called by main.py background tasks.
"""

import os, json, subprocess, shutil, tempfile, math
from pathlib import Path
from typing import Optional

# Same env var name as main.py's MAX_VIDEO_DURATION_SECONDS so one Railway
# variable controls both the pre-download check here and the post-download
# backstop in process_job. Kept independent (not imported from main) to
# avoid a circular import between the two modules.
MAX_VIDEO_DURATION_SECONDS = int(os.environ.get("MAX_VIDEO_DURATION_SECONDS", 3 * 3600))


class VideoTooLongError(RuntimeError):
    """Raised when a source video exceeds MAX_VIDEO_DURATION_SECONDS. Kept as
    its own type (rather than a plain RuntimeError) so main.py can catch it
    specifically and refund the user's tokens instead of treating it like a
    generic download failure."""
    pass


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

# Shared high-quality encode settings.
# NOTE: previously used CRF (quality-targeted) mode at CRF 18. CRF mode
# deliberately spends FEWER bits on "simple"/low-motion/dark content — great
# for average file size, bad for a clip that's mostly a dark, mostly-static
# shot (e.g. a product unboxing in mood lighting), which is exactly the kind
# of source that was coming out soft/blocky. Measured a real competitor's
# output at ~0.15 bits/pixel/frame vs ours at ~0.01-0.05 on similar dark
# content — a 3-16x gap. Switched to a target-bitrate floor instead, so
# every clip gets a reliable amount of data regardless of how "boring" the
# scene looks to the encoder. Same preset/time cost as before (tested).
ENC_PRESET = "medium"

# Reference point, tuned against real competitor output: 8 Mbps is right for
# a standard 1080x1920 clip. Scaled by pixel count for other resolutions
# (e.g. the 2160x3840 4K tier) so quality stays consistent across tiers
# without blowing up 4K file size/encode time by a full 4x.
_REF_BITRATE = 9_500_000
_REF_PIXELS  = 1080 * 1920

def _target_bitrate_args(w: int, h: int) -> list:
    """
    ffmpeg args for a target-bitrate encode sized to the given output
    resolution. Replaces plain -crf so dark/simple scenes can't get
    starved down to a tiny, blocky bitrate.

    Plain "-b:v X" alone is NOT enough — tested and confirmed that on truly
    low-motion/static footage (a locked-off shot, a mostly-still product
    photo, etc.) libx264's own rate control still quietly undershoots the
    target by itself (a nominal 8 Mbps target came out as low as ~176 kbps
    on a static test clip), because it decides the content doesn't "need"
    the bits. That's the same failure mode as CRF, just less aggressive.
    Forcing near-CBR behavior (minrate == maxrate == target, tight bufsize,
    nal-hrd=cbr) makes the encoder actually spend the full budget every
    time regardless of how simple the scene looks — confirmed via testing
    to hold ~8 Mbps even on a frozen single-frame clip, at the same preset
    speed as before (no timeout risk).
    """
    pixels = max(1, w * h)
    # Sub-linear scale (sqrt of the pixel ratio, not the full ratio) so 4K
    # gets a real step up in quality without a full 4x file-size/time hit.
    scale = (pixels / _REF_PIXELS) ** 0.5
    target = int(_REF_BITRATE * scale)
    target = max(4_000_000, min(target, 24_000_000))  # sane floor/ceiling
    bufsize = max(2_000_000, target // 2)
    return ["-b:v", str(target), "-minrate", str(target), "-maxrate", str(target),
            "-bufsize", str(bufsize), "-x264-params", "nal-hrd=cbr:force-cfr=1"]


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
            # Prefer the highest-res real source available (up to 4K) instead of
            # capping format selection — downstream encode now scales to match
            # whatever comes in, so a better source directly means a crisper clip.
            #
            # NOTE: the old first choice had [ext=mp4] on the video stream.
            # On YouTube that biases toward the AVC (avc1) encodes, which are
            # served at noticeably lower quality-per-pixel than the VP9
            # encodes of the same resolution, and on many videos the mp4
            # ladder simply stops at a lower height. Resolution/quality
            # matters more than container here — merge_output_format=mp4
            # happily muxes VP9 into .mp4, and everything downstream decodes
            # through ffmpeg/OpenCV which handle VP9 fine. AV1 (av01) is
            # excluded: some OpenCV builds can't decode it, and the smart
            # reframe pass reads frames through cv2.VideoCapture.
            "format":  ("bestvideo[vcodec!^=av01][height<=2160]+bestaudio[ext=m4a]/"
                        "bestvideo[vcodec!^=av01][height<=2160]+bestaudio/"
                        "bestvideo[height<=2160]+bestaudio/best"),
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

    # Pre-flight: ask for metadata only (no download) so an oversized video
    # gets rejected in ~1 second instead of after burning bandwidth/disk on
    # a multi-GB 4K download that we'd just throw away anyway. If this probe
    # fails for any reason (bot detection, extractor quirk, non-YouTube URL,
    # etc.) we don't block the job — we just fall through to the real
    # download and let the ffprobe-based check in main.py catch it instead.
    try:
        probe_opts = _base_opts("android", False, False)
        probe_opts["skip_download"] = True
        with yt_dlp.YoutubeDL(probe_opts) as ydl:
            probe_info = ydl.extract_info(url, download=False)
        probe_dur = (probe_info or {}).get("duration", 0) or 0
        if probe_dur > MAX_VIDEO_DURATION_SECONDS:
            raise VideoTooLongError(
                f"Video is {probe_dur/60:.0f} min long — over the "
                f"{MAX_VIDEO_DURATION_SECONDS // 60}-min limit per job. "
                f"Try a shorter video or trim it first.")
        if probe_dur:
            log_fn(f"📏 Pre-flight check: {probe_dur/60:.1f} min — under the limit, continuing")
    except VideoTooLongError:
        raise  # the over-limit case above — stop here, don't download
    except Exception as e:
        log_fn(f"   (pre-flight duration check skipped: {str(e)[:120]})")

    # Strategy ladder — try each in order, stop on first GOOD success.
    # android: no PO token needed, works for public videos — BUT without a
    #   PO token YouTube frequently only serves it the pre-merged 360p
    #   format (18). The old code treated any completed download as success,
    #   so a 360p file sailed through, the 9:16 crop upscaled ~5x, and the
    #   delivered clip looked like mush no matter how good the encoder
    #   settings were (confirmed on a real production job: 16:9 output was
    #   640x360). A download now only counts as success if it's >= 1080p
    #   tall (or we've run out of strategies — a genuinely low-res source
    #   still gets processed rather than failing the whole job).
    # mweb: mobile web, accepts browser cookies — sees the full DASH ladder
    # tv_embedded: embedded TV client, bypasses some restrictions
    strategies = [
        ("android",     True,  False, "android + proxy"),
        ("android",     False, False, "android no-proxy"),
        ("mweb",        True,  True,  "mweb + proxy + cookies"),
        ("mweb",        False, True,  "mweb no-proxy + cookies"),
        ("tv_embedded", True,  True,  "tv_embedded + proxy + cookies"),
        ("tv_embedded", False, True,  "tv_embedded no-proxy + cookies"),
    ]

    MIN_GOOD_HEIGHT = 1080  # below this, keep trying other clients

    def _cleanup_cookies():
        if cookie_file:
            try: os.remove(cookie_file)
            except: pass

    last_err = None
    best_path, best_h = None, -1   # best low-res fallback seen so far
    for client, use_proxy, use_cookies, label in strategies:
        if use_proxy and not proxy:
            continue  # skip proxy strategies if no proxy configured
        if use_cookies and not cookie_file:
            continue  # skip cookie strategies if no cookies configured
        log_fn(f"\U0001F504 Trying: {label}")
        try:
            result = _attempt(_base_opts(client, use_proxy, use_cookies))
            _, got_h = _probe_dims(result)
            if got_h >= MIN_GOOD_HEIGHT:
                log_fn(f"\u2705 Download succeeded via {label} ({got_h}p source)")
                _cleanup_cookies()
                return result
            # Completed, but low-res — likely a client that only got the
            # pre-merged 360p format. Stash it as a fallback and try the
            # next strategy for a real high-res source. The file is moved
            # aside so the next yt-dlp attempt (same outtmpl -> same
            # filename) doesn't see it and skip the download entirely.
            log_fn(f"   \u26A0\uFE0F {label} completed but only {got_h}p — "
                   f"trying next strategy for a higher-res source")
            if got_h > best_h:
                keep = result + ".lowres_keep"
                try:
                    shutil.move(result, keep)
                    if best_path:
                        try: os.remove(best_path)
                        except: pass
                    best_path, best_h = keep, got_h
                except Exception:
                    pass  # if the move fails, worst case we re-download
            else:
                try: os.remove(result)
                except: pass
        except Exception as e:
            msg = str(e)
            log_fn(f"   \u2717 {label} failed: {msg[:150]}")
            last_err = e

    _cleanup_cookies()

    if best_path:
        # Every strategy either failed or came back low-res — use the best
        # low-res file rather than failing the job (the source may simply
        # be an old low-res upload).
        final = best_path[:-len(".lowres_keep")]
        try:
            shutil.move(best_path, final)
        except Exception:
            final = best_path
        log_fn(f"\u26A0\uFE0F No strategy delivered >= {MIN_GOOD_HEIGHT}p — "
               f"using best available source ({best_h}p). "
               f"Output sharpness is limited by this source resolution.")
        return final

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
                      font_size=52, colour="white", flare=True) -> str:
    """
    flare=True adds a quick "pop in + glow pulse" animation to every caption
    chunk: it scales in from ~130% with a heavy blur (glow) and settles to
    100% with a light blur, using the caption's own outline colour as the
    glow colour. Pure ASS override tags — no extra rendering pass needed,
    libass (ffmpeg's built-in ass filter) animates it for free.
    """
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
    # Glow-pop override block prepended to each chunk's text.
    # \fad        quick fade in/out so the pop doesn't hard-cut
    # \t(0,120,…) over the first 120ms: scale 132%→100%, blur 9→1 (glow settles)
    # \t(120,..)  tiny extra blur breathing pulse later in the line's life so it
    #             still feels alive even on longer-held chunks
    glow_tag = (
        f"{{\\fad(70,60)"
        f"\\t(0,120,\\fscx132\\fscy132\\blur9)"
        f"\\t(120,240,\\fscx100\\fscy100\\blur1.2)"
        f"\\t(240,420,\\blur2.4)\\t(420,600,\\blur1)}}"
    ) if flare else ""

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
                    lines.append(f"Dialogue: 0,{_ts(cs)},{_ts(ce)},Default,,0,0,0,,{glow_tag}{' '.join(chunk)}")
                    chunk, cs, ce = [], None, None
            if chunk:
                lines.append(f"Dialogue: 0,{_ts(cs)},{_ts(ce)},Default,,0,0,0,,{glow_tag}{' '.join(chunk)}")
        else:
            wds  = seg.get("text", "").strip().split()
            dur  = re - rs
            step = dur / max(1, math.ceil(len(wds) / MAX_W))
            for i in range(0, len(wds), MAX_W):
                t  = " ".join(wds[i:i+MAX_W])
                cs = rs + (i // MAX_W) * step
                ce = min(re, cs + step)
                lines.append(f"Dialogue: 0,{_ts(cs)},{_ts(ce)},Default,,0,0,0,,{glow_tag}{t}")
    return header + "\n".join(lines) + "\n"


# ══════════════════════════════════════════════════════════════════
#  RESOLUTION HELPERS
# ══════════════════════════════════════════════════════════════════

def _probe_dims(video: str):
    """Return (width, height) of the source video's first video stream."""
    try:
        r = subprocess.run(
            [FFPROBE, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height",
             "-of", "csv=p=0:s=x", video],
            capture_output=True, text=True, timeout=15
        )
        w_s, h_s = r.stdout.strip().split("x")
        return int(w_s), int(h_s)
    except Exception:
        return 1920, 1080  # safe fallback, matches old hardcoded assumption


def _probe_vcodec(video: str) -> str:
    """Return the first video stream's codec name (e.g. 'h264', 'av1', 'vp9')."""
    try:
        r = subprocess.run(
            [FFPROBE, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=codec_name",
             "-of", "csv=p=0", video],
            capture_output=True, text=True, timeout=15
        )
        return r.stdout.strip().lower()
    except Exception:
        return ""


def _adaptive_vertical_dims(src_w: int, src_h: int):
    """
    Pick a clean, standard 9:16 output size — always one of two fixed tiers,
    never an odd in-between resolution like 1216x2160:
      - 4K-class source (short side >= 2160, e.g. a real 3840x2160 download)
        -> true 4K vertical output, 2160x3840. The crop is upscaled from its
        native ~2160-tall slice up to 3840 tall using the same clean Lanczos
        resize + sharpen + single-pass CRF18 encode already used below, so
        the 4K source's extra detail is kept and used, not smashed down to
        a smaller frame.
      - Everything else (1080p and below) -> standard HD vertical output,
        1080x1920, upscaled if needed so it's never delivered tiny/sub-HD
        and pixelated on a phone screen.
    Returns (out_w, out_h).
    """
    short_side = min(src_w, src_h) if src_w and src_h else 1080
    if short_side >= 2160:
        return 2160, 3840
    return 1080, 1920


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

    src_w, src_h = _probe_dims(video)
    out_w, out_h = _adaptive_vertical_dims(src_w, src_h)

    def _run(output: str, vert: bool):
        # When smart_reframe will run afterwards, this pass must NOT crop to
        # 9:16 (smart_reframe needs the full frame to have room to pan) and
        # must NOT burn captions yet (they'd be burned at the wrong aspect —
        # smart_reframe burns them after cropping instead, see below).
        defer_to_reframe = vert and smart_reframe_mode

        ass_path = None
        if ass_content and not defer_to_reframe:
            ass_path = os.path.join(tempfile.gettempdir(),
                                    f"sdp_{_uuid.uuid4().hex[:8]}.ass")
            with open(ass_path, "w", encoding="utf-8") as f:
                f.write(ass_content)

        cmd = [FFMPEG, "-y", "-ss", str(start), "-i", video, "-t", str(dur)]
        vf, af = [], []

        if vert and not defer_to_reframe:
            vf.append(
                f"scale={out_w}:{out_h}:force_original_aspect_ratio=increase:flags=lanczos,"
                f"crop={out_w}:{out_h}"
            )
        # Gentle sharpen — perceptual crispness without halo artifacts.
        # Skipped on the deferred-to-reframe pass: smart_reframe applies its
        # own unsharp AFTER cropping/resizing, which is the only place it
        # actually matters. Sharpening a frame that's about to be re-cropped
        # and re-encoded anyway just adds edge halos that get baked into a
        # second lossy encode for no benefit.
        if not defer_to_reframe:
            vf.append("unsharp=5:5:0.6:5:5:0.0")
        if ass_path:
            safe = ass_path.replace("\\", "/").replace(":", "\\:")
            vf.append(f"ass='{safe}'")
        if vf: cmd += ["-vf", ",".join(vf)]

        if audio_norm:
            af.append("loudnorm=I=-16:TP=-1.5:LRA=11")
        if af: cmd += ["-af", ",".join(af)]

        if defer_to_reframe:
            # This pass only needs to hand smart_reframe an exact trim of
            # the source. Ideally that's a lossless stream copy — every
            # full H.264 encode throws away detail permanently, so encoding
            # here AND AGAIN in smart_reframe's final pass was double
            # generation loss for no reason (no crop/scale/captions happen
            # in this pass, so there's nothing that actually needs a
            # re-encode).
            #
            # BUT: smart_reframe's face-detection pass reads this file with
            # OpenCV, and OpenCV's video reader can silently fail to decode
            # some codecs — confirmed via testing that it reports the file
            # as "opened" successfully but then returns ZERO frames for an
            # AV1-encoded video. AV1 is exactly the codec YouTube serves
            # for real 4K/1440p downloads (their high-res H.264 track
            # tops out at 1080p), so a real 4K source would silently break
            # Smart Reframe entirely under a naive stream-copy — it'd not
            # crop to vertical at all. The old code accidentally dodged
            # this because its full re-encode transcoded everything to
            # H.264 before OpenCV ever saw it.
            #
            # So: copy the video track only when it's already a codec
            # OpenCV can read (h264); otherwise transcode to H.264 at very
            # high quality (this is a hand-off intermediate, not the
            # delivered file, so we don't need our normal delivery bitrate
            # here — just enough that smart_reframe's real final encode
            # isn't starting from a second lossy generation).
            src_vcodec = _probe_vcodec(video)
            if src_vcodec in ("h264", "avc1"):
                cmd += ["-c:v", "copy", "-c:a", "aac", "-b:a", "128k", output]
            else:
                cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "12",
                        "-c:a", "aac", "-b:a", "128k", output]
        else:
            # Bitrate target matches whatever resolution this pass actually
            # outputs: the cropped out_w/out_h when we scale+crop to vertical,
            # otherwise the untouched source resolution (horizontal pass).
            if vert:
                br_args = _target_bitrate_args(out_w, out_h)
            else:
                br_args = _target_bitrate_args(src_w, src_h)

            cmd += ["-c:v", "libx264", "-threads", "4", "-preset", ENC_PRESET,
                    *br_args, "-c:a", "aac", "-b:a", "128k", output]
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


def generate_thumbnail(video_path: str, thumb_path: str, log_fn=lambda m: None) -> bool:
    """
    Grab one representative frame from a finished clip and save it as a
    small JPG for the results-page grid (thumbnail card view). Pulled from
    ~15% into the clip rather than frame 0 — the very first frame is
    disproportionately likely to be a black/transition frame, which makes
    for a useless-looking blank thumbnail card. Returns True on success;
    failures are non-fatal (results page just falls back to no image),
    logged but never raise, since a missing thumbnail should never break
    an otherwise-successful clip.
    """
    try:
        dur = 0.0
        try:
            r = subprocess.run(
                [FFPROBE, "-v", "error", "-show_entries", "format=duration",
                 "-of", "csv=p=0", video_path],
                capture_output=True, text=True, timeout=15
            )
            dur = float(r.stdout.strip() or 0)
        except Exception:
            pass
        offset = max(0.1, min(dur * 0.15, dur - 0.1)) if dur > 0.2 else 0.1

        cmd = [FFMPEG, "-y", "-ss", str(offset), "-i", video_path,
               "-frames:v", "1", "-vf", "scale=480:-2",
               "-q:v", "4", thumb_path]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if r.returncode != 0 or not os.path.exists(thumb_path):
            log_fn(f"   ⚠️  Thumbnail generation failed: {r.stderr[-200:]}")
            return False
        return True
    except Exception as e:
        log_fn(f"   ⚠️  Thumbnail generation error: {e}")
        return False


# ══════════════════════════════════════════════════════════════════
#  SMART REFRAME
# ══════════════════════════════════════════════════════════════════

def smart_reframe(input_path: str, output_path: str,
                  smoothness: float, log_fn,
                  ass_content: Optional[str] = None):
    """
    Two-pass smooth reframe:
      Pass 1 — detect face centre-x for every frame, reject outliers, fill
               gaps, Gaussian-smooth.
      Pass 2 — RE-READ the source from disk a second time and render each
               frame using the pre-computed smooth crop position.
    Captions (if provided) are burned in AFTER cropping, at the final
    output resolution, so their coordinate space actually matches the frame.

    IMPORTANT: frames are never held in memory across passes. The old
    version stored every decoded full-resolution frame in a Python list
    (frames.append(frame)) so it could reuse them in pass 2 — for a 4K clip
    that's gigabytes of raw frames, and on a memory-limited server the
    process gets killed mid-write, leaving a truncated/corrupt output file
    (no moov atom — unplayable, "Unknown" format in any player). Re-reading
    the file from disk in pass 2 instead keeps memory flat regardless of
    resolution or clip length.
    """
    import cv2
    import numpy as np

    cap    = cv2.VideoCapture(input_path)
    fps    = cap.get(cv2.CAP_PROP_FPS) or 30.0
    w      = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h      = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    OUT_W, OUT_H = _adaptive_vertical_dims(w, h)
    crop_w = min(w, int(h * OUT_W / OUT_H))

    # Frontal cascade catches straight-on faces reliably, but this
    # speaker (like most real talking-head footage) constantly turns to
    # a 3/4 or side angle — frontal-only tracking loses him for long
    # stretches when that happens, and the crop then drifts/settles on
    # empty background (confirmed: reproduced on real footage, ~8s of a
    # 30s clip lost the subject entirely). Profile cascade (run on the
    # frame and its horizontal mirror, since it's only trained for one
    # facing direction) catches the turned-head case frontal misses.
    cascade_front = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    cascade_profile = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_profileface.xml")

    def _valid_shape(fw, fh):
        # Real faces are roughly square in aspect ratio. Patterned
        # backgrounds (lattice curtains, grid textures) regularly trigger
        # false-positive "faces" in these cascades that are oddly
        # elongated — this rejects those without needing a heavier model.
        if fh == 0:
            return False
        ar = fw / float(fh)
        return 0.7 <= ar <= 1.4

    def _skin_ratio(bgr_small, fx, fy, fw, fh):
        # The decisive filter. Confirmed on real footage: a patterned
        # curtain triggered a rock-stable false-positive "face" detection
        # (same box, frame after frame — not a one-off, so the existing
        # jump-outlier rejection never caught it), and because it was the
        # LARGEST box detected each frame it won "pick the biggest face"
        # and hijacked the crop, panning fully off the actual person for
        # a long stretch. Its skin-tone pixel ratio measured 0.0 versus
        # 0.47 for a real face box on the same footage — background
        # patterns essentially never have real skin-tone color content,
        # so this cheaply and reliably tells a real face from a textured
        # false positive regardless of size or shape.
        region = bgr_small[max(0, fy):fy + fh, max(0, fx):fx + fw]
        if region.size == 0:
            return 0.0
        hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
        Hc, Sc, Vc = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
        mask = ((Hc < 25) | (Hc > 165)) & (Sc > 30) & (Sc < 180) & (Vc > 50)
        return float(mask.mean())

    SKIN_MIN = 0.15

    def _detect_faces(bgr_small, gray):
        candidates = []
        for (fx, fy, fw, fh) in cascade_front.detectMultiScale(gray, 1.1, 5, minSize=(25, 25)):
            if _valid_shape(fw, fh) and _skin_ratio(bgr_small, fx, fy, fw, fh) >= SKIN_MIN:
                candidates.append((fx, fy, fw, fh))
        for (fx, fy, fw, fh) in cascade_profile.detectMultiScale(gray, 1.1, 5, minSize=(25, 25)):
            if _valid_shape(fw, fh) and _skin_ratio(bgr_small, fx, fy, fw, fh) >= SKIN_MIN:
                candidates.append((fx, fy, fw, fh))
        flipped_gray = cv2.flip(gray, 1)
        flipped_bgr = cv2.flip(bgr_small, 1)
        gw = gray.shape[1]
        for (fx, fy, fw, fh) in cascade_profile.detectMultiScale(flipped_gray, 1.1, 5, minSize=(25, 25)):
            if _valid_shape(fw, fh) and _skin_ratio(flipped_bgr, fx, fy, fw, fh) >= SKIN_MIN:
                candidates.append((gw - fx - fw, fy, fw, fh))
        return candidates

    # ── PASS 1: collect raw face cx per frame. Each frame is discarded
    #    right after detection — only the tiny per-frame number survives,
    #    so this stays cheap on memory no matter how long/high-res the
    #    clip is. ──────────────────────────────────────────────────────
    log_fn("   🎯 Reframe pass 1: scanning faces…")
    cx_raw = []
    n = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        n += 1
        scale = 640 / w
        small = cv2.resize(frame, (640, int(h * scale)))
        gray  = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        faces = _detect_faces(small, gray)
        if len(faces):
            # Pick the LARGEST face (closest/most prominent), not just the
            # first one OpenCV happens to return — fixes the camera randomly
            # snapping to a smaller background face.
            fx, fy, fw, fh = max(faces, key=lambda f: f[2] * f[3])
            cx_raw.append((fx + fw / 2) / scale)
        else:
            cx_raw.append(None)
    cap.release()

    if n == 0:
        log_fn("   ⚠️  No frames to reframe")
        return

    tracked = sum(1 for c in cx_raw if c is not None)
    log_fn(f"   🎯 Face detected in {tracked}/{n} frames")

    # ── Outlier rejection: a single detection that jumps far from its
    #    neighbours is almost always a false positive, not a real cut to a
    #    new face position — drop it and let interpolation fill the gap. ───
    MAX_JUMP = w * 0.22  # ~1/5th of frame width in one frame is not a real face move
    cleaned = list(cx_raw)
    for i in range(n):
        v = cleaned[i]
        if v is None:
            continue
        neighbours = [cleaned[j] for j in range(max(0, i - 4), min(n, i + 5))
                      if j != i and cleaned[j] is not None]
        if not neighbours:
            continue
        med = float(np.median(neighbours))
        if abs(v - med) > MAX_JUMP:
            cleaned[i] = None
    cx_raw = cleaned

    # ── Fill gaps ──────────────────────────────────────────────────
    # Short gaps (a blink, a quick head turn the cascades missed for a
    # few frames) are safe to bridge with a straight linear slide — the
    # face almost certainly moved smoothly between the two known points.
    # Long gaps are a different situation: they mean tracking lost the
    # subject for a real stretch of time, and the next "known" point
    # might itself be a false detection somewhere in the background
    # (confirmed on real footage: a lost stretch interpolated straight
    # into an empty doorway because the anchor on the far side of the
    # gap wasn't trustworthy). For those, hold the last confidently
    # tracked position instead of sliding toward a shaky anchor — a
    # locked-off frame reads as intentional; a pan into empty
    # background reads as broken.
    default_cx = float(w) / 2
    known = [(i, v) for i, v in enumerate(cx_raw) if v is not None]
    LONG_GAP = int(fps * 1.5)  # gaps over 1.5s hold instead of sliding
    if not known:
        cx_filled = [default_cx] * n
    else:
        kx = [i for i, _ in known]
        ky = [v for _, v in known]
        if kx[0] > 0:
            kx.insert(0, 0);     ky.insert(0, ky[0])
        if kx[-1] < n - 1:
            kx.append(n - 1);    ky.append(ky[-1])
        cx_filled = list(np.interp(range(n), kx, ky))
        for a, b in zip(range(len(kx) - 1), range(1, len(kx))):
            i0, i1 = kx[a], kx[b]
            if i1 - i0 > LONG_GAP:
                for i in range(i0, i1):
                    cx_filled[i] = ky[a]

    # ── Gaussian smooth across the whole timeline ─────────────────
    # smoothness 0→1 maps window 15→90 frames (higher = lazier/smoother pan)
    win = max(15, int(smoothness * 75 + 15))
    if win % 2 == 0:
        win += 1
    kernel = cv2.getGaussianKernel(win, win / 3.0).flatten()
    pad    = win // 2
    padded = np.pad(cx_filled, pad, mode="reflect")
    cx_smooth = np.convolve(padded, kernel, mode="valid")[:n]

    # ── PASS 2: re-open the source from disk and render with the smoothed
    #    crop positions, streaming straight into ffmpeg over a pipe. Never
    #    more than one decoded frame is in memory at a time. ─────────────
    log_fn(f"   🎯 Reframe pass 2: rendering @ {OUT_W}x{OUT_H}…")

    ass_path = None
    vf = ["unsharp=5:5:0.6:5:5:0.0"]
    if ass_content:
        import uuid as _uuid
        ass_path = os.path.join(tempfile.gettempdir(), f"sdp_{_uuid.uuid4().hex[:8]}.ass")
        with open(ass_path, "w", encoding="utf-8") as f:
            f.write(ass_content)
        safe = ass_path.replace("\\", "/").replace(":", "\\:")
        vf.append(f"ass='{safe}'")

    cmd = [FFMPEG, "-y",
           "-f", "rawvideo", "-pix_fmt", "bgr24",
           "-s", f"{OUT_W}x{OUT_H}", "-r", str(fps), "-i", "-",
           "-i", input_path,
           "-map", "0:v:0", "-map", "1:a:0?",
           "-vf", ",".join(vf),
           "-c:v", "libx264", "-preset", ENC_PRESET, *_target_bitrate_args(OUT_W, OUT_H),
           # Force standard yuv420p output. Without this, piping raw BGR
           # frames into libx264 makes it default to a yuv444p "High 4:4:4"
           # profile (confirmed via ffprobe) instead of the normal yuv420p
           # every other clip uses — yuv444p isn't reliably playable on
           # phones, many hardware decoders, or social platforms, so a
           # reframed clip could look/behave worse than a non-reframed one
           # even though this pass already does a clean single-encode.
           "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "128k", output_path]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    half = crop_w / 2
    cap2 = cv2.VideoCapture(input_path)
    write_err = None
    try:
        i = 0
        while i < n:
            ret, frame = cap2.read()
            if not ret:
                break
            x1 = int(max(0, min(w - crop_w, cx_smooth[i] - half)))
            cropped = frame[:, x1:x1 + crop_w]
            resized = cv2.resize(cropped, (OUT_W, OUT_H),
                                  interpolation=cv2.INTER_LANCZOS4)
            proc.stdin.write(resized.tobytes())
            i += 1
    except Exception as e:
        # Don't close stdin ourselves here — let communicate() below do it.
        # Manually closing it first and THEN calling communicate() raises
        # "ValueError: flush of closed file" on every run (reproduced and
        # confirmed) and abandons the ffmpeg process without ever waiting
        # for it, which is the actual bug behind broken/unplayable clips:
        # the exception always fired, so Smart Reframe silently "failed"
        # on every single job and the renamed temp file was left orphaned.
        write_err = e
    finally:
        cap2.release()

    # communicate() (with no manual close beforehand) safely closes stdin
    # and drains stdout/stderr concurrently while waiting for ffmpeg to
    # actually finish and finalize the file (write the moov atom).
    _, stderr = proc.communicate()
    if ass_path:
        try: os.remove(ass_path)
        except: pass
    if write_err is not None:
        raise RuntimeError(f"reframe: frame write failed: {write_err}") from write_err
    if proc.returncode != 0:
        raise RuntimeError(f"reframe: {stderr.decode(errors='ignore')[-300:]}")



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
    cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml")

    # Stream blurred frames straight into ffmpeg over a pipe instead of an
    # OpenCV (mp4v) intermediate file — same double-compression issue as
    # smart_reframe, fixed the same way.
    cmd = [FFMPEG, "-y",
           "-f", "rawvideo", "-pix_fmt", "bgr24",
           "-s", f"{W}x{H}", "-r", str(fps), "-i", "-",
           "-i", input_path,
           "-map", "0:v:0", "-map", "1:a:0?",
           "-c:v", "libx264", "-threads", "4", "-preset", ENC_PRESET, *_target_bitrate_args(W, H),
           # Same fix as smart_reframe: force yuv420p so a face-blurred clip
           # doesn't silently end up in the less-compatible yuv444p profile.
           "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "128k", output_path]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    blurred = 0
    write_err = None
    try:
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
            proc.stdin.write(frame.tobytes())
    except Exception as e:
        # Same fix as smart_reframe: don't close stdin ourselves and then
        # call communicate() — that raises "ValueError: flush of closed
        # file" on every run and abandons the ffmpeg process without
        # waiting for it, which silently broke this feature the same way.
        write_err = e
    finally:
        cap.release()

    _, stderr = proc.communicate()
    log_fn(f"   👁️  Blurred {blurred} face instances")
    if write_err is not None:
        raise RuntimeError(f"blur: frame write failed: {write_err}") from write_err
    if proc.returncode != 0:
        raise RuntimeError(f"blur: {stderr.decode(errors='ignore')[-300:]}")
