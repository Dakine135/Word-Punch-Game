# Word Punch

A reading game: sight words (or letters) fall from the sky over a mirrored camera view.
**Read the word out loud** and it glows gold. Then **punch up** under it to launch a fist rocket and smash it.

- Offline speech recognition (Vosk), listening only for the words in play
- Pose tracking (MediaPipe) for up to 3 players
- School sight-word lists, K and 1st grade, Q1–Q4 (`word_punch/data/words.toml`), plus letters
- Three modes:
  - **split**: a lane per kid, each at their own level
  - **coop**: one shared sky with both kids' words mixed in
  - **competitive**: the same words for everyone, and the first punch scores
- Scoring: harder words, faster reading and faster punching earn more points, plus combos
- Speed adapts to how fast the kids read, and the level goes up once every word is mastered
- Lives (default) or `--gentle`: no game over, and missed words come back
- **Round goals** (Settings): after N words, after N minutes, or when the level is mastered;
  the race mode is first to the goal. Each side shows "Finished!", then "Round complete!"
- **Punch or Slice**: rocket punches, or swipe through words Fruit-Ninja style (picked on the
  mode screen; mouse drag slices in `--sim`)
- **Five games** (picked on the start screen):
  - *Word Punch*: read the falling words, then punch or slice them
  - *Catch the Word*: the game says a word, find it and hit it (no reading aloud needed)
  - *Whack-a-Word*: words pop out of holes; read it, whack it before it hides
  - *Boss Battle*: break words to hurt the monster, then beat its final 3-hit word
  - *Sentence Builder*: read and hit floating words in order to build a sentence
  - plus a *Tag team* mode: one kid reads, the other punches
- **Rewards**: up to 3 stars per round unlock camera hats and glove/blade colours
  (Dress up! on the start screen); golden, freeze and giant power-up words; music
- **Voice**: missed words are read aloud (offline Piper voice)
- **Parent report**: Players screen (P) -> G opens a printable progress page per kid

## Setup (Windows laptop with an NVIDIA GPU)

Lives at `D:\WordPunch` (game, models and Python environment together).

```bash
cd /d D:\WordPunch
py -3.11 -m venv .venv
.venv\Scripts\pip install -r requirements-lock.txt --extra-index-url https://download.pytorch.org/whl/cu128
.venv\Scripts\python tools/fetch_models.py
```

`requirements-lock.txt` pins the exact versions that are known to work (including the CUDA
build of PyTorch); `requirements.txt` lists the main packages. Downloaded models (YOLO, Vosk,
Piper, and Whisper in `models/hf`) stay in `models/`.

### Models (all offline, on this laptop)

| Job | Model | Why |
|---|---|---|
| Pose | **YOLO11x-pose** (Ultralytics, GPU) | steady (1.3 px/frame wobble vs 9.7 for MediaPipe), finds the player every frame, tracks each kid by ID |
| Speech | **Vosk en-us-0.22** listening for the on-screen words | fast: reacts while the kid is still talking |
| Speech, 2nd opinion | **Whisper large-v3-turbo** (GPU) picks the on-screen word | runs when Vosk hears a voice but can't place the word - the kids' main problem |
| Voice | **Piper** en_US-lessac-medium | reads words aloud |

Free-transcription Whisper and Parakeet were tested too, but they're poor at lone short
words ("a", "I", "the" came out as "Okay.", "Bye."), so Whisper is used to *choose* among
the on-screen words instead.

Desktop shortcut (double-click to play, fullscreen, no console window):

```bash
.venv\Scripts\python tools/make_shortcut.py
```

It runs `launch_word_punch.pyw`; if the game ever stops with an error, details are in
`logs/last_run.log`.

## Play

```bash
python -m word_punch --player Sam:k3 --player Max:letters
python -m word_punch --mode coop --gentle --player Sam:k2 --player Max:letters
python -m word_punch --mode competitive --player Sam:k2 --player Max:k1
python -m word_punch --sim     # no camera/mic: type a word + Enter to "say" it, click to punch
python -m word_punch --game boss --mode coop --player Sam:k3 --player Max:letters
python -m word_punch.report   # parent progress report
```

**Levels:** `letters k1 k2 k3 k4 g1q1 g1q2 g1q3 g1q4 g2a g2b g3a g3b g4 g5 g6 g7 g8 g9 g10 g11 g12`

**Keys:**

| Key | Action |
|---|---|
| Esc | Quit |
| F11 or Alt+Enter | Fullscreen on/off. Scales to any screen; set `[game] fullscreen = true` in settings.toml to always start fullscreen |
| F3 | Debug info (fps, heard words) |
| F2 | Pause |
| Enter | Play again |

**Other flags:**

| Flag | What it does |
|---|---|
| `--mic "Arctis"` | Pick a mic by name |
| `--letters-easy` | Any sound unlocks the only letter in a lane |
| `--lives 5` | Change the number of lives |

## Testing tools

```bash
python tools/punch_playground.py               # practice punching: skeletons, words auto-unlock,
                                                # live punch meters + tuning keys (S saves)
python tools/punch_playground.py --no-camera    # animation test: click to punch
python tools/pose_spike.py                      # bare skeletons + PUNCH! detection
python tools/speech_spike.py --levels k2 k3     # flashcards: measures recognition on the kids' voices
                                                # Tab / Shift+Tab picks the mic (saved for the game too),
                                                # and the level bar shows whether the mic hears anything.
                                                # Shows what you actually said (free transcript with
                                                # confidence) next to what the game heard; type any
                                                # word + Enter to test it.
python -m pytest
```

## Settings

On the start screen press **S** (or click **Settings** in the corner) for camera, mic, game,
punch, sound and display options. Changes save to `settings.toml` and camera/mic changes apply
live. **P** (or **Players**) opens parent setup for the kids' profiles.

## Tuning

Copy any section of `word_punch/default_settings.toml` into a `settings.toml` at the project root and change the values. Useful settings:

| Setting | What it controls |
|---|---|
| `[punch] min_rise` / `min_speed` | How big and fast a punch must be |
| `[difficulty] start_fall` | Starting speed |
| `[rules] mastery_hits` | Reads needed per word before the level goes up |
| `[speech] device` | Which mic to use |
| `[camera] index` | Which camera to use |

## Hardware

| Hardware | Details |
|---|---|
| Laptop with an NVIDIA GPU | Runs everything (pose + speech models on the GPU). Built-in or USB webcam, any mic. |

(A Raspberry Pi was the original plan; it was dropped so the game can use the laptop's GPU.)

## Project layout

| Path | Contents |
|---|---|
| `word_punch/game/` | Game rules: no pygame, fully unit tested |
| `word_punch/vision/` | Camera + pose process, player tracker, punch detector |
| `word_punch/speech/` | Mic + Vosk process, word matcher (homophones, letter names/sounds) |
| `word_punch/ui/` | Rendering, effects, synthesized sound effects |
| `word_punch/data/words.toml` | Word lists, homophones, letter aliases |
| `tools/` | Model downloader and test tools |

## Roadmap

- [x] Speech + pose pipelines, test tools
- [x] Playable game: 3 modes, scoring, lives/gentle, adaptive speed, level mastery
- [ ] Kid profiles with saved progress
- [ ] Recorded voice reads missed words aloud (Piper TTS)
- [ ] Hands-free menus (hover to select), results screen
- [x] GPU models: YOLO11-pose, Whisper second opinion (Pi plan dropped)

Font: [Andika](https://software.sil.org/andika/) by SIL International (OFL), designed for beginning readers.

Music (all CC0 / public domain, from OpenGameArt.org, downloaded by `tools/fetch_models.py`):
[Happy Clappy Loop](https://opengameart.org/content/happy-clappy-loop) (menus),
[The Arplands](https://opengameart.org/content/the-arplands) by LordZintick and
[Happy Adventure](https://opengameart.org/content/happy-adventure-loop) by TinyWorlds (games),
[Boss Fight Bounce](https://opengameart.org/content/boss-fight-bounce) by Locomule (boss battle),
[8 Bit Concentration Loop](https://opengameart.org/content/8-bit-concentration-loop) by cosmac
(Catch the Word, Sentence Builder). Thank you!
