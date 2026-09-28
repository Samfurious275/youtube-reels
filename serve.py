#!/usr/bin/env python3
"""Web page for the reel maker.

Two steps on purpose. First it finds the best stretches and writes a narration
script for each one, and puts them in front of you to read and edit. Only when
you press the second button does any of the slow work start.

  ./serve.sh            macOS / Linux
  serve.bat             Windows

Either one installs whatever is missing on first run, starts the page and opens
your browser at it. Nothing is uploaded anywhere: the whole pipeline runs on
this machine.

  ./serve.sh --share                       also publish a public link (up to a week)
  ./serve.sh --share --password hunter2    ... with a password on it
  ./serve.sh --lan                         let other devices on your wifi in
"""

import argparse
import traceback
from pathlib import Path

import gradio as gr

import reels

# The page draws this many script boxes and hides the ones it does not need.
# Gradio wants its components built before anything runs, so the ceiling has to
# match the largest number of reels the form can ask for.
MAX_REELS = 10

FITS = [("Keep the whole frame (blurred edges)", "blur"),
        ("Fill the screen (crops the sides)", "crop")]


def settings(count, seconds, voice, fit_label, burn, cover, keep_music, use_ollama):
    """Turn the form into the same options object the command line builds.

    Defaults come from the CLI parser, so the page cannot drift away from what
    the documented commands do; only what the form exposes is overridden.
    """
    a = reels.build_parser().parse_args(["placeholder"])
    a.reels = int(count)
    a.duration = int(seconds)
    a.max_duration = max(a.max_duration, float(a.duration))
    a.voice = voice
    a.fit = dict(FITS)[fit_label]
    a.no_burn = not burn
    a.cover_captions = bool(cover)
    a.no_bg = not keep_music
    a.script = "ollama" if use_ollama else "extractive"
    return a


def get_scripts(url, upload, count, seconds, voice, fit_label, burn, cover,
                keep_music, use_ollama, progress=gr.Progress()):
    """Step one: find the stretches and write a script for each."""
    target = (url or "").strip() or upload
    if not target:
        raise gr.Error("Paste a link or choose a video file first.")

    a = settings(count, seconds, voice, fit_label, burn, cover, keep_music, use_ollama)
    reels.WORK.mkdir(exist_ok=True)
    reels.OUTPUT.mkdir(exist_ok=True)

    ctx = reels.prepare(target, a,
                        progress=lambda frac, desc: progress(frac, desc=desc))
    spans, scripts = ctx["spans"], ctx["scripts"]

    boxes = []
    for i in range(MAX_REELS):
        if i < len(spans):
            s = spans[i]
            boxes.append(gr.update(
                visible=True, value=scripts[i],
                label=f"Reel {i + 1}  ({reels.hhmmss(s['start'])} – "
                      f"{reels.hhmmss(s['end'])} of the source)"))
        else:
            boxes.append(gr.update(visible=False, value=""))

    empty = sum(1 for s in scripts if not s.strip())
    note = [f"**{len(spans)} stretches picked.** Read the scripts below, change "
            f"anything you like, then press *Make the reels*."]
    if empty:
        note.append(f"\n**{empty}** of them came out empty, because that stretch "
                    f"had no speech to work from. Write those yourself, or they "
                    f"will be skipped.")
    note.append(f"\nScripts are also saved in `{ctx['scripts_dir']}`.")

    return [ctx, "\n".join(note), gr.update(visible=True)] + boxes


def make_reels(ctx, url, upload, count, seconds, voice, fit_label, burn, cover,
               keep_music, use_ollama, *scripts, progress=gr.Progress()):
    """Step two: save whatever is in the boxes, then render."""
    if not ctx:
        raise gr.Error("Press *Get the narration scripts* first.")

    # Read the options again rather than reusing step one's: everything here
    # affects rendering only, so changing your mind after reading the scripts
    # should work.
    a = settings(count, seconds, voice, fit_label, burn, cover, keep_music, use_ollama)

    scripts_dir = Path(ctx["scripts_dir"])
    scripts_dir.mkdir(parents=True, exist_ok=True)
    for i, text in enumerate(scripts[:len(ctx["spans"])], 1):
        (scripts_dir / f"reel-{i:02d}.txt").write_text(
            (text or "").strip(), encoding="utf-8")

    out_dir, made = reels.build(
        ctx, a, progress=lambda frac, desc: progress(frac, desc=desc))

    if not made:
        raise gr.Error("Nothing was rendered. Every script was empty — write at "
                       "least one and try again.")

    mp4s = sorted(Path(out_dir).glob("reel-*.mp4"))
    files = [str(p) for p in sorted(Path(out_dir).rglob("*")) if p.is_file()]

    rows = [f"**{len(made)} reels** in `{out_dir}`", ""]
    for m, mp4 in zip(made, mp4s):
        rows.append(f"- **{mp4.name}** — {reels.hhmmss(m['source_start'])} to "
                    f"{reels.hhmmss(m['source_end'])} of the source, "
                    f"{m['seconds']:.0f}s long")
    rows.append(f"\nWorking cache is now "
                f"{reels.human_size(reels.dir_size(reels.WORK))}. "
                f"Free it any time with `--clean`.")
    return str(mp4s[0]) if mp4s else None, files, "\n".join(rows)


def build_ui():
    with gr.Blocks(title="Reel maker") as demo:
        gr.Markdown(
            "# Long video → narrated vertical reels\n"
            "Paste a YouTube link, or drop in a video **you own or have "
            "permission to use**. You get back 1–2 minute vertical shorts with "
            "the original dialogue removed, the music kept, a narrator over the "
            "top and captions burned in.\n\n"
            "**It works in two steps.** First you get the narration scripts to "
            "read and edit. Nothing slow happens until you press the second "
            "button."
        )

        job = gr.State()

        with gr.Row():
            with gr.Column(scale=1):
                gr.Markdown("### 1. What to use")
                url = gr.Textbox(label="YouTube link",
                                 placeholder="https://www.youtube.com/watch?v=...")
                gr.Markdown("*...or upload a file instead:*")
                upload = gr.Video(label="Video file")

                count = gr.Slider(1, MAX_REELS, value=5, step=1,
                                  label="How many reels")
                seconds = gr.Slider(30, 150, value=75, step=5,
                                    label="Seconds per reel (roughly)")
                use_ollama = gr.Checkbox(
                    value=False, label="Write the narration with a local Ollama model",
                    info="Much better writing. Needs Ollama running; falls back "
                         "on its own if it is not there")

                gr.Markdown("### 2. How it should look and sound")
                voice = gr.Dropdown(reels.SUGGESTED_VOICES,
                                    value=reels.DEFAULT_VOICE, label="Narrator voice")
                fit = gr.Radio([f[0] for f in FITS], value=FITS[0][0],
                               label="How to fit a wide picture into a tall frame")
                keep_music = gr.Checkbox(
                    value=True, label="Remove the dialogue, keep music and effects",
                    info="Unticking this drops the original audio entirely and "
                         "is much faster")
                burn = gr.Checkbox(
                    value=True, label="Burn the narration captions into the picture",
                    info="Off: English stays a subtitle track and a .srt file")
                cover = gr.Checkbox(
                    value=False, label="Blur out subtitles already burned into the video",
                    info="Use when the source has hardcoded subtitles you want gone")

                step1 = gr.Button("Get the narration scripts", variant="primary")

            with gr.Column(scale=1):
                notes = gr.Markdown()
                boxes = [gr.Textbox(label=f"Reel {i + 1}", lines=5, visible=False,
                                    interactive=True) for i in range(MAX_REELS)]
                step2 = gr.Button("Make the reels", variant="primary", visible=False)
                preview = gr.Video(label="First reel")
                summary = gr.Markdown()
                out_files = gr.Files(label="Every reel, subtitle and script")

        form = [url, upload, count, seconds, voice, fit, burn, cover, keep_music,
                use_ollama]

        step1.click(get_scripts, inputs=form,
                    outputs=[job, notes, step2] + boxes)
        step2.click(make_reels, inputs=[job] + form + boxes,
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
    p.add_argument("--lan", action="store_true",
                   help="let other devices on your network reach it, no public link")
    p.add_argument("--host", default="127.0.0.1",
                   help="0.0.0.0 to allow other machines on your network")
    p.add_argument("--port", type=int, default=7861)
    a = p.parse_args()

    host = "0.0.0.0" if a.lan else a.host

    if a.share and not a.password:
        print("  ! --share puts this on the public internet with no password.\n"
              "    Anyone with the link can queue jobs on your machine.\n"
              "    Add --password to lock it.\n")

    print(f"\n  Starting the reel maker on http://{host}:{a.port}")
    if a.password:
        # The username is easy to miss, and the login just says "Incorrect
        # Credentials" when it is wrong, so spell both out here.
        print("\n  The page will ask you to log in:")
        print(f"      username   {a.user}")
        print(f"      password   {a.password}\n")
    print("  Your browser should open by itself. Press Ctrl+C here to stop.\n")

    auth = (a.user, a.password) if a.password else None
    # queue() keeps long jobs alive; without it the browser gives up partway
    demo = build_ui().queue(max_size=8)

    try:
        demo.launch(server_name=host, server_port=a.port, share=a.share,
                    auth=auth, inbrowser=True)
    except Exception as e:
        if not a.share:
            raise
        # The public link needs a helper binary that Gradio downloads on first
        # use, and on Windows that is routinely blocked by Defender, SmartScreen
        # or a corporate proxy. Losing the whole page over it would be silly
        # when the local one works perfectly well.
        print("\n  ! The public link could not be created.")
        print(f"    {type(e).__name__}: {e}\n")
        print("    This is almost always Windows blocking the helper Gradio")
        print("    downloads for sharing (frpc). Options, best first:\n")
        print("      * Put it on a free Hugging Face Space instead, which gives")
        print("        you a permanent link and does not need your machine on:")
        print("            ./hf-space/deploy.sh your-name/your-space\n")
        print("      * Share it on your own network only, no helper needed:")
        print("            serve.bat --lan")
        print("        then open http://<your-ip>:%d from the other device\n" % a.port)
        print("      * Or allow the blocked file in Windows Security ->")
        print("        Protection history, then try --share again.\n")
        print("    Starting without the public link.\n")
        demo.launch(server_name=host, server_port=a.port, share=False,
                    auth=auth, inbrowser=True)


if __name__ == "__main__":
    main()
