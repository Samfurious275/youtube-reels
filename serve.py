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
import socket
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

# The dropdown shows each style's description; this maps that back to its key.
STYLE_LABELS = {f"{k} — {v['label']}": k for k, v in sorted(reels.STYLES.items())}
STYLE_BY_LABEL = dict(STYLE_LABELS)
DEFAULT_STYLE_LABEL = next(lbl for lbl, k in STYLE_LABELS.items()
                           if k == reels.DEFAULT_STYLE)


def settings(count, seconds, voice, fit_label, burn, cover, keep_music, use_ollama,
             story=False, style=reels.DEFAULT_STYLE, montage=True):
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
    a.script = "auto" if use_ollama else "extractive"
    a.highlights = not story
    a.style = STYLE_BY_LABEL.get(style, reels.DEFAULT_STYLE)
    a.no_montage = not montage
    return a


def get_scripts(url, upload, count, seconds, voice, fit_label, burn, cover,
                keep_music, use_ollama, story, style, montage,
                progress=gr.Progress()):
    """Step one: find the stretches and write a script for each."""
    target = (url or "").strip() or upload
    if not target:
        raise gr.Error("Paste a link or choose a video file first.")

    a = settings(count, seconds, voice, fit_label, burn, cover, keep_music,
                 use_ollama, story, style, montage)
    reels.WORK.mkdir(exist_ok=True)
    reels.OUTPUT.mkdir(exist_ok=True)

    # Transcript only: the picture is not downloaded until you press the second
    # button, so getting the scripts takes seconds even for a long film.
    ctx = reels.prepare(target, a, need_video=False,
                        progress=lambda frac, desc: progress(frac, desc=desc))
    spans, scripts = ctx["spans"], ctx["scripts"]

    titles = ctx.get("titles") or [None] * len(spans)
    rows, boxes, talk, state = [], [], [], []
    for i in range(MAX_REELS):
        if i < len(spans):
            s, t = spans[i], titles[i]
            where = (f"narrates {reels.hhmmss(s['narr_start'])} – "
                     f"{reels.hhmmss(s['narr_end'])}" if "narr_start" in s
                     else f"{reels.hhmmss(s['start'])} – {reels.hhmmss(s['end'])}")
            rows.append(gr.update(visible=True))
            boxes.append(gr.update(
                value=scripts[i],
                label=f"Reel {i + 1}" + (f" · {t}" if t else "") + f"  ({where})"))
            talk.append(gr.update(value=reels.dialogue_for(ctx["lines"], s)))
            made = Path(ctx["out_dir"]) / f"reel-{i + 1:02d}.mp4"
            state.append(gr.update(
                value=f"*Already made: {made.name}*" if made.exists()
                else "*Not made yet.*"))
        else:
            rows.append(gr.update(visible=False))
            boxes.append(gr.update(value=""))
            talk.append(gr.update(value=""))
            state.append(gr.update(value=""))

    empty = sum(1 for s in scripts if not s.strip())
    note = [f"**{len(spans)} parts.** Read the scripts below, change anything "
            f"you like, then press *Make the reels*."]
    if empty:
        note.append(f"\n**{empty}** of them came out empty, because that stretch "
                    f"had no speech to work from. Write those yourself, or they "
                    f"will be skipped.")
    if a.script != "extractive" and not reels.ollama_up(a.ollama_host):
        note.append("\n⚠️ **No local model is answering**, so these were picked "
                    "out of the transcript rather than written — on a film that "
                    "reads as the characters talking, not as narration. Install "
                    "[Ollama](https://ollama.com), run `ollama pull llama3.2`, "
                    "then press the button again.")
    if ctx["video"] is None:
        note.append("\nOnly the transcript has been downloaded so far — the "
                    "video itself is fetched when you press *Make the reels*.")
    note.append(f"\nScripts are also saved in `{ctx['scripts_dir']}`.")

    files = [str(p) for p in sorted(Path(ctx["scripts_dir"]).glob("reel-*.txt"))]
    return ([ctx, "\n".join(note), gr.update(visible=True), files]
            + rows + boxes + talk + state)


FORM_LEN = 13          # how many inputs the settings form has, before the scripts


def render(ctx, form_values, scripts, only, progress):
    """Save whatever is in the boxes, then render all of them or just one."""
    a = settings(*form_values[2:])

    scripts_dir = Path(ctx["scripts_dir"])
    titles = ctx.get("titles") or [None] * len(ctx["spans"])
    for i, text in enumerate(scripts[:len(ctx["spans"])], 1):
        # The title lives in the file as a # comment and the box only ever held
        # the spoken words, so put it back rather than losing it on save.
        reels.write_script(scripts_dir, i, titles[i - 1], text)

    out_dir, made = reels.build(
        ctx, a, only=only,
        progress=lambda frac, desc: progress(frac, desc=desc))

    if not made:
        raise gr.Error("Nothing was rendered — that script was empty. Write "
                       "something in it and try again.")

    mp4s = sorted(Path(out_dir).glob("reel-*.mp4"))
    files = [str(f) for f in sorted(Path(out_dir).rglob("*")) if f.is_file()]

    rows = [f"**{len(made)} ready** in `{out_dir}`", ""]
    for m in made:
        rows.append(f"- **{m['file']}**"
                    + (f" · {m['title']}" if m.get("title") else "")
                    + f" — {m['seconds']:.0f}s, from "
                      f"{reels.hhmmss(m['source_start'])}")
    rows.append(f"\nWorking cache is now "
                f"{reels.human_size(reels.dir_size(reels.WORK))}. "
                f"Free it any time with `--clean`.")

    newest = max((Path(out_dir) / m["file"] for m in made),
                 key=lambda f: f.stat().st_mtime, default=None)
    return str(newest) if newest else None, files, "\n".join(rows)


def make_reels(ctx, *args, progress=gr.Progress()):
    """Every reel."""
    if not ctx:
        raise gr.Error("Press *Get the narration scripts* first.")
    return render(ctx, args[:FORM_LEN], args[FORM_LEN:], None, progress)


def rewrite_one(index):
    """Button handler that writes reel `index` again, and nothing else."""
    def run(ctx, *form_values, progress=gr.Progress()):
        if not ctx or index >= len(ctx["spans"]):
            raise gr.Error("Press *Get the narration scripts* first.")
        a = settings(*form_values[2:])
        progress(0.2, desc=f"Rewriting script {index + 1}")
        title, text = reels.regenerate_script(ctx, a, index + 1)
        ctx["scripts"][index] = text
        ctx.setdefault("titles", [None] * len(ctx["spans"]))[index] = title
        if not text:
            return (gr.update(value=""),
                    f"Reel {index + 1} came back empty. Write it yourself, or "
                    f"press rewrite again.")
        return (gr.update(value=text),
                f"Rewrote reel {index + 1}" + (f" — *{title}*" if title else "")
                + ". The others are untouched.")
    return run


def render_one(index):
    """Button handler that makes, or remakes, only reel `index`."""
    def run(ctx, *args, progress=gr.Progress()):
        if not ctx or index >= len(ctx["spans"]):
            raise gr.Error("Press *Get the narration scripts* first.")
        video, files, summary = render(ctx, args[:FORM_LEN], args[FORM_LEN:],
                                       {index + 1}, progress)
        return video, files, summary, f"*Made reel {index + 1}.*"
    return run


def delete_one(index):
    """Button handler that throws away reel `index`, keeping its script."""
    def run(ctx):
        if not ctx:
            raise gr.Error("Press *Get the narration scripts* first.")
        gone = reels.delete_reel(ctx["out_dir"], index + 1)
        left = [str(f) for f in sorted(Path(ctx["out_dir"]).rglob("*")) if f.is_file()]
        if not gone:
            return left, "*Nothing to delete — that reel has not been made.*"
        return left, (f"*Deleted {', '.join(gone)}. The script is still here, so "
                      f"you can make it again.*")
    return run


def build_ui():
    with gr.Blocks(title="Reel maker") as demo:
        gr.Markdown(
            "# Long video → narrated vertical reels\n"
            "Paste a YouTube link, or drop in a video **you own or have "
            "permission to use**. You get back 1–2 minute vertical shorts with "
            "the original dialogue removed, the music kept, a narrator over the "
            "top and captions burned in.\n\n"
            "**It works in two steps.** First you get the narration scripts to "
            "read and edit — that downloads only the transcript, so it takes "
            "seconds even for a long film. The video itself is fetched only "
            "when you ask for a reel.\n\n"
            "Each script has its own **Rewrite** and **Make just this reel** "
            "buttons, so one bad script does not hold up the rest."
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
                story = gr.Checkbox(
                    value=True,
                    label="Recap series — tell the whole story in order",
                    info="Each part carries on from the last, covering the film "
                         "start to finish. Untick for separate highlights that "
                         "do not connect")
                style = gr.Dropdown(
                    list(STYLE_LABELS), value=DEFAULT_STYLE_LABEL,
                    label="How the narration is written",
                    info="These come from the styles/ folder — add a text file "
                         "there and it appears here")
                use_ollama = gr.Checkbox(
                    value=True,
                    label="Write the narration with a local model (recommended)",
                    info="Untick only to skip it entirely. Without a model the "
                         "script is picked out of the transcript, which on a "
                         "film reads as the characters talking rather than as "
                         "narration")

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
                montage = gr.Checkbox(
                    value=True,
                    label="Cut between clips from across the part",
                    info="The narration covers the whole part, so the picture "
                         "moves through it too. Untick to sit on one continuous "
                         "stretch instead")

                step1 = gr.Button("Get the narration scripts", variant="primary")

            with gr.Column(scale=1):
                notes = gr.Markdown()
                rows, boxes, talk, state = [], [], [], []
                redo_btns, one_btns, del_btns = [], [], []
                for i in range(MAX_REELS):
                    with gr.Group(visible=False) as row:
                        boxes.append(gr.Textbox(label=f"Reel {i + 1}", lines=6,
                                                interactive=True))
                        with gr.Accordion("The film's own dialogue for this part",
                                          open=False):
                            talk.append(gr.Textbox(
                                show_label=False, lines=12, interactive=False,
                                info="What the narration was written from. Read "
                                     "it to judge whether the script is a fair "
                                     "account, and paste from it if you rewrite "
                                     "by hand"))
                        with gr.Row():
                            redo_btns.append(gr.Button("↻ Rewrite script",
                                                       size="sm"))
                            one_btns.append(gr.Button("Make / remake this reel",
                                                      size="sm",
                                                      variant="primary"))
                            del_btns.append(gr.Button("Delete this reel",
                                                      size="sm", variant="stop"))
                        state.append(gr.Markdown())
                    rows.append(row)

                script_files = gr.Files(label="The scripts, as .txt files")
                step2 = gr.Button("Make all the reels", variant="primary",
                                  visible=False)
                preview = gr.Video(label="Finished reel")
                summary = gr.Markdown()
                out_files = gr.Files(label="Every reel, subtitle and script")

        form = [url, upload, count, seconds, voice, fit, burn, cover, keep_music,
                use_ollama, story, style, montage]
        assert len(form) == FORM_LEN

        step1.click(get_scripts, inputs=form,
                    outputs=[job, notes, step2, script_files]
                            + rows + boxes + talk + state)
        step2.click(make_reels, inputs=[job] + form + boxes,
                    outputs=[preview, out_files, summary])

        for i in range(MAX_REELS):
            redo_btns[i].click(rewrite_one(i), inputs=[job] + form,
                               outputs=[boxes[i], notes])
            one_btns[i].click(render_one(i), inputs=[job] + form + boxes,
                              outputs=[preview, out_files, summary, state[i]])
            del_btns[i].click(delete_one(i), inputs=[job],
                              outputs=[out_files, state[i]])
    return demo


def free_port(host, start, tries=20):
    """The first port free at or above `start`.

    Gradio is told one exact port and gives up if it is taken, which is easy to
    hit: a previous run suspended with Ctrl+Z instead of Ctrl+C still holds it,
    and the error that comes back talks about environment variables rather than
    saying something is already running. Finding the next free one is friendlier
    than failing.
    """
    bind = "" if host == "0.0.0.0" else host
    for port in range(start, start + tries):
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind((bind, port))
                return port
            except OSError:
                continue
    return None


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

    port = free_port(host, a.port)
    if port is None:
        print(f"\n  Ports {a.port}-{a.port + 19} are all in use. Close whatever "
              f"is using them, or pass --port with a free one.\n")
        return
    if port != a.port:
        print(f"\n  ! Port {a.port} is already in use -- most likely another copy "
              f"of this page.\n    Using {port} instead.")

    if a.share and not a.password:
        print("  ! --share puts this on the public internet with no password.\n"
              "    Anyone with the link can queue jobs on your machine.\n"
              "    Add --password to lock it.\n")

    print(f"\n  Starting the reel maker on http://{host}:{port}")
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
        demo.launch(server_name=host, server_port=port, share=a.share,
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
        print("        then open http://<your-ip>:%d from the other device\n" % port)
        print("      * Or allow the blocked file in Windows Security ->")
        print("        Protection history, then try --share again.\n")
        print("    Starting without the public link.\n")
        demo.launch(server_name=host, server_port=port, share=False,
                    auth=auth, inbrowser=True)


if __name__ == "__main__":
    main()
