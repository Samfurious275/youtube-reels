# youtube-reels

Turn one long video into 5–10 vertical shorts, ready to upload.

Give it a link. It picks the best stretches, **removes the voices of the people
talking**, keeps the music and sound effects, puts an **AI narrator** over the
top, and burns **karaoke captions** into a 1080×1920 frame.

It works in **two steps**, so you are never waiting an hour to find out you
hated the writing:

```bash
./run.sh "https://www.youtube.com/watch?v=XXXX" --scripts   # 1. read + edit the narration
./run.sh "https://www.youtube.com/watch?v=XXXX"             # 2. build the reels
```

Everything is free. **There are no API keys anywhere in this project** — no
Claude, no OpenAI, nothing to sign up for and nothing to pay for. The pipeline
runs on your own machine; the one step that reaches the internet is the narrator
voice, which uses Microsoft's free Edge voices (no account, no key).

---

## Contents

- [The commands you need](#the-commands-you-need) ← **start here**
- [What you get](#what-you-get)
- [How it works](#how-it-works)
- [Install — Windows](#install--windows)
- [Install — macOS](#install--macos)
- [Install — Linux](#install--linux)
- [Using the web page](#using-the-web-page)
- [Sharing it with other people](#sharing-it-with-other-people)
- [If disk space is tight](#if-disk-space-is-tight)
- [Narration](NARRATION.md) — what you need, and how to make it good
- [All the options](#all-the-options)
- [How long it takes](#how-long-it-takes)
- [Troubleshooting](#troubleshooting)
- [Putting it on GitHub](#putting-it-on-github)
- [Notes and limits](#notes-and-limits)

---

## The commands you need

macOS and Linux use `./run.sh`. Windows uses `.\run.bat`. **The arguments are
identical** — every example works on both, so only the first is shown twice.

> **Windows: always put the link in double quotes.** YouTube links contain `&`,
> which Windows reads as "end of command". Without quotes you get the wrong
> video or a confusing error.

### I want to see the narration scripts, and edit them before anything is made

```bash
./run.sh "URL" --scripts          # macOS / Linux
.\run.bat "URL" --scripts         # Windows
```

This downloads the video, picks the stretches, writes one script per reel, and
**stops**. The scripts land in `output/<video title>/scripts/`:

```
scripts/reel-01.txt   45 words
scripts/reel-02.txt   52 words
scripts/reel-03.txt   empty -- write this one yourself or the reel is skipped
```

Open them in any text editor (Notepad is fine), change whatever you like, save.
Then build with **the same command minus `--scripts`**:

```bash
./run.sh "URL"
```

It reads your edited files back **word for word** and speaks them. Delete a
script file to have the generator write that one again.

Just want to see which stretches it would pick, without writing any scripts?

```bash
./run.sh "URL" --plan
```

### I want to remove the dialogue (the people talking)

**This is the default** — you do not need a flag:

```bash
./run.sh "URL"
```

Demucs splits the audio into *voice* and *everything else*, throws the voice
away and keeps the music and sound effects, then ducks that under the narrator.

If you want the opposite — drop the original audio entirely, narrator only:

```bash
./run.sh "URL" --no-bg
```

`--no-bg` is also **much faster**, because it skips the slow step. Use it for a
first look.

Keep the dialogue removal but change how loud the music sits underneath:

```bash
./run.sh "URL" --bg-gain 0.35        # quieter music
```

### I want to get rid of the subtitles and use the narration subtitles instead

Three different things people mean by this. Pick the one you want:

**The video has subtitles burned into the picture** and you want them gone:

```bash
./run.sh "URL" --cover-captions
```

It finds the rows those subtitles occupy and smears them away before anything
else happens, then draws the narration's own captions. Only the narration text
is left on screen.

**You want the narration as a switchable subtitle track**, not text baked into
the picture:

```bash
./run.sh "URL" --no-burn
```

The `.mp4` still carries an English subtitle track, and a `.srt` is still
written beside it — the picture is just left clean.

**Both** — remove the original burned-in subtitles *and* keep the picture clean:

```bash
./run.sh "URL" --cover-captions --no-burn
```

### Other things you will want

```bash
# how many, and how long
./run.sh "URL" --reels 10 --duration 45

# a different narrator, speaking slightly faster
./run.sh "URL" --voice en-US-BrianMultilingualNeural --rate "+8%"

# list every voice
./run.sh --list-voices

# much better narration, using a free local model (see NARRATION.md)
./run.sh "URL" --script ollama --model llama3.2

# a file on your disk works anywhere a link does
.\run.bat "C:\Users\me\Videos\movie.mp4" --reels 5     # Windows
./run.sh ~/Videos/movie.mp4 --reels 5                  # macOS / Linux

# free up disk space when you are done
./run.sh --clean
```

### The order most people want

```bash
./run.sh "URL" --scripts              # 1. read and edit the narration
./run.sh "URL" --no-bg --reels 2      # 2. quick look: is the framing right?
./run.sh "URL"                        # 3. build them properly
./run.sh --clean                      # 4. reclaim the disk
```

---

## What you get

Everything lands in `output/<video title>/`:

```
reel-01.mp4        1080x1920, captions burned in, plus an English subtitle track
reel-01.srt        the same subtitles as a file, for uploading
reel-02.mp4        ...and so on
scripts/           the narration scripts -- edit these and re-run
manifest.json      which part of the source each reel came from
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
   transcribed from scratch. If the video has no captions at all, Whisper runs
   locally as a fallback — accurate, but slow.
2. **Scores the whole runtime** second by second, on how loud it is and how much
   is being said, then picks the best stretches, keeping them far enough apart
   that they do not all come from the same ten minutes.
3. **Snaps each pick to the nearest scene cut**, so a reel never opens mid-shot.
4. **Writes a narration script** for each stretch — and stops here if you passed
   `--scripts`, so you can read and rewrite them.
5. **Speaks them** with a free Microsoft Edge neural voice.
6. **Removes the dialogue** with Demucs.
7. **Reframes to 1080×1920**, cropping off letterbox bars (and optionally
   smearing away burned-in subtitles), burns the captions on, and encodes.

Work is cached in `work/`, so a second run only redoes what changed. Stopping a
run part-way is safe.

---

## Install — Windows

**You need three things first.** Install them in this order.

### 1. Python 3.11

Download from
[python.org/downloads/release/python-3119](https://www.python.org/downloads/release/python-3119/)
— scroll to the bottom and pick **Windows installer (64-bit)**.

> **In the installer, tick "Add python.exe to PATH" on the first screen.**
> This is the single most common thing to get wrong. If you miss it, nothing
> below will work.

Python **3.11 specifically**, not 3.12 or 3.13 — `torch 2.2.2` has no Windows
build for anything newer. (If you use the [small install](#if-disk-space-is-tight),
any Python 3.10+ is fine.)

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
changed PATH in new terminals — skip this and it will tell you ffmpeg is missing
even though you just installed it.

Check:

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
.\run.bat "https://www.youtube.com/watch?v=XXXX" --scripts
```

The first run installs everything else by itself and takes several minutes.

---

## Install — macOS

Install [Homebrew](https://brew.sh) if you do not have it, then:

```bash
brew install git ffmpeg yt-dlp python@3.11
git clone https://github.com/YOUR-USERNAME/youtube-reels.git
cd youtube-reels
chmod +x run.sh serve.sh
./run.sh "https://www.youtube.com/watch?v=XXXX" --scripts
```

`run.sh` builds its own environment on the first run, installing `ffmpeg`,
`yt-dlp` or Python 3.11 if they are missing.

---

## Install — Linux

Debian or Ubuntu:

```bash
sudo apt update
sudo apt install -y git ffmpeg yt-dlp python3.11 python3.11-venv fonts-dejavu-core
git clone https://github.com/YOUR-USERNAME/youtube-reels.git
cd youtube-reels
chmod +x run.sh serve.sh
./run.sh "https://www.youtube.com/watch?v=XXXX" --scripts
```

If your release has no `python3.11` package:

```bash
sudo add-apt-repository ppa:deadsnakes/ppa && sudo apt update
sudo apt install -y python3.11 python3.11-venv
```

`fonts-dejavu-core` matters — without a font on disk the captions cannot be
drawn into the picture.

---

## Using the web page

If you would rather click than type:

```bash
./serve.sh          # macOS / Linux
serve.bat           # Windows — or just double-click it
```

Your browser opens at `http://127.0.0.1:7861`. It has **the same two steps** as
the command line, and every option above is a checkbox or a slider:

1. Paste a link or drop in a file, choose how many reels, press
   **Get the narration scripts**.
2. The scripts appear in editable boxes, one per reel, labelled with the part of
   the source they came from. **Read them. Change anything.**
3. Press **Make the reels**. Only now does the slow work start.

You can change the voice, the framing, dialogue removal and the subtitle options
*after* reading the scripts — they are only used in step 2.

Nothing is uploaded anywhere: the page is a front end for the same pipeline,
running on your machine.

---

## Sharing it with other people

### A permanent link (best, and free)

A Hugging Face Space stays up without your machine running:

1. Create a Space at [huggingface.co/new-space](https://huggingface.co/new-space)
   — give it a name and choose the **Docker** SDK.
2. Deploy to it:

   ```bash
   ./hf-space/deploy.sh your-username/your-space-name
   ```

   When it asks for a password, paste an access token with **write** permission
   from [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens).

Your link is then
`https://huggingface.co/spaces/your-username/your-space-name`.

Two honest caveats about the free tier: it is a **shared CPU**, so it is much
slower than your machine; and **YouTube links often fail there**, because
YouTube blocks downloads from datacenter addresses. Uploading a file always
works.

### A temporary link

```bash
./serve.sh --share --password hunter2
```

Prints a public `https://....gradio.live` link that lasts up to a week. The work
still happens on your machine, so it must stay on with the terminal open.

> Use `--password`. Without it, anyone with the link can queue jobs on your
> computer.

### If `--share` does not work on Windows

**This is common and it is not your fault.** The public link needs a small
helper program (`frpc`) that Gradio downloads the first time you use `--share`,
and Windows Defender, SmartScreen or a corporate network routinely block it.

The project now handles this: if the public link fails, it tells you why and
**starts the local page anyway** instead of dying.

Your options, best first:

1. **Use a Hugging Face Space instead** (above). Permanent link, nothing to
   unblock, and your machine does not have to stay on.
2. **Share on your own network only** — no helper program involved:

   ```powershell
   serve.bat --lan
   ```

   Then find your IP with `ipconfig` and open `http://<your-ip>:7861` from the
   other device. Both devices must be on the same wifi.
3. **Unblock the file**: Windows Security → *Protection history* → find the
   blocked item → *Allow*. Then try `--share` again.

---

## If disk space is tight

The full install is about **1.3 GB**, and `torch` alone is 573 MB of it. On top
of that, the working cache holds the downloaded video and is usually the biggest
thing on disk.

### Free up space now

```bash
./run.sh --clean          # macOS / Linux
.\run.bat --clean         # Windows
```

This deletes the working cache — the downloaded video and every intermediate
file. **Your finished reels and your narration scripts in `output/` are not
touched.** A later run re-downloads whatever it needs.

Every run also tells you how big the cache has got:

```
cache now holds 2.4 GB. Run with --clean to free it.
```

### Install the small version instead (~370 MB)

`torch`, Demucs and Whisper exist for exactly two jobs: removing the dialogue,
and transcribing videos that have no captions. Skip them and the install drops
from about 1.3 GB to about 370 MB.

**macOS / Linux:**

```bash
cd youtube-reels
rm -rf .venv
python3.11 -m venv .venv
.venv/bin/pip install -r requirements-lite.txt
.venv/bin/python reels.py "URL" --no-bg
```

**Windows:**

```powershell
cd youtube-reels
rmdir /s /q .venv
py -3.11 -m venv .venv
.venv\Scripts\pip install -r requirements-lite.txt
.venv\Scripts\python reels.py "URL" --no-bg
```

With the small install you **must** pass `--no-bg` (no dialogue removal), and
you need a video that already has captions — which most YouTube videos do. If
you forget, it tells you plainly rather than crashing.

Everything else is identical: picking the stretches, the narration, the voice,
the captions, the subtitles, the vertical reframe and the web page.

Change your mind later:

```bash
.venv/bin/pip install -r requirements.txt      # Windows: .venv\Scripts\pip
```

### Keep downloads smaller

```bash
./run.sh "URL" --max-height 720
```

Roughly halves the downloaded file. The reels are slightly softer, since the
picture is scaled up to 1080 wide.

---

## All the options

| Flag | Does |
| --- | --- |
| `--scripts` | write the narration scripts and stop, so you can read and edit them |
| `--plan` | show the stretches it would cut, write and render nothing |
| `--clean` | delete the working cache and exit; reels and scripts are kept |
| `--reels 7` | how many to cut (default 7) |
| `--duration 75` | seconds to aim at per reel (default 75) |
| `--gap 180` | minimum seconds between two picks, so they spread across the film |
| `--script ollama` | real narration from a local model instead of extractive |
| `--model llama3.2` | which Ollama model to use |
| `--voice` / `--rate` | which neural voice, and how fast it speaks |
| `--list-voices` | print every available voice |
| `--fit blur \| crop` | `blur` keeps the whole frame against a blurred fill (best for widescreen); `crop` fills the screen and throws the sides away |
| `--cover-captions` | smear away subtitles burned into the source picture |
| `--no-burn` | leave the picture clean: English stays a subtitle track and a `.srt` |
| `--no-bg` | drop the original audio entirely. Skips Demucs — **much** faster |
| `--bg-gain 0.55` | how loud the music and effects sit under the narrator |
| `--caption-words 3` | words per caption burst |
| `--caption-size` / `--caption-color` / `--caption-y` | caption look and placement |
| `--font` | path to a `.ttf`, if none is found automatically |
| `--max-height 1080` | cap the download resolution |
| `--fast` | hardware encoder: quicker, slightly softer picture |
| `--whisper-model small` | only used when the video has no captions at all |

---

## How long it takes

**Demucs — the step that removes the voices — is the slow part**, and it runs on
the CPU. It is deliberately run **per reel** rather than across the whole film:
separating ten minutes of clips takes minutes, separating two hours takes hours
for audio that would be thrown away.

| Step | Time |
| --- | --- |
| Download + transcript | a few minutes |
| Picking the stretches | 1–3 minutes for a feature-length film |
| Writing the scripts | seconds (extractive) or a minute or two (Ollama) |
| Per reel, with dialogue removal | several minutes |
| Per reel, with `--no-bg` | well under a minute |

So: `--scripts` first, then `--no-bg` to check the framing and the voice, and
only then the real run.

---

## Troubleshooting

**"ffmpeg is not recognised" on Windows, right after installing it.**
Close the terminal and open a new one. Windows only picks up PATH changes in new
windows.

**Windows says Python 3.11 was not found.**
You probably missed the "Add python.exe to PATH" tick box. Re-run the installer,
choose *Modify*, and enable it.

**The wrong video downloads, or a strange error on Windows.**
Put the link in double quotes: `"https://..."`.

**`--share` fails on Windows.** See
[the section above](#if---share-does-not-work-on-windows) — use a Hugging Face
Space or `serve.bat --lan`.

**It is filling up my disk.** Run `--clean`, and consider the
[small install](#if-disk-space-is-tight).

**`yt-dlp` fails with a bot check or "Sign in to confirm you're not a robot".**
Update it first — `yt-dlp -U` — since YouTube changes things often. On a server
or a Space this can happen regardless; upload the file instead.

**A reel was skipped.**
Its script was empty, because that stretch had no speech to work from. Run
`--scripts`, write that one yourself, and run again.

**Reels came out with no captions burned in.**
No TrueType font was found. Pass `--font` with a path to a `.ttf`, or on Linux
`sudo apt install fonts-dejavu-core`. The `.srt` and the subtitle track are
written either way.

**"only N well-separated stretches fit".**
`--gap` is keeping the picks apart and the video is not long enough for as many
as you asked for. Lower it: `--gap 90`.

**"Demucs could not run" / "Whisper is not installed".**
You are on the small install. Either add `--no-bg`, or
`pip install -r requirements.txt`.

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

Create the empty repository first at [github.com/new](https://github.com/new),
and do **not** let it add a README — this one is already here.

`.venv/`, `work/` and `output/` are ignored, so none of the multi-gigabyte
generated files get pushed.

---

## Notes and limits

- **Copyright.** The tool is content-neutral, but re-uploading clips of a film
  you do not own is what gets channels struck, regardless of how they were
  edited. Use it on your own footage, or on material you have the rights to.
- **Demucs is not perfect.** Shouted or heavily processed dialogue can leave a
  faint trace in the background bed. Lower `--bg-gain`, or use `--no-bg`.
- **The narrator is only as good as the transcript** — which is why you can
  rewrite every script. See **[NARRATION.md](NARRATION.md)**.
- **`--cover-captions` guesses.** It looks for bright text with a dark outline in
  the lower half of the frame. It is good at ordinary subtitles and can be
  fooled by bright captions elsewhere in the picture. Check one reel before
  committing to a batch.
- Captions are drawn with Pillow and overlaid as one transparent video, because
  the usual `subtitles` and `drawtext` filters need an ffmpeg built with libass —
  and many are not. Doing it this way looks identical on Windows, macOS and
  Linux.
- On Intel Macs, `torch` is pinned to 2.2.2 and `ctranslate2` below 4.5 — the
  last releases with x86_64 macOS wheels. `KMP_DUPLICATE_LIB_OK` is set in
  `reels.py` before anything loads, because torch and ctranslate2 each ship their
  own OpenMP and Intel's aborts the process when it sees both.
