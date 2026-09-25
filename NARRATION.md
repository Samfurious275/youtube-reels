# Narration — what you need, and how to make it good

The narration is two separate things, and they fail for different reasons:

- **The words** — the script written for each reel.
- **The voice** — the speech that reads those words aloud.

The voice is good out of the box and needs almost nothing from you. **The words
are where the quality actually comes from**, and where you have the most control.

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

Every script is cached as a plain text file, and **the pipeline reads that file
back verbatim**. So you can take the writing over completely.

The run prints where the cache is:

```
  cache: /path/to/youtube-reels/work/03dee7c87ca1
```

Inside, one file per reel:

```
script-01.txt
script-02.txt
```

The workflow:

1. Run once to get the picks and the first drafts:
   ```bash
   ./run.sh "URL" --reels 5 --no-bg
   ```
2. Open `work/<id>/script-01.txt` and rewrite it however you like.
3. Run **exactly the same command again**. It re-speaks the new words, re-times
   the captions to them, and re-renders that reel.

```
    cached script: 52 words
    narration 16.7s -> reel 30.0s
```

The picks are cached too, so they do not move between runs. Only what you changed
is redone.

To throw a script away and let the generator try again, delete that one file.

> This is also how you narrate in another language: write the script in that
> language and pick a matching `--voice`. The automatic modes work from an
> English transcript, so they only produce English.

---

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
You probably edited `output/<title>/reel-01.txt`, which is only a copy of what was
used. Edit `work/<id>/script-01.txt` — the path printed as `cache:` at the start
of the run.

**"nothing said in this stretch; skipping".**
There was too little speech there to write from. Lower `--gap` so it picks
different stretches, or write that script by hand.

**The narrator talks over the whole reel with no pauses.**
The script is too long for the time. Cut words — the reel will shorten to fit.

**The voice step fails or hangs.**
That is the one part that needs the internet. Check your connection; it retries
three times before giving up.

**The narration sounds flat.**
Try another voice first — they differ a lot. `--rate "-5%"` adds weight. Beyond
that, it is the writing, not the voice.
