---
title: Reel Maker
emoji: 🎬
colorFrom: indigo
colorTo: purple
sdk: docker
app_port: 7860
pinned: false
license: mit
---

# Long video → narrated vertical reels

Paste a link or drop in a video you own, and get back 1–2 minute vertical
shorts: the original dialogue removed, the music and sound effects kept, an AI
narrator over the top, and captions burned in.

Every reel also carries the narration as a real subtitle track and as a `.srt`
file beside it.

## Please read before you queue a job

This Space runs on a **shared free CPU**, and the dialogue-removal step (Demucs)
is heavy. A couple of short reels is a reasonable thing to ask of it; a
two-hour film is not — that belongs on your own machine, where it can take the
hours it needs.

To keep it usable:

- Start with **2 reels**.
- Untick **Keep the original music and sound effects** for a first look. That
  skips the slow step entirely.
- Prefer **uploading a short clip** over pasting a long link.

**YouTube links often fail here.** YouTube blocks downloads from datacenter
addresses, which is what this Space has, so a link that works on your laptop can
still be refused in the cloud. Uploading a file always works.

## Running it properly

The source, and instructions for macOS, Linux and Windows, are in the project
repository. Run locally and it is faster, has no queue, and takes whatever time
a long film needs.

## Fair use

Only put in material you own or have permission to use. Re-uploading clips of
someone else's film is what gets accounts struck, however the clips were edited.
