# youtube-reels

Turn one long video into 5–10 vertical shorts, ready to upload.

Give it a link. It picks the best stretches of the video, **removes the voices of
the people talking**, keeps the music and sound effects, puts an **AI narrator**
over the top, and burns **karaoke captions** into a 1080×1920 frame.

Everything is free. **There are no API keys anywhere in this project** — no
Claude, no OpenAI, nothing to sign up for and nothing to pay for. The pipeline
runs on your own machine; the one step that reaches the internet is the narrator
voice, which uses Microsoft's free Edge voices (no account, no key).

```bash
./run.sh "https://www.youtube.com/watch?v=XXXX" --plan   # see what it would cut
./run.sh "https://www.youtube.com/watch?v=XXXX"          # build the reels
```

Or use the web page, and send the link to someone else:

```bash
./serve.sh --share --password hunter2
```

---

## Contents

- [What you get](#what-you-get)
- [How it works](#how-it-works)
- [Install — Windows](#install--windows)
- [Install — macOS](#install--macos)
- [Install — Linux](#install--linux)
- [Using it from the command line](#using-it-from-the-command-line)
- [Using the web page](#using-the-web-page)
- [Sharing it with other people](#sharing-it-with-other-people)
- [Getting better results](#getting-better-results)
- [Narration](NARRATION.md) — what you need, and how to make it good
- [All the options](#all-the-options)
- [How long it takes](#how-long-it-takes)
- [Troubleshooting](#troubleshooting)
- [Putting it on GitHub](#putting-it-on-github)
- [Notes and limits](#notes-and-limits)

---

## What you get

Everything lands in `output/<video title>/`:

```
reel-01.mp4     1080x1920, captions burned in, plus an English subtitle track
reel-01.srt     the same subtitles as a file, for uploading
reel-01.txt     the narration script it wrote
reel-02.mp4     ...and so on
manifest.json   which part of the source each reel came from
```

Each reel carries the narration **three ways**, because each is needed somewhere
different:

- **Burned into the picture** — still readable when a feed autoplays on mute.
- **A subtitle track inside the `.mp4`** — viewers can switch it off.
- **A `.srt` file** — what YouTube, Instagram and TikTok want when you upload
  captions by hand.

The timings are not guessed. The voice reports exactly when it says each word,
so the captions land on the syllable.

---

## How it works

1. **Downloads** the video with `yt-dlp`, and **YouTube's own transcript** with
   it. That transcript is the point: a two-hour film does not have to be
   transcribed from scratch first. If the video has no captions at all, Whisper
   runs locally as a fallback — accurate, but slow.
2. **Scores the whole runtime** second by second, on how loud it is and how much
   is being said, then picks the best stretches, keeping them far enough apart
   that they do not all come from the same ten minutes.
3. **Snaps each pick to the nearest scene cut**, so a reel never opens mid-shot.
4. **Writes a narration script** for each stretch from that stretch's transcript.
5. **Speaks it** with a free Microsoft Edge neural voice.
6. **Removes the dialogue** with Demucs, which splits the audio into *voice* and
   *everything else* and keeps everything else. The music and effects survive;
   the people talking do not. That bed then ducks automatically under the
   narrator.
7. **Reframes to 1080×1920**, cropping off letterbox bars first, burns the
   captions on, and encodes.

Work is cached in `work/`, so a second run only redoes what changed. Stopping a
run part-way is safe.

---

## Install — Windows

**You need three things first.** Install them in this order.

### 1. Python 3.11

Download it from
[python.org/downloads/release/python-3119](https://www.python.org/downloads/release/python-3119/)
— scroll to the bottom and pick **Windows installer (64-bit)**.

> **In the installer, tick "Add python.exe to PATH" on the first screen.**
> This is the single most common thing to get wrong. If you miss it, nothing
> below will work.

Python **3.11 specifically**, not 3.12 or 3.13 — one of the libraries this uses
(`torch 2.2.2`) has no Windows build for anything newer.

### 2. Git

Download from [git-scm.com/download/win](https://git-scm.com/download/win) and
accept the defaults.

### 3. ffmpeg and yt-dlp

Open **PowerShell** and run:

```powershell
winget install --id Gyan.FFmpeg -e
winget install --id yt-dlp.yt-dlp -e
```

**Now close PowerShell and open a new window.** Windows only picks up the
changed PATH in new terminals — if you skip this, it will tell you ffmpeg is
missing even though you just installed it.

Check they are there:

```powershell
ffmpeg -version
yt-dlp --version
py -3.11 --version
```

### 4. Get the project and run it

```powershell
git clone https://github.com/YOUR-USERNAME/youtube-reels.git
cd youtube-reels
```

Then either **double-click `serve.bat`** in Explorer for the web page, or from
PowerShell:

```powershell
.\run.bat "https://www.youtube.com/watch?v=XXXX" --plan
```

The first run installs everything else by itself and takes several minutes.

> **Always put the link in double quotes.** YouTube links contain `&`, which
> Windows treats as "end of command" — without quotes you get a confusing error
> or the wrong video.

---

## Install — macOS

Install [Homebrew](https://brew.sh) if you do not have it, then:

```bash
brew install git ffmpeg yt-dlp python@3.11
git clone https://github.com/YOUR-USERNAME/youtube-reels.git
cd youtube-reels
chmod +x run.sh serve.sh
./run.sh "https://www.youtube.com/watch?v=XXXX" --plan
```

`run.sh` builds its own environment on the first run. If `ffmpeg`, `yt-dlp` or
Python 3.11 are missing it installs them for you.

---

## Install — Linux

Debian or Ubuntu:

```bash
sudo apt update
sudo apt install -y git ffmpeg yt-dlp python3.11 python3.11-venv fonts-dejavu-core
git clone https://github.com/YOUR-USERNAME/youtube-reels.git
cd youtube-reels
chmod +x run.sh serve.sh
./run.sh "https://www.youtube.com/watch?v=XXXX" --plan
```

If your release has no `python3.11` package:

```bash
sudo add-apt-repository ppa:deadsnakes/ppa && sudo apt update
sudo apt install -y python3.11 python3.11-venv
```

`fonts-dejavu-core` matters — without a font on disk the captions cannot be
drawn into the picture.

---

## Using it from the command line

macOS and Linux use `./run.sh`, Windows uses `.\run.bat`. **The arguments are
identical**; every example below works on both.

**Always start with `--plan`.** It prints the stretches it would cut and renders
nothing, which takes a couple of minutes instead of a couple of hours:

```bash
./run.sh "https://www.youtube.com/watch?v=XXXX" --plan
```

```
reel 01  0:14:22 - 0:15:37   the door had been locked from the inside...
reel 02  0:31:05 - 0:32:15   nobody at the table said anything for a while...
reel 03  0:58:40 - 0:59:55   he had been lying about the car the whole time...
```

Happy with those? Drop the flag and it builds them:

```bash
./run.sh "https://www.youtube.com/watch?v=XXXX"
```

More examples:

```bash
# ten short reels instead of seven medium ones
./run.sh "URL" --reels 10 --duration 45

# a fast first look: skips the slow dialogue-removal step
./run.sh "URL" --reels 2 --no-bg

# a different narrator, speaking slightly faster
./run.sh "URL" --voice en-US-BrianMultilingualNeural --rate "+8%"

# clean picture, subtitles you can switch off instead of burned-in captions
./run.sh "URL" --no-burn

# a file on your disk works anywhere a link does
./run.sh "C:\Users\me\Videos\movie.mp4" --reels 5     # Windows
./run.sh ~/Videos/movie.mp4 --reels 5                 # macOS / Linux

# every voice available
./run.sh --list-voices
```

---

## Using the web page

If you would rather click than type:

```bash
./serve.sh          # macOS / Linux
serve.bat           # Windows — or just double-click it
```

Your browser opens at `http://127.0.0.1:7861`. Paste a link or drop in a file,
pick how many reels you want, press the button. A progress bar shows which stage
it is on.

Nothing is uploaded anywhere — the page is just a front end for the same
pipeline, running on your machine.

---

## Sharing it with other people

### A temporary link (easiest)

```bash
./serve.sh --share --password hunter2
```

This prints a public `https://....gradio.live` link that anyone can open, lasting
up to a week. **The work still happens on your machine**, so it has to stay on
with the terminal open.

> Use `--password`. Without it, anyone who gets the link can queue jobs on your
> computer.

### A permanent link (Hugging Face Space)

Free, and it stays up without your machine running:

1. Create a Space at [huggingface.co/new-space](https://huggingface.co/new-space)
   — give it a name and choose the **Docker** SDK.
2. Deploy to it:

   ```bash
   ./hf-space/deploy.sh your-username/your-space-name
   ```

   When it asks for a password, paste an access token with **write** permission
   from [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens).

The first build takes several minutes, then your link is
`https://huggingface.co/spaces/your-username/your-space-name` and you can send it
to anyone.

Two honest caveats about the free tier:

- It is a **shared CPU**, so it is much slower than your own machine. Tell people
  to ask for 2 reels and untick *Keep the original music* for a first look.
- **YouTube links often fail there.** YouTube blocks downloads from datacenter
  addresses, which is what the Space has. Uploading a file always works.

---

## Getting better results

**Write better narration with a local model.** The default (`--script
extractive`) needs no download and picks out the most representative lines of
each stretch. It reads like a summary of what is said — because that is what it
is. That is the honest limit of doing this with no model at all.

For narration that actually reads like a recap, install
[Ollama](https://ollama.com) (free, local, no account):

```bash
ollama pull llama3.2
./run.sh "URL" --script ollama --model llama3.2
```

**This is the single biggest quality difference in the project.** If Ollama is
not running it quietly falls back to extractive rather than failing the render.

**Pick a voice you like.** `--list-voices` shows them all; the multilingual ones
sound the most natural and are listed first.

**You can also write the narration yourself.** Every script is cached as a plain
text file that the pipeline reads back verbatim, so you can rewrite one and
re-run to have it spoken and captioned. See **[NARRATION.md](NARRATION.md)** for
that workflow, choosing a voice, how reel length is decided, and what to do when
the narration comes out badly.

---

## All the options

| Flag | Does |
| --- | --- |
| `--plan` | show the stretches it would cut, render nothing |
| `--reels 7` | how many to cut (default 7) |
| `--duration 75` | seconds to aim at per reel (default 75) |
| `--gap 180` | minimum seconds between two picks, so they spread across the film |
| `--script ollama` | real narration from a local model instead of extractive |
| `--model llama3.2` | which Ollama model to use |
| `--voice` / `--rate` | which neural voice, and how fast it speaks |
| `--list-voices` | print every available voice |
| `--fit blur \| crop` | `blur` keeps the whole frame against a blurred fill (best for widescreen); `crop` fills the screen and throws the sides away |
| `--no-burn` | leave the picture clean: English stays as a subtitle track and a `.srt` |
| `--no-bg` | drop the original audio entirely. Skips Demucs — **much** faster, good for a first test |
| `--bg-gain 0.55` | how loud the music and effects sit under the narrator |
| `--caption-words 3` | words per caption burst |
| `--caption-size` / `--caption-color` / `--caption-y` | caption look and placement |
| `--font` | path to a `.ttf`, if none is found automatically |
| `--fast` | hardware encoder: quicker, slightly softer picture |
| `--whisper-model small` | only used when the video has no captions at all |

---

## How long it takes

**Demucs — the step that removes the voices — is the slow part**, and it runs on
the CPU. It is deliberately run **per reel** rather than across the whole film:
separating ten minutes of clips takes minutes, separating two hours takes hours
for audio that would be thrown away.

Rough shape of it on an ordinary laptop:

| Step | Time |
| --- | --- |
| Download + transcript | a few minutes |
| Picking the stretches | 1–3 minutes for a feature-length film |
| Per reel, without `--no-bg` | several minutes |
| Per reel, with `--no-bg` | well under a minute |

So: use `--plan` first, then `--no-bg` to check you like the framing and the
voice, and only then run it properly.

---

## Troubleshooting

**"ffmpeg is not recognised" on Windows, right after installing it.**
Close the terminal and open a new one. Windows only picks up PATH changes in new
windows.

**Windows says Python 3.11 was not found.**
You probably missed the "Add python.exe to PATH" tick box. Re-run the installer,
choose *Modify*, and enable it.

**The wrong video downloads, or you get a strange error on Windows.**
Put the link in double quotes: `"https://..."`. The `&` in YouTube links breaks
the command otherwise.

**`yt-dlp` fails with a bot check or "Sign in to confirm you're not a robot".**
Update it first — `yt-dlp -U` — since YouTube changes things often. On a server
or a Space this can happen no matter what; upload the file instead.

**Reels came out with no captions burned in.**
No TrueType font was found. Pass `--font` with a path to a `.ttf`, or on Linux
`sudo apt install fonts-dejavu-core`. The `.srt` and the subtitle track are
written either way.

**"only N well-separated stretches fit".**
`--gap` is keeping the picks apart and the video is not long enough for as many
as you asked for. Lower it: `--gap 90`.

**Your editor shows "package not installed" warnings.**
It is looking at your system Python, not the project's. Point it at
`.venv/bin/python` (or `.venv\Scripts\python.exe` on Windows).

---

## Putting it on GitHub

So other people can clone it:

```bash
cd youtube-reels
git init
git add .
git commit -m "Reel maker"
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/youtube-reels.git
git push -u origin main
```

Create the empty repository first at
[github.com/new](https://github.com/new), and do **not** let it add a README —
this one is already here.

`.venv/`, `work/` and `output/` are ignored, so none of the multi-gigabyte
generated files get pushed.

---

## Notes and limits

- **Copyright.** The tool is content-neutral, but re-uploading clips of a film
  you do not own is what gets channels struck, regardless of how they were
  edited. Use it on your own footage, or on material you have the rights to.
- **Demucs is not perfect.** Shouted or heavily processed dialogue can leave a
  faint trace in the background bed. Lower `--bg-gain`, or use `--no-bg` where it
  matters.
- **The narrator is only as good as the transcript.** A stretch with little
  speech gives the script generator almost nothing to work with, which is part of
  why stretches are scored on how much is being said.
- Captions are drawn with Pillow and overlaid as one transparent video, because
  the usual `subtitles` and `drawtext` filters need an ffmpeg built with libass —
  and many are not. Doing it this way looks identical on Windows, macOS and
  Linux.
- On Intel Macs, `torch` is pinned to 2.2.2 and `ctranslate2` below 4.5 — the
  last releases with x86_64 macOS wheels. `KMP_DUPLICATE_LIB_OK` is set in
  `reels.py` before anything loads, because torch and ctranslate2 each ship their
  own OpenMP and Intel's aborts the process when it sees both.
