#!/usr/bin/env python3
"""Web page for the reel maker.

Paste a YouTube link or drop in a video, get back vertical shorts with the
dialogue stripped out, a narrator over the top and captions burned in.

  ./serve.sh            macOS / Linux
  serve.bat             Windows

Either one installs whatever is missing on first run, starts the page and opens
your browser at it. Nothing is uploaded anywhere: the whole pipeline runs on
this machine.

  ./serve.sh --share                       also publish a public link (up to a week)
  ./serve.sh --share --password hunter2    ... with a password on it
"""

import argparse
from pathlib import Path

import gradio as gr

import reels

FITS = [("Keep the whole frame (blurred edges)", "blur"),
        ("Fill the screen (crops the sides)", "crop")]


def process(url, upload, count, seconds, voice, fit, burn, keep_music, use_ollama,
            progress=gr.Progress()):
    """Run the pipeline once and hand the page back everything it produced."""
    target = (url or "").strip() or upload
    if not target:
        raise gr.Error("Paste a link or choose a video file first.")

    # Defaults come from the CLI parser so the page and the command line cannot
    # drift apart; only what the page actually exposes is overridden.
    a = reels.build_parser().parse_args(["placeholder"])
    a.reels = int(count)
    a.duration = int(seconds)
    a.max_duration = max(a.max_duration, float(a.duration))
    a.voice = voice
    a.fit = fit
    a.no_burn = not burn
    a.no_bg = not keep_music
    a.script = "ollama" if use_ollama else "extractive"

    reels.WORK.mkdir(exist_ok=True)
    reels.OUTPUT.mkdir(exist_ok=True)

    out_dir, made = reels.make_reels(
        target, a, progress=lambda frac, desc: progress(frac, desc=desc))

    if not made:
        raise gr.Error(
            "No reels came out of that. The most common cause is a video with "
            "no speech in it to narrate.")

    mp4s = sorted(out_dir.glob("reel-*.mp4"))
    files = [str(p) for p in sorted(out_dir.iterdir()) if p.is_file()]

    rows = [f"**{len(made)} reels** in `{out_dir}`", ""]
    for m, mp4 in zip(made, mp4s):
        rows.append(f"- **{mp4.name}** — {reels.hhmmss(m['source_start'])} to "
                    f"{reels.hhmmss(m['source_end'])} of the source, "
                    f"{m['seconds']:.0f}s long")
    return str(mp4s[0]) if mp4s else None, files, "\n".join(rows)


def build_ui():
    with gr.Blocks(title="Reel maker") as demo:
        gr.Markdown(
            "# Long video &rarr; narrated vertical reels\n"
            "Paste a YouTube link, or drop in a video **you own or have "
            "permission to use**. You get back 1-2 minute vertical shorts: the "
            "original dialogue removed, the music and effects kept, an AI "
            "narrator over the top, and captions burned in.\n\n"
            "**This takes a while.** Removing the dialogue is the slow part and "
            "it runs on the CPU. A handful of reels from a long film can take "
            "well over an hour. Start with 2 reels to see what you get, and "
            "untick *Keep the original music* for a much faster first look."
        )
        with gr.Row():
            with gr.Column():
                url = gr.Textbox(
                    label="YouTube link",
                    placeholder="https://www.youtube.com/watch?v=...")
                gr.Markdown("*...or upload a file instead:*")
                upload = gr.Video(label="Video file")

                count = gr.Slider(1, 10, value=5, step=1, label="How many reels")
                seconds = gr.Slider(30, 150, value=75, step=5,
                                    label="Seconds per reel (roughly)")
                voice = gr.Dropdown(reels.SUGGESTED_VOICES,
                                    value=reels.DEFAULT_VOICE, label="Narrator voice")
                fit = gr.Radio([f[0] for f in FITS], value=FITS[0][0],
                               label="How to fit a wide picture into a tall frame")
                burn = gr.Checkbox(
                    value=True, label="Burn the captions into the picture",
                    info="Off: English stays as a subtitle track and a .srt file")
                keep_music = gr.Checkbox(
                    value=True, label="Keep the original music and sound effects",
                    info="Unticking this skips the slow dialogue-removal step")
                use_ollama = gr.Checkbox(
                    value=False, label="Write the narration with a local Ollama model",
                    info="Needs Ollama running on this machine; falls back "
                         "automatically if it is not")
                go = gr.Button("Make the reels", variant="primary")
            with gr.Column():
                preview = gr.Video(label="First reel")
                summary = gr.Markdown()
                out_files = gr.Files(label="Every reel, subtitle and script")

        def run(url, upload, count, seconds, voice, fit_label, burn, keep_music,
                use_ollama, progress=gr.Progress()):
            fit = dict(FITS)[fit_label]
            return process(url, upload, count, seconds, voice, fit, burn,
                           keep_music, use_ollama, progress)

        go.click(run,
                 inputs=[url, upload, count, seconds, voice, fit, burn,
                         keep_music, use_ollama],
                 outputs=[preview, out_files, summary])
    return demo


def main():
    p = argparse.ArgumentParser(
        description="Serve the reel maker as a web page on this machine.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument("--share", action="store_true",
                   help="also publish a public gradio.live link (lasts up to a week)")
    p.add_argument("--password", default=None,
                   help="require this password; strongly advised with --share")
    p.add_argument("--user", default="reels", help="username that goes with --password")
    p.add_argument("--host", default="127.0.0.1",
                   help="0.0.0.0 to allow other machines on your network")
    p.add_argument("--port", type=int, default=7861)
    a = p.parse_args()

    if a.share and not a.password:
        print("  ! --share puts this on the public internet with no password.\n"
              "    Anyone with the link can queue jobs on your machine.\n"
              "    Add --password to lock it.\n")

    print(f"\n  Starting the reel maker on http://{a.host}:{a.port}")
    if a.password:
        # The username is easy to miss, and the login just says "Incorrect
        # Credentials" when it is wrong, so spell both out here.
        print("\n  The page will ask you to log in:")
        print(f"      username   {a.user}")
        print(f"      password   {a.password}\n")
    print("  Your browser should open by itself. Press Ctrl+C here to stop.\n")

    # queue() keeps long jobs alive; without it the browser gives up partway
    build_ui().queue(max_size=8).launch(
        server_name=a.host, server_port=a.port, share=a.share,
        auth=(a.user, a.password) if a.password else None,
        inbrowser=True)


if __name__ == "__main__":
    main()
