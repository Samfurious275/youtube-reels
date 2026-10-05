#!/usr/bin/env python3
"""
Long video -> vertical narrated reels.

Give it a YouTube URL (or a local file) and it gives you back 5-10 vertical
shorts, each one a 1-2 minute stretch of the film with the original dialogue
stripped out, a narrator speaking over it, and karaoke captions burned in.

  1. Downloads the video with yt-dlp, and YouTube's own transcript with it
     (no Whisper run on a two-hour movie unless the video has no captions)
  2. Scores the whole runtime second by second -- loudness plus how much is
     being said -- and picks the N best non-overlapping stretches
  3. Snaps each stretch to the nearest scene cut so a reel never opens or
     closes mid-shot
  4. Writes a narration script for each reel from that stretch's transcript
     (a local Ollama model if you have one, otherwise extractive)
  5. Speaks it with a free Edge neural voice, keeping the word timings the
     voice reports -- that is what makes the captions land on the syllable
  6. Splits the clip's audio with Demucs, throws away the dialogue and keeps
     the music and effects, then ducks that bed under the narration
  7. Reframes to 1080x1920 (letterbox bars detected and cropped off first),
     burns the captions, and writes output/<title>/reel-01.mp4

Everything is free and runs on this machine. No API keys.

Usage (macOS/Linux ./run.sh, Windows run.bat -- same arguments):
  ./run.sh "https://www.youtube.com/watch?v=XXXX"
  ./run.sh "URL" --plan                  # show the picks, render nothing
  ./run.sh "URL" --reels 7 --duration 75
  ./run.sh "URL" --script ollama --model llama3.2
  ./run.sh "URL" --fit crop --voice en-US-BrianNeural
  ./run.sh "/path/to/movie.mp4" --reels 5
  ./run.sh --list-voices

Everything is cached under work/<video>/, so a re-run only redoes what changed.
Start with --plan: picking the stretches takes a couple of minutes, rendering
them takes considerably longer.
"""

import argparse
import asyncio
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

# Intel macOS landmine, set before anything that reads it loads: faster-whisper
# pulls in torch for its voice-activity filter, so torch's libiomp5 and
# ctranslate2's libiomp5 land in one process and Intel's OpenMP aborts the run.
# Letting the duplicate through is the documented escape hatch.
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

ROOT = Path(__file__).resolve().parent
WORK = ROOT / "work"
OUTPUT = ROOT / "output"

SAMPLE_RATE = 48000
REEL_W, REEL_H = 1080, 1920
FPS = 30

# Measured off these voices rather than assumed: they land near 183 words a
# minute at +0%, well above the ~155 a human narrator reads at. The script
# generators aim at this so a reel comes out close to the length it asked for --
# guess low and every reel ends with the narrator finished and the picture still
# running.
WORDS_PER_SECOND = 183 / 60

DEFAULT_VOICE = "en-US-AndrewMultilingualNeural"

# Voices worth trying first: these are the conversational ones, which is what
# keeps a recap from sounding like a station announcement.
SUGGESTED_VOICES = [
    "en-US-AndrewMultilingualNeural",
    "en-US-BrianMultilingualNeural",
    "en-US-AvaMultilingualNeural",
    "en-US-EmmaMultilingualNeural",
    "en-US-GuyNeural",
    "en-GB-RyanNeural",
]


# ---------------------------------------------------------------- helpers


def run(cmd, **kw):
    print("  $ " + " ".join(str(c) for c in cmd[:6]) + (" ..." if len(cmd) > 6 else ""))
    subprocess.run([str(c) for c in cmd], check=True, **kw)


def ffmpeg(*args):
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args])


def ffmpeg_cached(out, *args):
    """Render to a temp name and rename into place.

    Everything under work/ is reused on the next run purely because the file is
    there, so a run killed midway through an encode would otherwise leave a
    truncated file that every later run trusts. Renaming is atomic, so a cached
    file is either complete or absent.
    """
    out = Path(out)
    tmp = out.with_name(f".partial-{out.name}")
    try:
        ffmpeg(*args, tmp)
        tmp.replace(out)
    finally:
        tmp.unlink(missing_ok=True)
    return out


def probe(path, stream, *fields):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", stream,
         "-show_entries", f"stream={','.join(fields)}",
         "-of", "csv=p=0:s=,", str(path)],
        capture_output=True, text=True).stdout.strip().splitlines()
    return out[0].split(",") if out else []


def video_size(path):
    vals = probe(path, "v:0", "width", "height")
    if not vals:
        sys.exit(f"ffprobe found no video stream in {path}")
    return int(vals[0]), int(vals[1])


def duration_of(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)], capture_output=True, text=True).stdout.strip()
    try:
        return float(out)
    except ValueError:
        return 0.0


def slugify(text, fallback="video"):
    text = re.sub(r"[^\w\s-]", "", (text or "").lower())
    text = re.sub(r"[\s_-]+", "-", text).strip("-")
    return text[:60] or fallback


def load_json(path):
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def save_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def dir_size(path):
    path = Path(path)
    if not path.exists():
        return 0
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def clean_cache():
    """Throw away the working cache.

    It holds the downloaded video and every intermediate wav, which is nearly
    all of the disk this project uses -- the finished reels in output/ are tiny
    beside it. Nothing here is precious: a later run re-downloads and redoes
    whatever it needs. Finished reels and narration scripts live in output/ and
    are left alone.
    """
    size = dir_size(WORK)
    if not size:
        print("Cache is already empty.")
        return
    shutil.rmtree(WORK, ignore_errors=True)
    print(f"Freed {human_size(size)}. Your reels and scripts in output/ are untouched.")


def hhmmss(seconds):
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{h:d}:{m:02d}:{s:02d}"


def srt_time(seconds):
    seconds = max(0.0, seconds)
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d},{int(round((seconds % 1) * 1000)):03d}"


def wrap(text, width=42, max_lines=2):
    def greedy(w):
        lines, line = [], ""
        for word in text.split():
            if line and len(line) + 1 + len(word) > w:
                lines.append(line)
                line = word
            else:
                line = f"{line} {word}".strip()
        if line:
            lines.append(line)
        return lines

    lines = greedy(width)
    # A line too long for the box reads better spread evenly than as one full
    # width line next to a stub, so widen until it fits instead of regrouping.
    w = max(width, -(-len(text) // max_lines))
    while len(lines) > max_lines and w <= len(text):
        lines = greedy(w)
        w += 4
    return "\n".join(lines)


# ---------------------------------------------------------------- 1. source


# Every spelling a video id shows up in: watch?v=, youtu.be/, /shorts/, /embed/,
# /live/. Anchored so a partial match inside a longer id can't slip through.
YT_ID = re.compile(
    r"(?:v=|/shorts/|/embed/|/live/|/v/|youtu\.be/)([0-9A-Za-z_-]{11})(?![0-9A-Za-z_-])")

VIDEO_EXTS = (".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi")


def normalize_url(url):
    """Turn anything YouTube-shaped into a plain watch URL.

    Copying a Shorts link into a watch?v= link is an easy slip and yt-dlp just
    reports "Unsupported URL", so pull the id out and rebuild the link instead.
    Taking the last id handles exactly that nested case; a share ?si= tracker
    falls away with it. Anything unrecognised is passed through untouched so
    yt-dlp can still try other sites.
    """
    ids = YT_ID.findall(url)
    if ids:
        return f"https://www.youtube.com/watch?v={ids[-1]}"
    if re.fullmatch(r"[0-9A-Za-z_-]{11}", url.strip()):
        return f"https://www.youtube.com/watch?v={url.strip()}"
    return url


def find_source(d):
    """The merged download, never one of yt-dlp's per-stream leftovers.

    An interrupted download leaves files like source.f399.mp4 next to the
    finished source.mp4, and those sort first alphabetically, so picking by glob
    order could quietly hand back a video-only or audio-only fragment.
    """
    merged = d / "source.mp4"
    if merged.exists():
        return merged
    return next((p for p in sorted(d.glob("source.*"))
                 if p.suffix.lower() in VIDEO_EXTS and ".f" not in p.stem), None)


def fetch(target, d, max_height=1080):
    """Download the video and its transcript, or adopt a local file.

    The transcript is asked for in the same breath as the video because
    YouTube's own captions are the difference between starting work in a minute
    and running Whisper across two hours of film first.
    """
    local = Path(target).expanduser()
    if local.exists() and local.suffix.lower() in VIDEO_EXTS:
        link = d / f"source{local.suffix.lower()}"
        if not link.exists():
            # Hard-link so a 4 GB film is not copied; fall back across volumes.
            try:
                os.link(local, link)
            except OSError:
                shutil.copy2(local, link)
        print(f"  local source: {local.name}")
        return link, local.stem, {}

    video = find_source(d)
    if video is None:
        fmt = (f"bestvideo[height<={max_height}][ext=mp4]+bestaudio[ext=m4a]/"
               f"bestvideo[height<={max_height}]+bestaudio/"
               f"best[height<={max_height}]/best")
        run(["yt-dlp", "--no-playlist", "--write-info-json",
             "-f", fmt, "--merge-output-format", "mp4",
             "-o", str(d / "source.%(ext)s"), target])
        video = find_source(d)
        if video is None:
            sys.exit("yt-dlp finished but left no video file behind.")
    else:
        print(f"  cached download: {video.name}")

    download_captions(target, d)
    info = load_json(d / "source.info.json") or {}
    return video, info.get("title") or video.stem, info


def download_audio(target, d):
    """Just the soundtrack, for transcribing a video that has no captions.

    A couple of hundred megabytes at most against several gigabytes for the
    picture, and Whisper never looks at the picture anyway.
    """
    got = next((p for p in sorted(d.glob("audio.*")) if p.suffix != ".json"), None)
    if got:
        return got
    run(["yt-dlp", "--no-playlist", "-f", "bestaudio/best",
         "-o", str(d / "audio.%(ext)s"), target])
    return next((p for p in sorted(d.glob("audio.*")) if p.suffix != ".json"), None)


def fetch_meta(target, d):
    """The transcript and the runtime, without downloading the video.

    Writing narration only needs the words and how long the film is, and the
    film itself is gigabytes. So this fetches the captions and the metadata and
    stops. The picture is downloaded later, and only if you go on to render.

    Returns (video_or_None, title, total_seconds). A local file is used where it
    sits -- there is nothing to save by refusing to look at a file already on
    the disk.
    """
    local = Path(target).expanduser()
    if local.exists() and local.suffix.lower() in VIDEO_EXTS:
        video, title, _ = fetch(target, d)
        return video, title, duration_of(video)

    if not (d / "source.info.json").exists():
        run(["yt-dlp", "--no-playlist", "--skip-download", "--write-info-json",
             "-o", str(d / "source.%(ext)s"), target])
    download_captions(target, d)

    info = load_json(d / "source.info.json") or {}
    total = float(info.get("duration") or 0)
    if not total:
        sys.exit("Could not read the video's duration without downloading it. "
                 "Run without --scripts to fetch the video itself.")
    return None, info.get("title") or "video", total


def caption_files(d):
    """Caption files best first.

    A plain "en" track is the one a human typed where the video has one;
    "en-orig" and the rest are machine transcripts. Plain alphabetical order
    puts en-orig first, which is exactly backwards, so rank the plain tag ahead
    of everything else. json3 is preferred over vtt for carrying word timings.
    """
    def rank(p):
        return (0 if p.suffixes[:1] == [".en"] else 1, p.name)

    return (sorted(d.glob("source*.json3"), key=rank)
            or sorted(d.glob("source*.vtt"), key=rank))


# Asking for "en.*" looks right and is a trap: YouTube offers the English track
# machine-translated into sixty-odd languages, every one of them matching that
# pattern, and working through the list earns an HTTP 429 partway down. These
# are the spellings an actual English track uses.
SUB_LANGS = "en,en-US,en-GB,en-orig"


CAPTION_TROUBLE = {}


def download_captions(target, d):
    """Fetch the transcript on its own, and never let it sink the run.

    Kept apart from the video download so a rate-limited or missing caption
    file costs nothing more than a slower path through Whisper -- bundling the
    two means one 429 throws away a download that may have taken an hour.
    """
    if caption_files(d):
        return
    cmd = ["yt-dlp", "--no-playlist", "--skip-download",
           "--write-subs", "--write-auto-subs",
           "--sub-langs", SUB_LANGS, "--sub-format", "json3/vtt/best",
           "-o", str(d / "source.%(ext)s"), target]
    print("  $ yt-dlp --skip-download --write-auto-subs ...")
    done = subprocess.run(cmd, capture_output=True, text=True)
    if not caption_files(d):
        blurb = (done.stderr or "") + (done.stdout or "")
        why = blurb.strip().splitlines()
        # A rate limit is not the same as a video with no captions, and the
        # difference decides whether waiting ten minutes fixes it.
        CAPTION_TROUBLE[str(d)] = ("rate-limited" if "429" in blurb
                                   else (why[-1] if why else "unknown"))
        print(f"  no caption file came back"
              f"{': ' + why[-1] if why else ''}")


# ---------------------------------------------------------------- 2. transcript


def _tokens_from_json3(path):
    """Word tokens with absolute times out of YouTube's json3 caption format.

    Auto-captions stream as a rolling window: every line is emitted once as a
    timed event and again as part of the next event's scrollback. The
    scrollback copies carry aAppend, so dropping those leaves each word exactly
    once, at the moment it is actually said.
    """
    data = load_json(path) or {}
    out = []
    for ev in data.get("events", []):
        if ev.get("aAppend") or "segs" not in ev:
            continue
        base = ev.get("tStartMs", 0)
        for seg in ev["segs"]:
            text = seg.get("utf8", "")
            if not text.strip():
                continue
            out.append(((base + seg.get("tOffsetMs", 0)) / 1000.0, text.strip()))
    return out


VTT_TIME = re.compile(r"(\d+):(\d\d):(\d\d)[.,](\d+)\s*-->\s*(\d+):(\d\d):(\d\d)[.,](\d+)")
VTT_TAG = re.compile(r"<[^>]+>")


def _tokens_from_vtt(path):
    """Same idea for the vtt fallback, at line granularity rather than word.

    vtt auto-captions repeat the previous line at the top of each cue, so a cue
    that merely re-states text already seen contributes nothing new.
    """
    out, seen = [], set()
    start = None
    for line in Path(path).read_text(encoding="utf-8", errors="ignore").splitlines():
        m = VTT_TIME.search(line)
        if m:
            h, mi, s, ms = m.group(1, 2, 3, 4)
            start = int(h) * 3600 + int(mi) * 60 + int(s) + int(ms.ljust(3, "0")[:3]) / 1000
            continue
        if start is None:
            continue
        text = VTT_TAG.sub("", line).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append((start, text))
    return out


def _group(tokens, max_chars=90, max_gap=1.2):
    """Word tokens -> readable lines, split on pauses and sentence ends."""
    lines, buf, start, last = [], [], None, None
    for t, text in tokens:
        if start is None:
            start = t
        if buf and (t - last > max_gap or len(" ".join(buf)) + len(text) > max_chars
                    or buf[-1].endswith((".", "?", "!"))):
            lines.append({"start": round(start, 3), "end": round(last + 0.6, 3),
                          "text": " ".join(buf)})
            buf, start = [], t
        buf.append(text)
        last = t
    if buf:
        lines.append({"start": round(start, 3), "end": round(last + 0.6, 3),
                      "text": " ".join(buf)})
    return lines


def transcript(video, d, whisper_model):
    """YouTube's captions if the download brought any, Whisper if it did not."""
    cache = d / "transcript.json"
    cached = load_json(cache)
    if cached:
        print(f"  cached transcript: {len(cached)} lines")
        return cached

    subs = caption_files(d)
    if subs:
        path = subs[0]
        print(f"  using YouTube's transcript: {path.name}")
        tokens = (_tokens_from_json3(path) if path.suffix == ".json3"
                  else _tokens_from_vtt(path))
        lines = _group(tokens)
        if lines:
            save_json(cache, lines)
            print(f"  {len(lines)} lines")
            return lines
        print("  that caption file turned out empty; falling back to Whisper")

    wav = d / "speech16k.wav"
    if not wav.exists():
        ffmpeg_cached(wav, "-i", video, "-vn", "-ac", "1", "-ar", "16000")

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        sys.exit(
            "This video has no captions, so the speech has to be transcribed --\n"
            "  but Whisper is not installed. If you installed from\n"
            "  requirements-lite.txt, that is expected. Either:\n"
            "    * use a video that has captions (most YouTube videos do), or\n"
            "    * install the full set:  pip install -r requirements.txt")

    mins = duration_of(video) / 60
    print(f"  no captions available -- transcribing {mins:.0f} min with Whisper "
          f"'{whisper_model}'. This is the slow path; expect a long wait.")
    model = WhisperModel(whisper_model, device="cpu", compute_type="int8")
    try:
        segs, _ = model.transcribe(str(wav), language="en", vad_filter=True,
                                   beam_size=5,
                                   vad_parameters={"min_silence_duration_ms": 400})
        segs = list(segs)
    except Exception as e:                      # onnxruntime missing / VAD failure
        print(f"  voice-activity filter unavailable ({e}); transcribing without it")
        segs, _ = model.transcribe(str(wav), language="en", beam_size=5)
        segs = list(segs)

    lines = [{"start": round(s.start, 3), "end": round(s.end, 3), "text": s.text.strip()}
             for s in segs if s.text.strip()]
    if not lines:
        sys.exit("No speech found in this video, so there is nothing to narrate.")
    save_json(cache, lines)
    print(f"  {len(lines)} lines transcribed")
    return lines


# ---------------------------------------------------------------- 3. analysis


def loudness_curve(video, d):
    """One RMS value per second across the whole runtime.

    Decoded at 4 kHz mono, which is far below anything you would listen to but
    is plenty for "is something happening here" -- and keeps a two-hour film
    down to a buffer numpy can hold without complaint.
    """
    import numpy as np

    cache = d / "loudness.npy"
    if cache.exists():
        return np.load(cache)

    print("  measuring loudness across the runtime ...")
    sr = 4000
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(video), "-vn",
         "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"],
        capture_output=True).stdout
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    n = len(samples) // sr
    if n == 0:
        return np.zeros(1, dtype=np.float32)
    curve = np.sqrt((samples[:n * sr].reshape(n, sr) ** 2).mean(axis=1))
    np.save(cache, curve)
    return curve


def speech_curve(lines, seconds):
    """Words spoken per second, on the same one-second grid as the loudness."""
    import numpy as np

    curve = np.zeros(max(seconds, 1), dtype=np.float32)
    for ln in lines:
        words = len(ln["text"].split())
        span = max(ln["end"] - ln["start"], 0.5)
        lo, hi = int(ln["start"]), min(int(ln["end"]) + 1, len(curve))
        if hi > lo:
            curve[lo:hi] += words / span
    return curve


def _norm(a):
    import numpy as np

    lo, hi = float(np.percentile(a, 5)), float(np.percentile(a, 95))
    if hi - lo < 1e-6:
        return np.zeros_like(a)
    return np.clip((a - lo) / (hi - lo), 0, 1)


def score_curve(video, lines, d, start_frac, end_frac):
    """How worth watching each second is, on a one-second grid.

    Loudness and how much is being said, because between them they catch both
    the set pieces and the scenes that carry plot -- footage cut from a silent
    establishing shot has nothing happening in it. The head and tail are marked
    unusable outright: logos, cold opens and end credits are never what you
    want, and they sit at predictable ends of the runtime.
    """
    import numpy as np

    total = duration_of(video)
    loud = loudness_curve(video, d)
    # A file whose audio runs shorter than its picture -- a stripped track, a
    # bad mux -- would otherwise confine every pick to the part that has sound.
    # Pad the grid out to the real runtime instead, so the silent tail is merely
    # unattractive rather than invisible.
    seconds = int(total)
    loud = (np.pad(loud, (0, seconds - len(loud))) if len(loud) < seconds
            else loud[:seconds])
    speech = speech_curve(lines, seconds)[:seconds]

    score = 0.5 * _norm(loud) + 0.5 * _norm(speech)
    score[:int(seconds * start_frac)] = -1
    score[int(seconds * (1 - end_frac)):] = -1
    return score, seconds, total


def transcript_score(lines, total, start_frac, end_frac):
    """Scoring from the transcript alone, for when no video has been downloaded.

    Only how much is being said, because loudness needs the film's audio. For
    chapter boundaries that costs nothing -- a recap's structure comes from the
    runtime, not the soundtrack -- and for choosing which minute to show it is a
    fair stand-in until the picture is actually there.
    """
    seconds = max(int(total), 1)
    score = _norm(speech_curve(lines, seconds)[:seconds])
    score[:int(seconds * start_frac)] = -1
    score[int(seconds * (1 - end_frac)):] = -1
    return score, seconds, float(total)


def story_spans(video, lines, d, count, target, start_frac, end_frac):
    """Consecutive chapters covering the film in order, for a recap series."""
    score, seconds, total = score_curve(video, lines, d, start_frac, end_frac)
    return story_chapters(score, seconds, total, count, target, start_frac, end_frac,
                          lambda t: snap_to_cut(video, t, d))


def story_chapters(score, seconds, total, count, target, start_frac, end_frac,
                   snap=None):
    """Divide the runtime into N chapters and pick each one's footage.

    This is a different job from picking highlights. A recap tells the story
    from beginning to end across several parts, so the film is divided into N
    chapters that between them cover the whole runtime, and each reel is one
    chapter. Nothing is skipped and nothing is told out of order.

    Each chapter narrates its whole stretch -- which may be ten minutes of film
    -- while showing only the best minute or so of footage from inside it. That
    is how these recaps work: the voice covers the plot, the picture shows the
    part worth looking at.

    snap moves a start onto the nearest shot change; left out, the spans come
    back marked unsnapped so that can be done later, once the video exists.
    """
    import numpy as np

    lo = int(seconds * start_frac)
    hi = int(seconds * (1 - end_frac))
    if hi - lo < count:
        sys.exit(f"This video is only {hhmmss(total)} long; nothing to cut up.")

    win = min(int(target), max(5, (hi - lo) // count))
    cum = np.concatenate([[0.0], np.cumsum(score)])

    spans = []
    edges = np.linspace(lo, hi, count + 1).astype(int)
    for i in range(count):
        c0, c1 = int(edges[i]), int(edges[i + 1])
        # Best window for the footage, taken from inside this chapter only, so
        # the picture always belongs to the part of the story being told.
        last = max(c0, c1 - win)
        if last > c0:
            means = (cum[c0 + win:last + win + 1] - cum[c0:last + 1]) / win
            at = c0 + int(np.argmax(means))
        else:
            at = c0
        start = snap(float(at)) if snap else float(at)
        span = {
            "start": round(start, 2),
            "end": round(min(start + target, total), 2),
            # The stretch of story this chapter is responsible for narrating.
            "narr_start": round(c0, 2),
            "narr_end": round(c1, 2),
            "chapter": i + 1,
        }
        if snap is None:
            span["unsnapped"] = True
        spans.append(span)
    return spans


def pick_highlights(video, lines, d, count, target, gap, start_frac, end_frac):
    """The N most eventful non-overlapping stretches, in story order.

    Scored on loudness and on how much is being said, because between them they
    catch both the set pieces and the scenes that actually carry plot -- a reel
    cut from a silent establishing shot has nothing to narrate. Picks are taken
    greedily, best first, with a gap enforced around each one so all N do not
    pile into the same ten minutes.
    """
    score, seconds, total = score_curve(video, lines, d, start_frac, end_frac)
    return best_windows(score, seconds, total, count, target, gap,
                        lambda t: snap_to_cut(video, t, d))


def best_windows(score, seconds, total, count, target, gap, snap=None):
    """The N best-scoring stretches, far enough apart not to overlap."""
    import numpy as np

    win = int(target)
    if seconds <= win:
        sys.exit(f"This video is only {hhmmss(total)} long; nothing to cut up.")

    # Mean score of every window start, via a cumulative sum so a two-hour film
    # is one pass rather than seven thousand slices.
    cum = np.concatenate([[0.0], np.cumsum(score)])
    windows = (cum[win:] - cum[:-win]) / win

    picks = []
    blocked = np.zeros(len(windows), dtype=bool)
    blocked[windows < -0.5] = True              # windows overlapping a trimmed end
    for _ in range(count):
        if blocked.all():
            break
        masked = np.where(blocked, -np.inf, windows)
        i = int(masked.argmax())
        picks.append(i)
        lo = max(0, i - win - int(gap))
        hi = min(len(blocked), i + win + int(gap))
        blocked[lo:hi] = True

    if len(picks) < count:
        print(f"  only {len(picks)} well-separated stretches fit in "
              f"{hhmmss(total)}; reduce --gap or --reels for more")

    spans = []
    for t0 in sorted(picks):
        s = snap(float(t0)) if snap else float(t0)
        span = {"start": round(s, 2), "end": round(min(s + target, total), 2)}
        if snap is None:
            span["unsnapped"] = True
        spans.append(span)
    return spans


SCENE_PTS = re.compile(r"pts_time:([0-9.]+)")


def snap_to_cut(video, t, d, window=5.0, threshold=0.3):
    """Move a start time to the nearest shot change within a few seconds.

    Opening a reel two seconds into a shot looks like a mistake; opening on the
    cut looks deliberate. Only the window around the pick is decoded, so this
    stays cheap even on a feature-length source.
    """
    lo = max(0.0, t - window)
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{lo:.3f}", "-t", f"{window * 2:.3f}",
         "-i", str(video), "-an",
         "-vf", f"scale=240:-2,select='gt(scene,{threshold})',metadata=print:file=-",
         "-f", "null", "-"],
        capture_output=True, text=True)
    cuts = [lo + float(m) for m in SCENE_PTS.findall(out.stdout)]
    if not cuts:
        return t
    best = min(cuts, key=lambda c: abs(c - t))
    return best if abs(best - t) <= window else t


CROP_RE = re.compile(r"crop=(\d+):(\d+):(\d+):(\d+)")


def detect_letterbox(video, d, samples=6):
    """The rectangle the picture actually occupies, bars excluded.

    A 2.39:1 film in a 16:9 container is mostly black once it is squeezed into a
    9:16 frame, so the bars come off before any reframing. Several points in the
    runtime are sampled because one dark scene would otherwise be mistaken for a
    bar. The widest, tallest rectangle any sample claims is the safe answer --
    erring toward keeping picture rather than cropping into it.
    """
    cache = d / "letterbox.json"
    cached = load_json(cache)
    if cached is not None:
        return tuple(cached)

    w, h = video_size(video)
    total = duration_of(video)
    best = None
    for i in range(samples):
        at = total * (0.15 + 0.7 * i / max(samples - 1, 1))
        out = subprocess.run(
            ["ffmpeg", "-v", "info", "-ss", f"{at:.2f}", "-t", "4", "-i", str(video),
             "-an", "-vf", "cropdetect=24:2:0", "-f", "null", "-"],
            capture_output=True, text=True).stderr
        found = CROP_RE.findall(out)
        if not found:
            continue
        cw, ch, cx, cy = (int(v) for v in found[-1])
        if cw <= 0 or ch <= 0:
            continue
        best = (cw, ch, cx, cy) if best is None else (
            max(best[0], cw), max(best[1], ch), min(best[2], cx), min(best[3], cy))

    if best is None or best[0] * best[1] < w * h * 0.25:
        best = (w, h, 0, 0)
    # Even dimensions keep every downstream filter and encoder happy.
    best = (best[0] - best[0] % 2, best[1] - best[1] % 2, best[2], best[3])
    save_json(cache, list(best))
    if best[:2] != (w, h):
        print(f"  cropping letterbox bars: {w}x{h} -> {best[0]}x{best[1]}")
    return best


def detect_caption_band(video, d, samples=14):
    """Find subtitles burned into the source picture; return the rows they use.

    No subtitle track can replace text that is part of the image -- the only way
    to be rid of it is to paint over those pixels. Caption glyphs are bright and
    carry a hard dark outline, a combination almost nothing else in a frame has,
    so each row is scored by how many bright pixels sit within a few rows of a
    dark one, and the rows that stand out are the band.

    Frames are seeked to individually rather than filtered out of a full decode,
    because a feature-length film would otherwise have to be decoded end to end
    to sample a dozen pictures. Returns None when the source is clean.
    """
    import numpy as np

    cache = d / "caption_band.json"
    cached = load_json(cache)
    if cached is not None:
        return tuple(cached) if cached else None

    w, h = video_size(video)
    total = duration_of(video)
    frames = []
    for i in range(samples):
        at = total * (0.10 + 0.8 * i / max(samples - 1, 1))
        raw = subprocess.run(
            ["ffmpeg", "-v", "error", "-ss", f"{at:.2f}", "-i", str(video),
             "-frames:v", "1", "-vf", "format=gray", "-f", "rawvideo", "-"],
            capture_output=True).stdout
        if len(raw) >= w * h:
            frames.append(np.frombuffer(raw[:w * h], dtype=np.uint8).reshape(h, w))

    if not frames:
        save_json(cache, None)
        return None

    f = np.stack(frames)
    mid = f[:, :, int(w * 0.2):int(w * 0.8)]          # captions sit centred
    bright, dark = mid > 240, mid < 40
    outline = np.zeros_like(bright)
    for s in range(1, 7):
        outline[:, s:, :] |= dark[:, :-s, :]
        outline[:, :-s, :] |= dark[:, s:, :]
    score = (bright & outline).sum(axis=2).mean(axis=0)
    score[:h // 2] = 0                                 # ignore the top half

    if score.max() < 6:                                # nothing burned in
        save_json(cache, None)
        print("  no burned-in subtitles found in the source")
        return None

    rows = np.flatnonzero(score >= max(3.0, score.max() * 0.15))
    pad = int(h * 0.015)
    band = (max(0, int(rows.min()) - pad), min(h, int(rows.max()) + pad))
    save_json(cache, list(band))
    print(f"  covering burned-in subtitles in the source: rows {band[0]}-{band[1]}")
    return band


# ---------------------------------------------------------------- 4. script


# How the narration is written. These are the fallbacks; styles/*.txt is the
# real list, so a new way of writing is a text file rather than a code change.
BUILTIN_STYLES = {
    "punchy": {
        "label": "fast story recap: past tense, one beat per sentence",
        "rules": ("Write in the past tense. Keep every sentence to a single idea "
                  "and to about fourteen words at most. Move the plot forward in "
                  "every sentence. Report what people say instead of quoting "
                  "them. Use the characters' names."),
        "open": ("Open with one striking thing the main character did, then turn "
                 "it immediately."),
        "close": ("Finish with one short direct question to the viewer about "
                  "what they would have done."),
        "reminder": ("every single sentence is in the past tense, and no "
                     "sentence runs past about fourteen words"),
    },
}

STYLES_DIR = ROOT / "styles"


def _parse_style(text):
    """One style file: "key: value" lines, a blank line, then the writing rules.

    Deliberately not YAML or JSON. These are meant to be opened and reworded by
    whoever is using them, and the lite install has no parser to spare.
    """
    head, _, body = text.partition("\n\n")
    meta = {}
    for line in head.splitlines():
        if ":" in line and not line.startswith("#"):
            key, _, value = line.partition(":")
            meta[key.strip().lower()] = value.strip()
    # Collapse each paragraph but keep the breaks: the shape of a structure --
    # intro, story, call to action -- is carried by its paragraphs.
    paras = [" ".join(part.split()) for part in body.split("\n\n") if part.strip()]
    rules = "\n\n".join(paras)
    if not rules:
        raise ValueError("no writing rules after the blank line")
    return {"label": meta.get("label", ""), "rules": rules,
            "open": meta.get("open", ""), "close": meta.get("close", ""),
            "reminder": meta.get("reminder", "")}


def load_styles():
    """Every style in styles/, falling back to the built-ins if it is missing."""
    styles = {k: dict(v) for k, v in BUILTIN_STYLES.items()}
    if STYLES_DIR.is_dir():
        for path in sorted(STYLES_DIR.glob("*.txt")):
            try:
                styles[path.stem] = _parse_style(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as e:
                print(f"  ignoring styles/{path.name}: {e}")
    return styles


STYLES = load_styles()

DEFAULT_STYLE = "punchy"

# Asking for the title in prose produced titles run together with the first
# sentence, which then got read aloud. Asking for JSON parsed perfectly but
# wrecked the writing -- constrained decoding collapses a small model's prose
# into comma-spliced fragments a tenth of the length. A plain separator keeps
# the prose intact and still splits deterministically.
TITLE_SEP = "|||"
REPLY_FORMAT = (f' Reply with a short title of at most six words, then {TITLE_SEP}, '
              f'then the narration. Put nothing else in the reply.')


def style_for(a):
    """The writing rules this run should use.

    A file given with --style-file replaces the built-in wording outright, so a
    style nobody anticipated does not need a code change to use.
    """
    path = getattr(a, "style_file", None)
    if path:
        text = Path(path).read_text(encoding="utf-8").strip()
        if not text:
            sys.exit(f"{path} is empty -- it should describe how to write.")
        return {"label": f"custom ({Path(path).name})", "rules": text,
                "open": "", "close": ""}
    return STYLES[getattr(a, "style", DEFAULT_STYLE)]


CUE = re.compile(r"\[[^\]]*\]|\([^)]*\)|♪|>>")
SPEAKER = re.compile(r"^[A-Z][A-Z .'-]{1,20}:\s*")


def clean_line(text):
    """Strip the things a caption track carries that a narrator should not say."""
    text = CUE.sub(" ", text)
    text = SPEAKER.sub("", text.strip())
    return re.sub(r"\s+", " ", text).strip()


def lines_in(lines, span):
    """The transcript this reel narrates.

    In story mode that is the whole chapter, which is far longer than the
    footage shown -- the voice covers the plot while the picture shows the best
    part of it. Everywhere else the two are the same stretch.
    """
    start = span.get("narr_start", span["start"])
    end = span.get("narr_end", span["end"])
    return [ln for ln in lines if ln["end"] > start and ln["start"] < end]


def split_script(raw):
    """Split a script file into its title and the words to be spoken.

    Lines starting with # are notes: the chapter title the generator wrote, and
    anything you jot down yourself. They are kept in the file and never read
    aloud, which is what lets one file per reel hold both.
    """
    title, body = None, []
    for ln in raw.splitlines():
        if ln.strip().startswith("#"):
            if title is None:
                title = ln.strip().lstrip("#").strip()
        else:
            body.append(ln)
    return title, " ".join(" ".join(body).split())


_OLLAMA_SEEN = {}


def ollama_up(host):
    """Whether a local Ollama is answering, cached for the run.

    Checked so the default can simply use it when it is there. Without a model
    the only other option selects sentences out of the transcript, and a film's
    transcript is dialogue -- so the "narration" comes out as characters talking
    in the first person, which is not narration at all.
    """
    import urllib.error
    import urllib.request

    if host in _OLLAMA_SEEN:
        return _OLLAMA_SEEN[host]
    try:
        with urllib.request.urlopen(f"{host.rstrip('/')}/api/tags", timeout=3) as r:
            up = r.status == 200
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        up = False
    _OLLAMA_SEEN[host] = up
    return up


# Pronouns that mark a line as somebody speaking rather than somebody narrating.
SPEAKER_WORDS = {"i", "im", "ill", "ive", "id", "me", "my", "mine", "myself",
                 "we", "us", "our", "ours", "ourselves",
                 "you", "your", "yours", "youre", "youll", "youve", "yourself"}


def speaker_ratio(text):
    """How much of a line is first or second person, 0 to 1."""
    toks = re.findall(r"[a-z']+", text.lower())
    if not toks:
        return 0.0
    return sum(1 for t in toks if t.replace("'", "") in SPEAKER_WORDS) / len(toks)


def extractive_script(lines, span, target_words):
    """A narration built from the most representative lines of the stretch.

    No model, no download, no network: sentences are scored by how many of the
    stretch's own frequent words they carry, normalised by length so a long
    rambling line does not win on volume alone. It reads as a summary of what is
    said rather than as writing, which is the honest limit of doing this without
    a model -- --script ollama is the upgrade path.
    """
    chosen = [clean_line(ln["text"]) for ln in lines_in(lines, span)]
    chosen = [c for c in chosen if len(c.split()) >= 3]
    if not chosen:
        return ""

    # Lines thick with "I" and "you" are characters talking, and strung together
    # they read as dialogue rather than as anyone describing events. Prefer the
    # rest -- unless that leaves too little to work with, in which case a poor
    # script beats none.
    narrated = [c for c in chosen if speaker_ratio(c) < 0.12]
    if len(narrated) >= 3:
        chosen = narrated

    words = [w for c in chosen for w in re.findall(r"[a-z']+", c.lower())]
    freq = Counter(w for w in words if w not in STOPWORDS)
    if not freq:
        return " ".join(chosen)[:target_words * 8]
    top = freq.most_common(1)[0][1]

    ranked = []
    for i, c in enumerate(chosen):
        toks = [w for w in re.findall(r"[a-z']+", c.lower()) if w not in STOPWORDS]
        if not toks:
            continue
        ranked.append((sum(freq[w] for w in toks) / (top * len(toks) ** 0.6), i, c))
    ranked.sort(reverse=True)

    keep, used = [], 0
    for _, i, c in ranked:
        if used >= target_words:
            break
        keep.append((i, c))
        used += len(c.split())
    keep.sort()                                  # back into the order they were said

    text = " ".join(c for _, c in keep)
    if text and text[-1] not in ".?!":
        text += "."
    return text


STOPWORDS = set("""a an and are as at be been but by can could did do does for from
had has have he her here him his how i if in into is it its just like me my no not
of on or our out she should so than that the their them then there these they this
to too was we were what when where which who will with would you your yeah okay oh
uh um going get got know really right now one see said says come came go went about
""".split())


def ollama_script(lines, span, target_words, model, host, chapter=None,
                  previous=None, style=None, is_last=False):
    """Ask a local Ollama model for real narration. Free, offline, no key.

    Returns (title, text), or None on any failure so the caller can fall back
    rather than abort a long render over a model that is not pulled.
    """
    import urllib.error
    import urllib.request

    excerpt = " ".join(clean_line(ln["text"]) for ln in lines_in(lines, span))
    excerpt = re.sub(r"\s+", " ", excerpt).strip()[:6000]
    if len(excerpt.split()) < 12:
        return None

    style = style or STYLES[DEFAULT_STYLE]
    # The chosen style says how to write; these hold whatever the style does not
    # cover, and are the same for all of them because they are about the medium
    # rather than the voice.
    rules = (style["rules"] + " Never comment on the film or call it a film, and "
             "never write stage directions, headings, bullet points or "
             "quotation marks.")

    # Goes last in the prompt, where a small model pays most attention, because
    # tense and sentence length are the first things it drifts away from.
    checks = [c for c in (style.get("reminder", ""),
                          "the last line is a question to the viewer"
                          if (is_last and style["close"]) else "") if c]
    reminder = f"\n\nBefore you reply, check that {', and '.join(checks)}." if checks else ""

    if chapter:
        # A recap runs across several parts, so each one has to pick up exactly
        # where the last stopped: told what has already been covered, the model
        # continues instead of re-introducing everyone from scratch.
        so_far = ""
        if previous:
            so_far = (
                f"THE PREVIOUS PART ENDED WITH THESE EXACT WORDS:\n"
                f"...{previous}\n\n"
                f"Carry on from that moment. Do not retell any of it, do not "
                f"begin by summarising, and do not re-introduce anyone already "
                f"named there -- the viewer has just heard it.\n\n")
        prompt = (
            f"You are writing part {chapter} of a recap of one film, narrated in "
            f"order from beginning to end.\n\n"
            f"{so_far}"
            f"TRANSCRIPT OF THIS PART OF THE FILM:\n{excerpt}\n\n"
            f"Write about {target_words} words covering what happens in this "
            f"part. {rules} "
            + ("Continue straight on from the story so far, without recapping it "
               "and without any greeting or introduction. "
               if previous else style["open"] + " ")
            # The sign-off belongs at the end of the whole recap, not at the end
            # of every part of it.
            + ((style["close"] + " ") if is_last and style["close"] else "")
            + REPLY_FORMAT
            + reminder)
    else:
        prompt = (
            "Below is the transcript of one scene from a film.\n\n"
            f"TRANSCRIPT:\n{excerpt}\n\n"
            f"Write about {target_words} words of voiceover narration for a "
            f"vertical short built from this scene. {rules} {style['open']} "
            + ((style["close"] + " ") if style["close"] else "")
            + REPLY_FORMAT
            + reminder)

    body = json.dumps({
        "model": model, "prompt": prompt, "stream": False,
        "options": {"temperature": 0.7, "num_predict": int(target_words * 3)},
    }).encode()
    # Tried twice, because one bad generation quietly costs a whole chapter: the
    # fallback keeps the run alive but drops that part to the extractive script,
    # which in a recap series reads jarringly unlike the ones either side of it.
    # A reply that parses to nothing counts as a failure too -- a model that
    # answers with only its title line is no more use than one that times out.
    for attempt in range(2):
        req = urllib.request.Request(f"{host.rstrip('/')}/api/generate", data=body,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                raw = json.loads(r.read()).get("response", "")
        except (urllib.error.URLError, OSError, ValueError, TimeoutError) as e:
            if attempt == 0:
                print(f"    ollama call failed ({e}); retrying")
                continue
            print(f"    ollama unavailable ({e}); using the extractive script")
            return None

        title, text = parse_narration(raw)
        if text:
            return title, text
        if attempt == 0:
            print("    ollama returned no narration; retrying")

    print("    ollama returned nothing usable; using the extractive script")
    return None


def parse_narration(raw):
    """Pull the title and the spoken words out of whatever the model replied.

    Returns (title_or_None, text). An empty text means the reply was unusable.

    The title is asked for before a separator, so that is tried first and
    settles it. Everything below is the fallback for a reply that ignored it.
    """
    raw = raw.strip()
    if TITLE_SEP in raw:
        head, _, tail = raw.partition(TITLE_SEP)
        spoken = tail.strip().strip("\"'*#").strip()
        if spoken:
            head = re.sub(r"^\s*[\"'*#\s]*title\s*:\s*", "", head.strip(), flags=re.I)
            title = head.strip().strip("\"'*#").strip() or None
            return title, re.sub(r"\s+", " ", spoken)

    # Models like to open with "Here is the narration:" and to wrap the whole
    # thing in quotes; neither belongs in something that gets read aloud.
    text = re.sub(r"^\s*(here'?s?|sure|okay)[^\n:]*:\s*", "", raw, flags=re.I)

    title = None
    m = re.match(r"^\s*[\"'*#\s]*title\s*:\s*(.+)", text, flags=re.I)
    if m:
        line, _, rest = m.group(1).partition("\n")
        # Only take it as a title if narration actually follows. A reply that is
        # nothing but a title has failed, and saying so gets it retried instead
        # of silently handing the chapter to the extractive script.
        if rest.strip():
            title = re.sub(r"[\"'*#\s]+$", "", line.strip())
            text = rest
    else:
        # Models routinely ignore the TITLE: form and just write a bare heading
        # line. Left in, it is read aloud as the opening words of the first
        # sentence -- so treat a short, unpunctuated opening line followed by
        # real text as the title it plainly is.
        first, _, rest = text.partition("\n")
        first = first.strip().strip("\"'*#").strip()
        if (rest.strip() and 0 < len(first.split()) <= 8
                and not first.endswith((".", "!", "?", ",", ";", ":"))):
            title, text = first, rest

    text = re.sub(r"^[\"'*#\s]+|[\"'*\s]+$", "", text)
    return title, re.sub(r"\s+", " ", text)


_WARNED_EXTRACTIVE = False


def resolve_script(a):
    """Which script writer to use, settling "auto" against a live Ollama.

    Said out loud when it falls back, because the difference is not subtle: a
    model writes narration, while the alternative picks lines out of the
    transcript, and a film's transcript is people talking.
    """
    global _WARNED_EXTRACTIVE

    mode = getattr(a, "script", "auto")
    if mode != "auto":
        return mode
    if ollama_up(getattr(a, "ollama_host", "http://127.0.0.1:11434")):
        return "ollama"
    if not _WARNED_EXTRACTIVE:
        _WARNED_EXTRACTIVE = True
        print("  ! No local model is answering, so the scripts will be picked "
              "out of the\n    transcript rather than written. On a film that "
              "reads as characters talking,\n    not as narration. Install "
              "https://ollama.com and run:  ollama pull llama3.2")
    return "extractive"


def narration_for(lines, span, seconds, a, index, scripts_dir, previous=None,
                  is_last=False):
    """One reel's script, as an editable text file beside the finished reels.

    Read back verbatim whenever the file already has something in it, which is
    what makes rewriting one by hand work: edit it, run the same command again,
    and it is spoken and captioned exactly as written. Delete the file to have
    the generator try again.
    """
    scripts_dir.mkdir(parents=True, exist_ok=True)
    cache = scripts_dir / f"reel-{index:02d}.txt"
    if cache.exists():
        title, text = split_script(cache.read_text(encoding="utf-8"))
        if text:
            print(f"    script (yours): {len(text.split())} words")
            return title, text

    target = int(seconds * WORDS_PER_SECOND)
    chapter = span.get("chapter")
    title, text = None, None
    if resolve_script(a) == "ollama":
        got = ollama_script(lines, span, target, a.model, a.ollama_host,
                            chapter=chapter, previous=previous,
                            style=style_for(a), is_last=is_last)
        if got:
            title, text = got
    if not text:
        text = extractive_script(lines, span, target)
    if not text:
        # A stretch with no speech gives the generators nothing to work from.
        # Leave an empty file rather than none at all: it is the difference
        # between a reel you can rescue by writing the narration yourself and
        # one that silently disappears.
        cache.touch()
        print("    script: empty (nothing said in this stretch)")
        return None, ""

    if chapter and not title:
        title = f"Part {chapter}"
    header = f"# {title}\n\n" if title else ""
    cache.write_text(header + text, encoding="utf-8")
    print(f"    script: {len(text.split())} words"
          + (f"   {title}" if title else ""))
    return title, text


# ---------------------------------------------------------------- 5. voice


async def _speak(text, voice, rate, mp3):
    """Speak one script, keeping the word timings the voice reports.

    Those timings are the whole trick behind captions that land on the syllable:
    Edge tells us when it says each word, so nothing has to be guessed from
    character counts or force-aligned afterwards. It only sends them when asked
    -- the default is one event per sentence, which is useless for captions --
    and older builds have no such switch, so those fall back to sentences and
    the caller splits them up.
    """
    import edge_tts

    def make(boundary):
        if boundary is None:
            return edge_tts.Communicate(text, voice, rate=rate)
        return edge_tts.Communicate(text, voice, rate=rate, boundary=boundary)

    boundary = "WordBoundary"
    for attempt in range(3):
        try:
            comm = make(boundary)
        except TypeError:                       # edge-tts too old for the switch
            boundary = None
            comm = make(boundary)
        try:
            audio, words = bytearray(), []
            async for chunk in comm.stream():
                if chunk["type"] == "audio":
                    audio += chunk["data"]
                elif chunk["type"] in ("WordBoundary", "SentenceBoundary"):
                    words.append({
                        "start": chunk["offset"] / 1e7,          # 100ns ticks
                        "end": (chunk["offset"] + chunk["duration"]) / 1e7,
                        "text": chunk["text"],
                    })
            if not audio:
                raise RuntimeError("Edge returned no audio")
            Path(mp3).write_bytes(bytes(audio))
            return words
        except Exception:
            if attempt == 2:
                raise
            await asyncio.sleep(2 * (attempt + 1))


def expand_to_words(events, text, duration):
    """Whatever granularity the voice reported, hand back one entry per word.

    A sentence-level event gets split across its own words in proportion to how
    long each one takes to say, which is close enough that captions still change
    on the beat. If no timings arrived at all, the whole script is spread evenly
    over the audio -- visibly worse, but the reel still ships with captions.
    """
    out = []
    for ev in events:
        words = ev["text"].split()
        if len(words) <= 1:
            out.append(dict(ev))
            continue
        span = max(ev["end"] - ev["start"], 0.2)
        weights = [len(w) + 1 for w in words]
        total = sum(weights)
        t = ev["start"]
        for w, weight in zip(words, weights):
            dur = span * weight / total
            out.append({"start": round(t, 3), "end": round(t + dur, 3), "text": w})
            t += dur

    if not out:
        words = text.split()
        if not words or duration <= 0:
            return []
        step = duration / len(words)
        out = [{"start": round(i * step, 3), "end": round((i + 1) * step, 3), "text": w}
               for i, w in enumerate(words)]
    return repunctuate(out, text)


def _bare(word):
    return re.sub(r"[^\w']", "", word).lower()


def repunctuate(words, text):
    """Put the script's punctuation back onto the timed words.

    Edge reports each word stripped bare, so nothing downstream can tell where a
    sentence ended -- and captions that break mid-clause are the difference
    between text you read and text you trip over. Walking the two lists together
    and copying the original token back restores it; a word that fails to line
    up is left alone rather than guessed at.
    """
    tokens = text.split()
    i = 0
    for w in words:
        bare = _bare(w["text"])
        for j in range(i, min(i + 4, len(tokens))):
            if _bare(tokens[j]) == bare:
                w["text"] = tokens[j]
                i = j + 1
                break
    return words


def speak(text, d, index, voice, rate):
    """Narration wav plus per-word timings, both cached."""
    tts = d / "tts"
    tts.mkdir(exist_ok=True)
    key = hashlib.sha1(f"{voice}|{rate}|{text}".encode()).hexdigest()[:16]
    mp3 = tts / f"{key}.mp3"
    meta = tts / f"{key}.words.json"
    wav = tts / f"{key}.wav"

    words = load_json(meta)
    if words is None or not mp3.exists():
        print(f"    speaking with {voice} ...")
        words = asyncio.run(_speak(text, voice, rate, mp3))
        save_json(meta, words)

    if not wav.exists():
        # Edge pads roughly a second of silence onto the front of every clip.
        # Left in, the reel opens on dead air and every caption sits a beat late,
        # so cut to just before the first word and slide the timings to match.
        lead = max(0.0, (words[0]["start"] - 0.15) if words else 0.0)
        ffmpeg_cached(wav, "-ss", f"{lead:.3f}", "-i", mp3,
                      "-ac", "1", "-ar", str(SAMPLE_RATE))
        if lead:
            for w in words:
                w["start"] = round(max(0.0, w["start"] - lead), 3)
                w["end"] = round(max(0.05, w["end"] - lead), 3)
            save_json(meta, words)

    return wav, expand_to_words(words, text, duration_of(wav))


def caption_chunks(words, per_chunk, max_chars=24):
    """Group words into the short bursts that read cleanly on a phone.

    Each chunk holds the screen until the next one starts, so there is never a
    gap where the narrator is talking to an empty frame.
    """
    chunks, buf = [], []
    for w in words:
        buf.append(w)
        text = " ".join(x["text"] for x in buf)
        if len(buf) >= per_chunk or len(text) >= max_chars or w["text"].endswith(
                (".", "?", "!", ",", ";", ":")):
            chunks.append({"start": buf[0]["start"], "end": buf[-1]["end"], "text": text})
            buf = []
    if buf:
        chunks.append({"start": buf[0]["start"], "end": buf[-1]["end"],
                       "text": " ".join(x["text"] for x in buf)})

    for i, c in enumerate(chunks):
        c["text"] = c["text"].strip()
        if i + 1 < len(chunks):
            c["end"] = max(c["end"], chunks[i + 1]["start"])
    return [c for c in chunks if c["text"]]


# ---------------------------------------------------------------- 6. captions


# Where a bold sans-serif lives on each platform. Pillow draws the captions
# because this ffmpeg is built without libass and freetype, so there is no
# subtitles, ass or drawtext filter to hand the job to -- and doing it here
# means the result looks identical on macOS and Windows.
FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Black.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/HelveticaNeue.ttc",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "C:/Windows/Fonts/ariblk.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]


def find_font(explicit=None):
    for c in ([explicit] if explicit else []) + FONT_CANDIDATES:
        if c and Path(c).exists():
            return c
    return None


def caption_video(chunks, duration, d, index, font_path, size_frac, color):
    """Render the captions once, as a transparent video to overlay in one pass.

    One overlay filter per caption would mean a hundred-odd inputs on a single
    ffmpeg command line for a two-minute reel. Baking them into one alpha clip
    (qtrle, which is lossless with a real alpha channel) keeps the render to a
    single overlay no matter how much is said.
    """
    from PIL import Image, ImageDraw, ImageFont

    out = d / f"captions-{index:02d}.mov"
    if out.exists():
        return out
    if not chunks or not font_path:
        return None

    pngs = d / f"cappng-{index:02d}"
    if pngs.exists():
        shutil.rmtree(pngs)
    pngs.mkdir(parents=True)

    size = max(24, int(REEL_H * size_frac))
    font = ImageFont.truetype(font_path, size)
    line_h = int(size * 1.18)
    strip_h = line_h * 2 + int(size * 0.6)
    strip_h += strip_h % 2
    chars = max(10, int(REEL_W * 0.86 / (size * 0.56)))
    stroke = max(4, size // 8)

    blank = pngs / "blank.png"
    Image.new("RGBA", (REEL_W, strip_h), (0, 0, 0, 0)).save(blank)

    def draw_chunk(i, text):
        p = pngs / f"{i:04d}.png"
        img = Image.new("RGBA", (REEL_W, strip_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        lines = wrap(text.upper(), width=chars).split("\n")[:2]
        y = (strip_h - line_h * len(lines)) // 2
        for ln in lines:
            draw.text((REEL_W // 2, y), ln, font=font, fill=color,
                      stroke_width=stroke, stroke_fill=(0, 0, 0, 255), anchor="ma")
            y += line_h
        img.save(p)
        return p

    # A concat list of stills with explicit durations, transparent where nobody
    # is speaking, so the alpha clip covers the reel end to end.
    entries, t = [], 0.0
    for i, c in enumerate(chunks):
        start = max(t, min(c["start"], duration))
        end = max(min(c["end"], duration), start + 0.2)
        if start > t + 0.04:
            entries.append((blank, start - t))
        if start >= duration:
            break
        entries.append((draw_chunk(i, c["text"]), end - start))
        t = end
    if t < duration:
        entries.append((blank, duration - t))

    listing = pngs / "list.txt"
    body = "".join(f"file '{p.name}'\nduration {dur:.3f}\n" for p, dur in entries)
    body += f"file '{entries[-1][0].name}'\n"       # concat needs the tail repeated
    listing.write_text(body, encoding="utf-8")

    ffmpeg_cached(out, "-f", "concat", "-safe", "0", "-i", str(listing),
                  "-fps_mode", "cfr", "-r", str(FPS),
                  "-c:v", "qtrle", "-pix_fmt", "argb")
    shutil.rmtree(pngs, ignore_errors=True)
    return out


def write_srt(chunks, path):
    blocks = []
    for i, c in enumerate(chunks, 1):
        end = max(c["end"], c["start"] + 0.3)
        blocks.append(f"{i}\n{srt_time(c['start'])} --> {srt_time(end)}\n"
                      f"{wrap(c['text'], width=32)}\n")
    path.write_text("\n".join(blocks), encoding="utf-8")


# ---------------------------------------------------------------- 7. audio bed


def background_bed(clip_audio, d, index, model):
    """Demucs splits the clip into voice and everything else; keep the rest.

    Run per reel rather than on the source, because separating ten minutes of
    clips on a CPU takes minutes and separating a two-hour film takes hours for
    audio that is then thrown away.
    """
    bed = d / f"bed-{index:02d}.wav"
    if bed.exists():
        print("    cached background bed")
        return bed

    tmp = d / f"demucs-{index:02d}"
    print("    removing dialogue with Demucs (slow on CPU) ...")
    try:
        run([sys.executable, "-m", "demucs", "--two-stems", "vocals",
             "-n", model, "-o", str(tmp), str(clip_audio)])
    except (subprocess.CalledProcessError, FileNotFoundError):
        shutil.rmtree(tmp, ignore_errors=True)
        sys.exit(
            "Demucs could not run, so the dialogue cannot be removed.\n"
            "  If you installed from requirements-lite.txt, that is expected --\n"
            "  Demucs and torch are the big downloads it leaves out. Either:\n"
            "    * add --no-bg to drop the original audio instead, or\n"
            "    * install the full set:  pip install -r requirements.txt")
    produced = next(tmp.rglob("no_vocals.wav"), None)
    if produced is None:
        shutil.rmtree(tmp, ignore_errors=True)
        sys.exit("Demucs produced no output; re-run with --no-bg to skip it.")
    shutil.move(str(produced), bed)
    shutil.rmtree(tmp, ignore_errors=True)
    return bed


def mix(bed, voice, d, index, bg_gain):
    """Narration on top, the music and effects ducked underneath it."""
    out = d / f"audio-{index:02d}.m4a"
    if out.exists():
        return out
    if bed is None:
        return ffmpeg_cached(
            out, "-i", voice, "-af",
            "aformat=channel_layouts=stereo,loudnorm=I=-14:TP=-1.5:LRA=11",
            "-c:a", "aac", "-b:a", "192k")

    # apad, then duration=first, because sidechaincompress stops the moment its
    # shorter input ends. Without the padding a narration that finishes early
    # takes the music with it, and the reel ends on the last word instead of
    # running to the length the picture was cut to.
    return ffmpeg_cached(
        out, "-i", bed, "-i", voice, "-filter_complex",
        f"[0:a]aformat=channel_layouts=stereo,aresample={SAMPLE_RATE},"
        f"volume={bg_gain}[bg];"
        f"[1:a]aformat=channel_layouts=stereo,aresample={SAMPLE_RATE},"
        "apad,asplit=2[v1][v2];"
        "[bg][v1]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=400[duck];"
        "[duck][v2]amix=inputs=2:normalize=0:duration=first[m];"
        "[m]loudnorm=I=-14:TP=-1.5:LRA=11[out]",
        "-map", "[out]", "-c:a", "aac", "-b:a", "192k")


# ---------------------------------------------------------------- 8. render


def vertical_chain(crop, fit, band=None):
    """Steps that turn a wide frame into a 1080x1920 one, ending at [v].

    blur keeps the whole frame and fills the dead space with a blown-up blurred
    copy of itself, which is what you want for anything widescreen -- a centre
    crop of a 2.39:1 shot throws away most of the composition. crop is there for
    footage that was already shot tight.

    band, when given, is where subtitles are burned into the source picture, in
    the source's own coordinates. Those pixels get blurred away before any
    reframing, so the narration's captions are the only text on screen.

    Returned as a list of statements rather than one string: each step names its
    output, so the next one starts from a label and nothing has to guess whether
    a comma or a label join is needed.
    """
    cw, ch, cx, cy = crop
    steps = [f"[0:v]crop={cw}:{ch}:{cx}:{cy}[src]"]
    cur = "[src]"

    if band:
        # The band was measured on the full frame; the letterbox crop has since
        # moved the origin, so shift it and clamp it into what is left.
        y0 = max(0, band[0] - cy)
        y1 = min(ch, band[1] - cy)
        bh = y1 - y0
        if bh > 4:
            steps.append(f"{cur}split=2[base][strip]")
            # Smeared sideways much harder than it is vertically: a line of text
            # is destroyed by dragging it along its own direction, where an even
            # blur strong enough to do the same would turn the strip to mush.
            # Then darkened a little so anything drawn on top stays readable.
            steps.append(f"[strip]crop=iw:{bh}:0:{y0},"
                         f"gblur=sigma={max(28, bh)}:sigmaV={max(8, bh // 3)},"
                         f"eq=brightness=-0.16[blurred]")
            steps.append(f"[base][blurred]overlay=0:{y0}[covered]")
            cur = "[covered]"

    if fit == "crop":
        steps.append(f"{cur}scale={REEL_W}:{REEL_H}:force_original_aspect_ratio=increase,"
                     f"crop={REEL_W}:{REEL_H},setsar=1[v]")
    else:
        steps.append(f"{cur}split=2[a][b]")
        steps.append(f"[a]scale={REEL_W}:{REEL_H}:force_original_aspect_ratio=increase,"
                     f"crop={REEL_W}:{REEL_H},gblur=sigma=42,"
                     f"eq=brightness=-0.22:saturation=0.9[bg]")
        steps.append(f"[b]scale={REEL_W}:-2[fg]")
        steps.append(f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1[v]")
    return steps


def caption_y_for(crop, fit, strip_h, explicit):
    """Where the caption strip sits, measured in pixels from the top.

    Left to a fixed fraction, captions straddle the bottom edge of the picture
    on anything widescreen -- half the text over the frame, half over the blur.
    Working it out from the frame's own height instead drops the strip just
    below the picture, which is where these reels put it, and still clears the
    bottom of the screen where a platform's own UI sits.
    """
    if explicit is not None:
        return max(0, min(int(REEL_H * explicit), REEL_H - strip_h))
    if fit == "crop":
        y = int(REEL_H * 0.62)
    else:
        cw, ch, _, _ = crop
        picture_h = REEL_W * ch / max(cw, 1)      # height once scaled to width
        y = int((REEL_H + min(picture_h, REEL_H)) / 2) + 28
    return max(0, min(y, REEL_H - strip_h - 70))


def render(video, span, audio, captions, srt, out, crop, a, band=None):
    """Cut, reframe, burn the captions on, and encode the finished reel.

    The same English text goes in twice on purpose: burned into the picture, so
    it survives being watched muted in a feed, and again as a real subtitle
    track, so a player can turn it off and a platform can read it.
    """
    dur = span["end"] - span["start"]
    chain = vertical_chain(crop, a.fit, band)
    last = "[v]"

    # Input 0 is the picture and 1 the audio; anything after that is numbered as
    # it is added, because either of the next two can be absent.
    inputs, nxt = [], 2
    if captions:
        inputs += ["-i", str(captions)]
        y = caption_y_for(crop, a.fit, video_size(captions)[1], a.caption_y)
        chain.append(f"[v][{nxt}:v]overlay=0:{y}:shortest=0:eof_action=pass[vc]")
        last = "[vc]"
        nxt += 1

    subs = []
    if srt:
        inputs += ["-i", str(srt)]
        subs = ["-map", f"{nxt}:s:0", "-c:s", "mov_text",
                "-metadata:s:s:0", "language=eng",
                "-metadata:s:s:0", "title=English"]
        nxt += 1

    codec = ["-c:v", "h264_videotoolbox", "-b:v", "6M"] if a.fast else [
        "-c:v", "libx264", "-preset", "medium", "-crf", "20"]

    # Fast-seek before -i so a pick an hour into a film does not decode the hour
    # before it; -t after so the length is measured from the seek point. The
    # output gets its own -t rather than -shortest, which would otherwise end
    # the reel at the last subtitle cue instead of at the last frame.
    ffmpeg_cached(
        out,
        "-ss", f"{span['start']:.3f}", "-t", f"{dur:.3f}", "-i", str(video),
        "-i", str(audio), *inputs,
        "-filter_complex", ";".join(chain),
        "-map", last, "-map", "1:a:0", *subs,
        "-r", str(FPS), "-pix_fmt", "yuv420p", *codec,
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
        "-t", f"{dur:.3f}")
    return out


# ---------------------------------------------------------------- driver


def list_voices():
    import edge_tts

    voices = asyncio.run(edge_tts.list_voices())
    print("Suggested (the conversational ones):")
    for v in SUGGESTED_VOICES:
        print(f"  {v}")
    print("\nAll English voices:")
    for v in sorted(voices, key=lambda v: v["ShortName"]):
        if v["Locale"].startswith("en"):
            print(f"  {v['ShortName']:<40} {v['Gender']:<7} {v['Locale']}")


def prepare(target, a, progress=None, with_scripts=True, need_video=True):
    """Everything up to the point where the narration scripts exist.

    Split from the rendering on purpose: the scripts are the part worth reading
    before an hour of encoding starts, so this stops there and hands them back.
    Nothing here is slow enough to regret, and all of it is cached.
    """
    def step(frac, desc):
        if progress:
            progress(frac, desc)

    url = normalize_url(target)
    d = WORK / hashlib.sha1(url.encode()).hexdigest()[:12]
    d.mkdir(parents=True, exist_ok=True)

    print("\n[1/4] source")
    if need_video:
        step(0.05, "Fetching the video")
        video, title, _ = fetch(url, d, a.max_height)
        total = duration_of(video)
    else:
        step(0.05, "Fetching the transcript")
        video, title, total = fetch_meta(url, d)
    print(f"  {title}  ({hhmmss(total)})")
    if video is None:
        print("  transcript only -- the video itself has not been downloaded")

    print("\n[2/4] transcript")
    step(0.30, "Reading the transcript")
    source_for_speech = video
    if source_for_speech is None and not caption_files(d):
        trouble = CAPTION_TROUBLE.get(str(d), "")
        if trouble == "rate-limited":
            print("  ! YouTube rate-limited the caption request (HTTP 429).\n"
                  "    That is temporary and says nothing about this video --\n"
                  "    waiting ten minutes and running again usually fixes it.")
        else:
            print("  ! No captions came back for this video.")
        print("    Falling back to transcribing it here, which means\n"
              "    downloading the audio (often a few hundred MB) and running\n"
              "    Whisper over it. On a feature-length video that is slow.\n"
              "    Ctrl+C now if you would rather wait and retry.")
        source_for_speech = download_audio(url, d)
    lines = transcript(source_for_speech, d, a.whisper_model)

    print("\n[3/4] picking the best stretches")
    step(0.55, "Scoring the runtime and picking the best stretches")
    mode = "best" if a.highlights else "story"
    cache = d / f"spans-{mode}-{a.reels}-{a.duration}.json"
    spans = load_json(cache)
    if spans is None:
        if video is None:
            # No picture to score or to find shot changes in, so go on the
            # transcript alone and leave the spans marked for snapping later.
            score, seconds, tot = transcript_score(lines, total, a.skip_start,
                                                   a.skip_end)
            if a.highlights:
                spans = best_windows(score, seconds, tot, a.reels, a.duration, a.gap)
            else:
                spans = story_chapters(score, seconds, tot, a.reels, a.duration,
                                       a.skip_start, a.skip_end)
        elif a.highlights:
            spans = pick_highlights(video, lines, d, a.reels, a.duration, a.gap,
                                    a.skip_start, a.skip_end)
        else:
            spans = story_spans(video, lines, d, a.reels, a.duration,
                                a.skip_start, a.skip_end)
        save_json(cache, spans)
    for i, s in enumerate(spans, 1):
        if not a.highlights:
            print(f"  part {i:02d}  narrates {hhmmss(s['narr_start'])} - "
                  f"{hhmmss(s['narr_end'])}, shows "
                  f"{hhmmss(s['start'])} - {hhmmss(s['end'])}")
        else:
            preview = " ".join(clean_line(ln["text"])
                               for ln in lines_in(lines, s))[:100]
            print(f"  reel {i:02d}  {hhmmss(s['start'])} - {hhmmss(s['end'])}"
                  f"   {preview}")

    out_dir = OUTPUT / slugify(title)
    scripts_dir = out_dir / "scripts"
    ctx = {"url": url, "d": d, "video": video, "title": title, "total": total,
           "lines": lines, "spans": spans, "out_dir": out_dir,
           "scripts_dir": scripts_dir, "scripts": [], "spans_cache": cache}
    if not with_scripts:
        return ctx

    print("\n[4/4] narration scripts")
    ctx["titles"] = []
    told = []
    for i, span in enumerate(spans, 1):
        step(0.60 + 0.38 * (i - 1) / len(spans),
             f"Writing narration {i} of {len(spans)}")
        print(f"  reel {i:02d}")
        # Only the tail of the story so far is carried forward. It is there to
        # stop the next part re-introducing everyone, and a whole film's worth
        # of it would crowd out the transcript the model actually has to work
        # from.
        previous = " ".join(told)[-1500:] if told else None
        title, text = narration_for(lines, span, span["end"] - span["start"],
                                    a, i, scripts_dir, previous=previous,
                                    is_last=(i == len(spans)))
        ctx["scripts"].append(text)
        ctx["titles"].append(title)
        if text:
            told.append(text)
    step(1.0, "Scripts ready")
    return ctx


def write_script(scripts_dir, index, title, text):
    """Save one script, keeping its title as the leading # comment."""
    Path(scripts_dir).mkdir(parents=True, exist_ok=True)
    body = (text or "").strip()
    head = f"# {title}\n\n" if title and body else ""
    path = Path(scripts_dir) / f"reel-{index:02d}.txt"
    path.write_text(head + body, encoding="utf-8")
    return path


def story_so_far(scripts_dir, index):
    """The tail of the parts before this one, for continuity."""
    told = []
    for i in range(1, index):
        path = Path(scripts_dir) / f"reel-{i:02d}.txt"
        if path.exists():
            _, text = split_script(path.read_text(encoding="utf-8"))
            if text:
                told.append(text)
    return (" ".join(told)[-1500:]) if told else None


def regenerate_script(ctx, a, index):
    """Write one reel's script again, from scratch.

    Deletes it first, because the generator reads an existing file back
    verbatim -- that is what makes hand edits stick, and it would otherwise make
    rewriting impossible.
    """
    scripts_dir = Path(ctx["scripts_dir"])
    (scripts_dir / f"reel-{index:02d}.txt").unlink(missing_ok=True)
    span = ctx["spans"][index - 1]
    return narration_for(ctx["lines"], span, span["end"] - span["start"], a,
                         index, scripts_dir,
                         previous=story_so_far(scripts_dir, index),
                         is_last=(index == len(ctx["spans"])))


def build(ctx, a, progress=None, only=None):
    """Render the reels from an already-prepared job.

    The scripts are read off disk again rather than taken from ctx, so anything
    edited in between -- by hand or through the web page -- is what gets spoken.
    """
    def step(frac, desc):
        if progress:
            progress(frac, desc)

    video, d, spans = ctx["video"], ctx["d"], ctx["spans"]
    lines, total = ctx["lines"], ctx["total"]
    out_dir, scripts_dir = ctx["out_dir"], ctx["scripts_dir"]

    if video is None:
        # The scripts were written from the transcript alone. Everything from
        # here needs the picture, so this is where it gets downloaded.
        step(0.005, "Fetching the video")
        video, _, _ = fetch(ctx["url"], d, a.max_height)
        ctx["video"] = video
        total = ctx["total"] = duration_of(video)

    if any(s.get("unsnapped") for s in spans):
        # These were chosen from the transcript, with no picture to score or to
        # find shot changes in.
        step(0.01, "Choosing the footage now the picture is here")
        if not a.highlights:
            # A recap's chapters are a fixed division of the runtime, so redoing
            # the pick returns the very same chapters -- and therefore still
            # matches the scripts already written against them. Only the minute
            # of footage inside each one changes, and it improves, because
            # loudness can be scored now as well as speech.
            for s, better in zip(spans, story_spans(video, lines, d, len(spans),
                                                    a.duration, a.skip_start,
                                                    a.skip_end)):
                s.update(better)
        else:
            # Highlight picks are not reproducible from the runtime alone, so
            # re-picking them would leave the scripts describing other moments.
            # Move them onto a shot change and otherwise leave them be.
            for s in spans:
                length = s["end"] - s["start"]
                s["start"] = round(snap_to_cut(video, s["start"], d), 2)
                s["end"] = round(min(s["start"] + length, total), 2)
        for s in spans:
            s.pop("unsnapped", None)
        save_json(ctx["spans_cache"], spans)

    step(0.02, "Looking at the picture")
    crop = detect_letterbox(video, d)
    band = detect_caption_band(video, d) if a.cover_captions else None
    font = find_font(a.font)
    if not font and not a.no_burn:
        print("  no bold font found, so nothing will be drawn into the picture "
              "(pass --font /path/to/font.ttf). The English subtitle track and "
              ".srt are written either way.")

    out_dir.mkdir(parents=True, exist_ok=True)
    made = []

    for i, span in enumerate(spans, 1):
        if only and i not in only:
            continue
        print(f"\nreel {i:02d} of {len(spans)}  "
              f"({hhmmss(span['start'])} - {hhmmss(span['end'])})")
        # The bar is split evenly between the reels, leaving a sliver at the
        # front for the one-off look at the picture.
        base = 0.03 + 0.95 * (i - 1) / len(spans)
        span_frac = 0.95 / len(spans)
        step(base, f"Reel {i} of {len(spans)}: reading the narration")
        title, text = narration_for(lines, span, span["end"] - span["start"], a, i,
                                    scripts_dir)
        if not text:
            print("    nothing said in this stretch; skipping")
            continue

        step(base + span_frac * 0.15, f"Reel {i} of {len(spans)}: speaking it")
        voice_wav, words = speak(text, d, i, a.voice, a.rate)
        narr = duration_of(voice_wav)

        # The narration decides the reel's length, not the other way round: a
        # clip that outlives its script ends on silence, and one that ends early
        # cuts the narrator off mid-sentence.
        span = dict(span)
        span["end"] = min(span["start"] + max(min(narr + a.tail, a.max_duration),
                                              a.min_duration), total)
        dur = span["end"] - span["start"]
        print(f"    narration {narr:.1f}s -> reel {dur:.1f}s")

        clip_audio = d / f"clip-{i:02d}.wav"
        bed = None
        if not a.no_bg:
            step(base + span_frac * 0.30,
                 f"Reel {i} of {len(spans)}: removing the dialogue (slow)")
            if not clip_audio.exists():
                ffmpeg_cached(clip_audio, "-ss", f"{span['start']:.3f}",
                              "-t", f"{dur:.3f}", "-i", str(video), "-vn",
                              "-ac", "2", "-ar", str(SAMPLE_RATE))
            bed = background_bed(clip_audio, d, i, a.demucs_model)

        print("    mixing and captioning")
        step(base + span_frac * 0.70, f"Reel {i} of {len(spans)}: mixing and captioning")
        audio = mix(bed, voice_wav, d, i, a.bg_gain)
        # The text is grouped whether or not it gets burned in: the subtitle
        # track needs no font, only the timings.
        chunks = caption_chunks(words, a.caption_words)
        caps = None
        if not a.no_burn:
            caps = caption_video(
                chunks, dur, d, i, font, a.caption_size,
                tuple(int(x) for x in a.caption_color.split(",")) + (255,))

        print("    encoding")
        step(base + span_frac * 0.82, f"Reel {i} of {len(spans)}: encoding")
        out = out_dir / f"reel-{i:02d}.mp4"
        # Written before the encode, not after: it is muxed in as a subtitle
        # track as well as left beside the reel for uploading.
        srt = out_dir / f"reel-{i:02d}.srt"
        if chunks:
            write_srt(chunks, srt)
        else:
            srt.unlink(missing_ok=True)
            srt = None
        render(video, span, audio, caps, srt, out, crop, a, band)
        made.append({"file": out.name, "title": title,
                     "source_start": span["start"],
                     "source_end": round(span["end"], 2), "seconds": round(dur, 1),
                     "narration": text})
        print(f"  -> {out}")

    if made:
        save_json(out_dir / "manifest.json",
                  {"title": ctx["title"], "source": ctx["url"], "reels": made})
    plural = "reel" if len(made) == 1 else "reels"
    step(1.0, f"Done: {len(made)} {plural}")
    print(f"\nDone: {len(made)} {plural} in {out_dir}")
    skipped = (len(only) if only else len(spans)) - len(made)
    if skipped:
        print(f"  {skipped} skipped for having an empty script -- write those in "
              f"{scripts_dir} and run again")
    print(f"  cache now holds {human_size(dir_size(WORK))}. "
          f"Run with --clean to free it.")
    return out_dir, made


def make_reels(target, a, progress=None):
    """Prepare and build in one go, for the command line.

    The two halves get their own slice of the progress bar; preparing is a small
    fraction of the work, however long the download takes.
    """
    def slice_of(lo, hi):
        if not progress:
            return None
        return lambda frac, desc: progress(lo + (hi - lo) * frac, desc)

    # Neither planning nor writing scripts needs the picture, so those fetch the
    # captions and stop -- seconds and a few kilobytes instead of a download
    # that can run to gigabytes.
    light = a.plan or a.scripts
    ctx = prepare(target, a, slice_of(0.0, 0.15), with_scripts=not a.plan,
                  need_video=not light)

    if a.plan:
        print("\n--plan: nothing rendered. Re-run without it to build these.")
        return None, []

    if a.scripts:
        print(f"\nScripts written to {ctx['scripts_dir']}")
        empty = 0
        titles = ctx.get("titles") or [None] * len(ctx["scripts"])
        for i, (text, title) in enumerate(zip(ctx["scripts"], titles), 1):
            if text:
                print(f"  reel-{i:02d}.txt   {len(text.split())} words"
                      + (f"   {title}" if title else ""))
            else:
                empty += 1
                print(f"  reel-{i:02d}.txt   empty -- write this one yourself "
                      f"or the reel is skipped")
        print("\nRead them, edit whichever you want to rewrite, then run the "
              "same command again without --scripts to build the reels.")
        if ctx["video"] is None:
            print("The video itself has not been downloaded yet -- that happens "
                  "on the build run.")
        if empty:
            print("An empty script means that stretch had no speech to work from.")
        return ctx["out_dir"], []

    return build(ctx, a, slice_of(0.15, 1.0))


def build_parser():
    """Every setting, in one place.

    Kept out of main() so the web page can take its defaults from here rather
    than keeping a second copy of them that quietly drifts out of step.
    """
    p = argparse.ArgumentParser(
        description="Turn a long video into narrated vertical reels.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("url", nargs="?", help="YouTube URL, video id, or a local video file")
    p.add_argument("--reels", type=int, default=7, help="how many to cut (default 7)")
    p.add_argument("--duration", type=int, default=75,
                   help="seconds to aim at per reel (default 75)")
    p.add_argument("--min-duration", type=float, default=30.0)
    p.add_argument("--max-duration", type=float, default=170.0,
                   help="hard ceiling; Shorts and Reels both cut off at 3 min")
    p.add_argument("--tail", type=float, default=0.7,
                   help="seconds of picture left after the last word (default 0.7)")
    p.add_argument("--gap", type=float, default=180.0,
                   help="minimum seconds between two picks (default 180)")
    p.add_argument("--skip-start", type=float, default=0.03,
                   help="fraction of the runtime to ignore at the head (default 0.03)")
    p.add_argument("--skip-end", type=float, default=0.06,
                   help="fraction to ignore at the tail, for credits (default 0.06)")

    p.add_argument("--script", choices=["auto", "extractive", "ollama"],
                   default="auto",
                   help="how to write the narration: auto uses a local Ollama "
                        "model when one is running and falls back to picking "
                        "lines out of the transcript when none is")
    p.add_argument("--style", choices=sorted(STYLES), default=DEFAULT_STYLE,
                   help="how the narration is written: "
                        + "; ".join(f"{k} = {v['label']}"
                                    for k, v in sorted(STYLES.items())))
    p.add_argument("--style-file",
                   help="a text file describing how to write, used instead of "
                        "--style")
    p.add_argument("--model", default="llama3.2", help="Ollama model for --script ollama")
    p.add_argument("--ollama-host", default="http://127.0.0.1:11434")

    p.add_argument("--voice", default=DEFAULT_VOICE)
    p.add_argument("--rate", default="+0%", help="speaking rate, e.g. +10%%")
    p.add_argument("--list-voices", action="store_true")

    p.add_argument("--fit", choices=["blur", "crop"], default="blur",
                   help="blur keeps the whole frame, crop fills the screen")
    p.add_argument("--caption-words", type=int, default=3,
                   help="words per caption burst (default 3)")
    p.add_argument("--caption-size", type=float, default=0.045,
                   help="caption height as a fraction of the frame (default 0.045)")
    p.add_argument("--caption-y", type=float, default=None,
                   help="where the caption strip sits, 0 top 1 bottom "
                        "(default: just under the picture)")
    p.add_argument("--caption-color", default="255,255,255", help="R,G,B")
    p.add_argument("--font", help="path to a .ttf if none is found automatically")

    p.add_argument("--no-burn", action="store_true",
                   help="leave the picture clean: English stays as a subtitle "
                        "track and a .srt, but is not drawn into the frame")
    p.add_argument("--cover-captions", action="store_true",
                   help="blur away subtitles burned into the source picture "
                        "before drawing the narration's own captions")
    p.add_argument("--no-bg", action="store_true",
                   help="drop the original audio entirely (skips Demucs, much faster)")
    p.add_argument("--bg-gain", type=float, default=0.55,
                   help="how loud the music/SFX bed sits (default 0.55)")
    p.add_argument("--demucs-model", default="htdemucs",
                   help="htdemucs is best, mdx_extra_q is faster")
    p.add_argument("--whisper-model", default="small",
                   help="only used when the video has no captions at all")
    p.add_argument("--max-height", type=int, default=1080)
    p.add_argument("--fast", action="store_true",
                   help="hardware encoder: much quicker, slightly softer picture")
    p.add_argument("--plan", action="store_true",
                   help="print the stretches that would be cut, render nothing")
    p.add_argument("--highlights", action="store_true",
                   help="separate best moments that do not connect to each "
                        "other. The default instead makes a recap series: "
                        "consecutive parts telling the story in order, each "
                        "carrying on from the last")
    p.add_argument("--scripts", action="store_true",
                   help="download only the transcript, write the narration "
                        "scripts and stop -- so you can read and edit them "
                        "before the video is ever fetched")
    p.add_argument("--clean", action="store_true",
                   help="delete the working cache (the downloaded video and "
                        "intermediates) and exit; your reels are not touched")
    return p


def main():
    p = build_parser()
    a = p.parse_args()

    if a.clean:
        clean_cache()
        return
    if a.list_voices:
        list_voices()
        return
    if not a.url:
        p.error("give me a YouTube URL or a local video file")
    if a.duration > a.max_duration:
        a.max_duration = float(a.duration)

    WORK.mkdir(exist_ok=True)
    OUTPUT.mkdir(exist_ok=True)
    make_reels(a.url, a)


if __name__ == "__main__":
    main()
