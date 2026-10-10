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

## Setup (Windows laptop)

```bash
py -3.11 -m venv %USERPROFILE%\.venvs\word-punch
%USERPROFILE%\.venvs\word-punch\Scripts\pip install -r requirements.txt
%USERPROFILE%\.venvs\word-punch\Scripts\python tools/fetch_models.py
```

(The venv lives outside OneDrive on purpose.)

## Play

```bash
python -m word_punch --player Sam:k3 --player Max:letters
python -m word_punch --mode coop --gentle --player Sam:k2 --player Max:letters
python -m word_punch --mode competitive --player Sam:k2 --player Max:k1
python -m word_punch --sim     # no camera/mic: type a word + Enter to "say" it, click to punch
```

**Levels:** `letters k1 k2 k3 k4 g1q1 g1q2 g1q3 g1q4`

**Keys:**

| Key | Action |
|---|---|
| Esc | Quit |
| F11 | Fullscreen |
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
python tools/pose_spike.py                      # skeletons + PUNCH! detection, for tuning
python tools/speech_spike.py --levels k2 k3     # flashcards: measures recognition on the kids' voices
python -m pytest
```

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
| Laptop (development) | Any webcam and mic |
| Raspberry Pi 4 (target) | USB webcam and a USB conference mic. The camera, pose and speech work runs in separate processes. A lighter MoveNet pose backend is planned for the Pi. |

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
- [ ] Raspberry Pi 4 port (MoveNet backend, benchmarks, kiosk autostart)

Font: [Andika](https://software.sil.org/andika/) by SIL International (OFL), designed for beginning readers.
