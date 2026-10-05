# Narration — what you need, and how to make it good

The narration is two separate things, and they fail for different reasons:

- **The words** — the script written for each reel.
- **The voice** — the speech that reads those words aloud.

The voice is good out of the box and needs almost nothing from you. **The words
are where the quality actually comes from**, and where you have the most control.

---

## A recap series, not separate clips

By default the reels form **one continuous recap**: the film is split into
consecutive chapters that between them cover the whole runtime, and each part is
written knowing what the previous one already said. Part 2 carries on from where
Part 1 stopped rather than re-introducing everyone.

Each chapter narrates its *whole* stretch of story — often half an hour of it.
The footage keeps up by cutting between a dozen or so short clips spread across
that chapter, rather than sitting on one continuous minute, so the picture moves
through the story at roughly the pace the voice does.

Each part also gets a chapter title. It is stored as a `#` comment on the first
line of the script file:

```
# The Boat Under the Tarpaulin

Idris takes her to the boat yard and pulls back the cover...
```

**Lines starting with `#` are never spoken.** They are there for the title and
for any notes you want to leave yourself. Everything else in the file is read
aloud.

Continuity and the titles both come from the local model, which is used
automatically when one is running. Without one you get a digest of each
chapter's dialogue instead, and plain `Part 1`, `Part 2` titles.

For separate, unconnected highlights instead, use `--highlights`.

---

## What you need

| For | You need | Cost |
| --- | --- | --- |
| The voice (always) | An internet connection | Free, no account, no key |
| Default script writing | Nothing at all | Free |
| **Good** script writing | [Ollama](https://ollama.com) + a model (~2 GB) | Free, local, no account |
| Best script writing | Ten minutes and your own judgement | Free |

**One honest note about the voice:** the narrator uses Microsoft's free Edge
neural voices, which means the text is sent to Microsoft's speech service and the
audio comes back. There is no API key, no account and no charge — but it is the
one step that needs the internet. Everything else (picking the stretches,
removing the dialogue, captions, encoding) runs entirely on your machine.

---

## The three ways to get a script

Ranked worst to best. They all cost nothing.

### 1. Extractive — the default

```bash
./run.sh "URL"
```

No download, no setup, works offline. It reads the transcript of the stretch,
scores each line by how many of that stretch's own frequent words it carries, and
keeps the highest-scoring lines until it has enough to fill the time — then puts
them back in the order they were said.

It also strips the things a caption track carries that nobody should read aloud:
`[Music]`, `(laughs)`, `♪`, and `NAME:` speaker prefixes.

**Its limit, stated plainly:** it selects sentences, it does not write them. The
result reads like a summary of what the characters said, because that is exactly
what it is. It is fine for a rough pass and for checking your framing. It will
not sound like a recap channel.

### 2. Ollama — a local model writes it

This is **the single biggest quality jump available**, and it is still free.

```bash
# once
ollama pull llama3.2

# then, every time
./run.sh "URL" --script ollama --model llama3.2
```

The model is asked for third-person, present-tense narration that opens with a
line that stops someone scrolling, with dialogue quoting and stage directions
explicitly ruled out.

- It runs on your machine. Nothing is uploaded and there is no account.
- If Ollama is not running, it **quietly falls back to extractive** rather than
  failing a long render.
- Bigger models write better. `llama3.2` is a good starting point; try
  `mistral` or a larger llama if your machine can hold one.
- Point it elsewhere with `--ollama-host http://192.168.1.50:11434` if Ollama
  runs on another machine on your network.

### 3. Write it yourself — the best results

Every script is a plain text file, and **the pipeline reads it back verbatim**.
So you can take the writing over completely. There is a command for exactly
this:

```bash
./run.sh "URL" --scripts          # macOS / Linux
.\run.bat "URL" --scripts         # Windows
```

That downloads **only the transcript**, picks the parts, writes a script for
each, and **stops before anything is rendered** — the video is not fetched at
all, so this comes back in seconds and costs a few hundred kilobytes even for a
feature-length film.

The files land next to where the reels will go:

```
output/<video title>/scripts/reel-01.txt
output/<video title>/scripts/reel-02.txt
```

It tells you what it wrote:

```
  reel-01.txt   45 words
  reel-02.txt   52 words
  reel-03.txt   empty -- write this one yourself or the reel is skipped
```

Open them in any text editor — Notepad is fine — rewrite whatever you like, save.
Then build with **the same command minus `--scripts`**:

```bash
./run.sh "URL"
```

```
    script (yours): 52 words
    narration 16.7s -> reel 30.0s
```

The picks are cached too, so they do not move between runs. Change one script and
only that reel changes.

To throw a script away and let the generator write it again, delete that file.

**An empty script** means that stretch had no speech to work from. The file is
still created, so you can write it yourself. Left empty, that reel is skipped.

**Prefer clicking?** The web page (`./serve.sh`, or `serve.bat` on Windows) does
the same two steps: press *Get the narration scripts*, edit them in the boxes
that appear, then press *Make the reels*.

> This is also how you narrate in another language: write the script in that
> language and pick a matching `--voice`. The automatic modes work from an
> English transcript, so they only produce English.

---

## Choosing how it is written

`--style` sets the writing. The default is `punchy`:

| Style | Reads like |
| --- | --- |
| `punchy` *(default)* | Fast recap. One idea per sentence, about ten words, plot in every line. Ends with a question to the viewer. |
| `action` | Escalating action beats, each bigger than the last. Concrete and physical — the weapon, the number, the count of men left. |
| `reveal` | Someone badly underestimated. The first half is how little they are thought of; then the truth, then the reaction. |
| `twist` | Opens on the strangest fact in the film, stated flatly, then goes back and earns it. The last sentence answers the first. |
| `cinematic` | Steadier, present tense, longer sentences. |

All of them are past tense and third person except `cinematic`, with sentences of
about ten words — which is how this kind of short actually reads.

**A style that pushes a shape will invent to fill it.** `action` in particular
wants every beat bigger than the last, so on a stretch where little happens it
supplies the escalation itself. Always read the scripts before rendering.

**Styles are files, in `styles/`.** One `.txt` each: a few `key: value` lines, a
blank line, then the writing rules. Drop a new file in and it appears in
`--style` and in the web page immediately. Copy an existing one to see the shape.

For a one-off, skip the folder:

```bash
echo "Past tense. Dry and understated. Never more than one clause." > my-style.txt
./run.sh "URL" --style-file my-style.txt
```

Two things worth knowing:

- **Style only applies when a local model writes the script.** Selecting
  sentences from the transcript cannot rewrite them into another tense.
- **Bigger models follow it more closely.** On `llama3.2` (3B) most parts come
  back in the right tense and the occasional one drifts into the present. If a
  part comes out wrong, the quickest fix is to edit that one script by hand —
  or pull a larger model and delete the script so it is written again.

## Choosing a voice

```bash
./run.sh --list-voices
```

The **multilingual** voices are the most natural and are listed first. The
default is `en-US-AndrewMultilingualNeural`.

```bash
./run.sh "URL" --voice en-US-BrianMultilingualNeural
./run.sh "URL" --voice en-GB-RyanNeural --rate "+8%"
```

`--rate` takes a percentage and accepts negatives — `"-5%"` for a slower, heavier
read. Anything past about `+15%` starts to sound rushed rather than energetic.

Pick the voice before you write scripts by hand. Changing the voice re-speaks
everything anyway, and different voices suit different writing.

---

## How length works

You do not have to count words. **The narration decides how long the reel is**,
not the other way round — a clip that outlives its script ends on dead air, and
one that ends early cuts the narrator off mid-sentence.

- `--duration 75` is the target. The script generators aim at roughly
  **3 words per second**, so ~75 seconds means ~229 words.
- After it is spoken, the reel is cut to the real length of the audio, plus a
  short tail (`--tail`, default 0.7s), clamped between `--min-duration` and
  `--max-duration`.
- That 3-words-per-second figure was measured from these voices, not assumed.
  They read noticeably faster than a human narrator does.

So if you write your own script, just write it — the reel will fit itself around
what you wrote. A rough guide:

| Reel length | Words |
| --- | --- |
| 30 seconds | ~90 |
| 60 seconds | ~180 |
| 90 seconds | ~275 |

---

## Captions come from the narration

You never time captions by hand. The voice reports exactly when it says each
word, and the captions are built from that, so they land on the syllable.

This is also why the captions always match the script: change the words, and the
burned-in captions, the `.srt`, and the subtitle track inside the `.mp4` all
follow automatically.

```bash
--caption-words 3     # words per burst (default 3)
--caption-size 0.045  # height, as a fraction of the frame
--no-burn             # keep the picture clean; subtitles only
```

---

## Writing narration that works

If you are writing your own, or judging what the model produced:

- **Earn the first three seconds.** The opening line is the whole reel. Lead with
  the strangest or most specific fact, not with setup.
- **Present tense, third person.** "He opens the door" carries better than "he
  opened the door."
- **Short sentences.** They get chopped into three-word captions, and long
  clauses break across bursts badly.
- **Do not narrate what is plainly on screen.** Say what it means, or what the
  viewer cannot see.
- **Do not quote dialogue.** The dialogue has been removed from the audio; a
  narrator quoting lines nobody can hear reads as confusing.
- **End on a hook, not a summary.** Stopping one beat early is better than
  explaining.
- **Read it aloud once.** If you stumble, the voice will too.

---

## Troubleshooting

**The narration is just characters' lines strung together.**
That is extractive mode working as designed. Use `--script ollama`, or write the
script yourself.

**`--script ollama` had no effect.**
Ollama was not reachable, so it fell back silently. Check it is running:

```bash
ollama list
curl http://127.0.0.1:11434/api/tags
```

Then pull the model you named: `ollama pull llama3.2`.

**My edit to the script did nothing.**
Check you edited `output/<title>/scripts/reel-01.txt` and saved it. Run with
`--scripts` to have the folder printed for you, and look for `script (yours)` in
the output of the next run — that line means your file was the one that was read.

**"script: empty (nothing said in this stretch)".**
There was too little speech there to write from, so the file was left empty and
that reel will be skipped. Write it yourself, or lower `--gap` so it picks
different stretches.

**The narrator talks over the whole reel with no pauses.**
The script is too long for the time. Cut words — the reel will shorten to fit.

**The voice step fails or hangs.**
That is the one part that needs the internet. Check your connection; it retries
three times before giving up.

**The narration sounds flat.**
Try another voice first — they differ a lot. `--rate "-5%"` adds weight. Beyond
that, it is the writing, not the voice.
