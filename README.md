# Pipeline for Analyzing Multimodal Neurophysiological Data

A unified processing pipeline for simultaneous **EEG**, **fNIRS**, and **PPG** recordings collected during cognitive focus tasks.

---

## Overview

This pipeline takes raw CSV recordings from the Brain-Life device and produces:
- Signal quality reports for each modality
- EEG Focus Index (FI = β/α) timelines
- fNIRS HbO/HbR concentration changes via Modified Beer–Lambert Law
- PPG heart rate and signal quality metrics
- A combined multi-panel summary figure with paired t-test statistics (task vs adjacent rest)

---

## Repository Structure

```
├── code/
│   ├── analysis/                    # Offline processing of recorded data
│   │   ├── metadata.py                  # Single source of truth for all parameters
│   │   ├── run_pipeline.py              # Main entry point — runs all steps + summary
│   │   ├── eeg_fi_line_chart.py         # EEG Focus Index (compute + standalone chart)
│   │   ├── csv_to_edf_denoised.py       # EEG CSV → EDF conversion with denoising
│   │   ├── WPT_denoising_threshold.py   # Wavelet packet denoising for EEG
│   │   ├── intensity_filter.py          # Hampel / DWT filters for fNIRS intensity
│   │   ├── fnirs_check.py               # fNIRS SCI + HbO/HbR via MBLL
│   │   ├── ppg_check.py                 # PPG quality check module
│   │   └── utils.py                     # Timeline, outlier/z-score, paired stats
│   └── experiment/                  # PsychoPy tasks run during acquisition
│       ├── passive_video_psychopy.py     # Passive visual observation (moving image, 3 min)
│       ├── fairy_tale_psychopy.py        # Story reading (paged, 3 min)
│       ├── addition_game_psychopy.py     # Sum of two 3-digit numbers (3 min)
│       ├── cpt_x_psychopy.py             # CPT-X sustained attention (X→C, others→SPACE, 3 min)
│       ├── multiplication_game_psychopy.py  # Product of two 2-digit numbers (3 min)
│       └── stroop_game_psychopy.py       # Stroop — respond to ink colour (C/M, 5 min)
├── data/
│   └── raw/
│       ├── csv/                     # Raw CSV recordings per subject
│       └── edf/
│           ├── good/                # EDF files that passed quality check
│           └── bad_denoised/        # EDF files that failed — denoised fallback
├── graph/
│   ├── summary/                     # Combined 4-panel summary PNGs
│   ├── eeg/                         # EEG FI standalone charts
│   ├── fnirs/                       # fNIRS HbO/HbR standalone plots
│   └── fnirs_stroop/                # Stroop-method fNIRS plots
└── documents/                       # Protocol & reference documents
```

---

## Task Timeline

All signals share the same segmentation:

```
F0 (baseline, 110s) → PRE-FOCUS (10s) → F1 (110s) → REST (60s) → PRE-FOCUS (10s) → F2 → ...
```

- **F0**: Resting baseline — no break after it, goes straight to pre-focus
- **Task blocks (F1–F12)**: Active cognitive tasks, 110 s each
- **REST**: 60 s break between task blocks
- **PRE-FOCUS**: 10 s transition window before each task

---

## Setup

```bash
# analysis
pip install numpy scipy matplotlib pandas pyedflib

# experiment (acquisition machine only)
pip install psychopy
```

All configurable analysis parameters (durations, sampling rates, channel names, paths) live in `code/analysis/metadata.py`. Edit that file only — all analysis scripts import from it.

---

## Usage

### Run the full pipeline on a single file

```bash
python code/analysis/run_pipeline.py data/raw/csv/subject.csv data/raw/edf \
    --summary-save graph/summary
```

### Run on all CSV files in a folder

```bash
python code/analysis/run_pipeline.py data/raw/csv/ data/raw/edf \
    --summary-save graph/summary
```

### Run the standalone EEG FI chart

```bash
python code/analysis/eeg_fi_line_chart.py
```

### Analyse a PsychoPy battery session (`code/results/eeg_bl/`)

```bash
python code/analysis/run_pipeline.py --battery --dry-run   # pairings + timelines only
python code/analysis/run_pipeline.py --battery             # figures -> graph/eeg_bl/
```

The two commands above assume the 12-block protocol, whose block order is encoded in the
recording's filename (`…_F0-F1-…-F12.csv`). Recordings from the 7-block PsychoPy battery in
`code/experiment/` need `--battery` instead, because their block order is **randomized per session
and stored in `metadata.json`**, not in the filename. It pairs each recording in
`code/results/eeg_bl/` with a session folder in `code/results/behaviors/`, builds the timeline from
that session's `task_order` (the session-timeline section of `utils.py`), and hands it to the same
`run_pipeline()` code — so the figures are identical in form to the 12-block ones, only with real
block names on the ruler.

Recordings are named by informal nickname while sessions are keyed by student ID, so the pairing
falls back to wall-clock containment. Anything unmatched or ambiguous is reported and analysed with
generic block labels rather than guessed at; use `--map <csv>=<session>` to state a pairing
explicitly. Intermediate EDFs go to `data/derived/` (gitignored — regenerate as needed).

> ### µV conversion overflow — fixed, and it invalidates older figures
>
> `convert_to_uV()` used to cast to `np.int16` before the DC offset was removed. These electrodes
> sit near −160…−200 mV, so **every** sample fell outside int16's ±32767 and the cast wrapped
> modulo 65536, injecting ±65536 µV step discontinuities that the downstream filters spread rather
> than removed. Whether a recording survived was luck — whether its range happened to sit inside one
> wrap band or straddle an edge:
>
> * `ban_29_14_40` — 0 induced steps, so the cast was a harmless constant offset;
> * `minhanh_29_16_29` — 41,329 steps on AF3, its `AF3_processed` uncorrelated with the true signal
>   (r = −0.12) and inflated 79× in amplitude;
> * **14 of the 15 files in `data/raw/csv/`** are affected too.
>
> Both copies of the conversion (`csv_to_edf_denoised.py`, `WPT_denoising_threshold.py`) now stay in
> float; `write_edf` already digitises via each signal's own `physical_min`/`physical_max`, so no
> manual narrowing was ever wanted. After the fix both battery recordings' processed channels match
> an independent correct computation at r = +1.0000.
>
> **Consequence:** every PNG under `graph/summary/` and `graph/eeg/` was produced before this fix and
> is affected for those 14 files. Re-run the pipeline to regenerate them.

### Browse the EEG in time windows

```bash
python code/analysis/eeg_fi_line_chart.py --windows                       # 20 s strips, 12/page
python code/analysis/eeg_fi_line_chart.py --windows --win 10 --strips 15 --only ban
python code/analysis/eeg_fi_line_chart.py --windows --from 700 --to 900
```

A 28-minute recording on one axis is ~340 samples per pixel, so a full-session plot shows only
the envelope — no waveform survives it, which is why it reads as a solid chunked band. This
renders the recording as a strip chart the way EEG is actually read: short windows at fixed
scale, stacked down the page, paginated to the end. Writes a multi-page PDF per recording plus
a PNG of one page.

### Blink / ocular artifact

Detection lives in the ocular-artifact section of `utils.py` (`detect_blinks`,
`band_power_clean`). It **excludes** spans rather than correcting them: with two bipolar frontal
derivations and no EOG channel there is no way to separate blink from brain — ICA needs more
channels — so interpolating would invent data and quietly lower the variance. Band power is
computed per surviving segment and PSD-averaged, so excising a span never introduces a splice
step of its own. Tune with `--blink-sd` (default 3.5 robust SDs; lower is more sensitive).

The threshold is calibrated against blink **rate**, the only external reference available:
spontaneous blinking runs ~10–20/min at rest and *drops* during focused visual work, so a
detector firing well above 20/min is discarding EEG rather than blinks. On `ban_29_14_40`, over
the 24.5 min it actually screens:

| `--blink-sd` | events/min | time excluded | mean span | |
|---|---|---|---|---|
| 5.0 | 6.6 | 8.5% | 0.86 s | under — misses task blinks |
| 4.0 | 13.4 | 16.5% | 0.83 s | conservative, defensible |
| **3.5** | **17.7** | **22.3%** | 0.85 s | **default — top of the normal band** |
| 3.0 | 22.1 | 29.1% | 0.89 s | over — above resting rate |
| 2.0 | 25.2 | 40.8% | 1.09 s | count saturates, spans just widen |

Below 3.0 the event count saturates near 600 while the excluded fraction climbs to 41–47% and
the mean span grows to 1.33 s — it stops finding new blinks and starts merging the ones it has,
so the extra cost buys nothing.

**The baseline is deliberately not screened.** `run_all_experiments` spends 50 s of its 182 s
baseline on guided blinks and eye movements — those artifacts are the protocol, they are what
pins the recording's time alignment, and five are individually logged in `task.csv`. Screening
there would flag the protocol as noise and inflate the amplitude threshold everywhere else.

At the default threshold: `ban_29_14_40` 437 spans / 22.3% of time excluded,
`minhanh_29_16_29` 293 spans / 27.0%.

> **What exclusion does and does not fix.** It removes discrete events, and on the strip charts
> the marked spans now cover essentially every visible deflection. But it does **not** clean up
> the band composition: sweeping the threshold from 6.0 to 1.5 robust SDs moves `ban`'s excluded
> fraction from 4.7% to 46.8% while its delta share goes 87.3% → 88.5%, i.e. not at all. Its
> low-frequency excess is *continuous drift*, not a train of separable blinks, so no exclusion
> threshold rescues the spectrum. (An earlier version of this README quoted per-band ratios of
> ×0.63/×0.14 as evidence exclusion worked — those compared a whole-record Welch against a
> per-segment average, two different estimators, and overstated the effect. The threshold sweep
> above is the internally consistent comparison.)
>
> A *local* threshold also sounds better than a global one and is worse here: when a block is
> blink-dense the local level rises to meet the blinks and the detector stops seeing them. Over
> `ban`'s visibly blink-heavy 200–220 s Addition block, global finds 13 spans and adaptive 4.
> Hence `adaptive=False` by default.

### Plot the processed EEG traces

```bash
python code/analysis/eeg_fi_line_chart.py --traces      # -> graph/eeg_bl/<stem>_eeg.png
```

Shows the EEG the analysis actually consumes — the `AF3_processed` / `AF4_processed` channels named
by `metadata.EEG_CHANNELS`, read from the exported EDF — over the same block timeline. Three panels:
each channel across the session with an artifact rug, then a short zoom where individual rhythms
resolve. A PASS/FAIL banner reports the baseline's eyes-closed alpha reactivity per channel, which
is the one built-in physiological validity check these recordings carry. The `_summary.png` /
`_FI.png` figures reduce all of this to one β/α ratio, so use this to see what that ratio came from.

> **The WPT denoising is computed and then ignored — but the denoised channel is not the answer.**
> When a recording fails the band-noise check the pipeline applies WPT denoising and writes it as a
> *separate* channel pair (`AF3_denoised`/`AF4_denoised`), routing the file to `edf/good_denoised/`.
> It does not overwrite `_processed`, and `metadata.EEG_CHANNELS` names `_processed`, so the Focus
> Index is computed from the channel that failed the check. `minhanh_29_16_29` is exactly this case:
> beta drops 2.8× on AF3 (64.8 → 23.3 µV²) while alpha barely moves (24.0 → 21.5), so its FI reads
> 2.70 from `_processed` against 1.08 from `_denoised`, and under the pipeline's own test the choice
> flips p = 0.118 (ns) to p = 0.003 (\*\*).
>
> Do **not** conclude `_denoised` holds the right value. The WPT runs at `level=3`, which at 244 Hz
> gives 15.25 Hz packets — so a "23–27 Hz" target thresholds the whole 15.25–30.5 Hz packet:
> measured attenuation is 5–17 dB across 18–30 Hz versus 0.84–0.96 gain across 8–12 Hz. The FI move
> is the filter's shape, not the participant's brain. And the 13.25–14.5 Hz interference that
> actually failed the check sits in the untouched 0–15.25 Hz packet and survives (28.4 → 12.5), so
> the post-WPT re-check passes because the denominator shrank, not because the artifact went away.
> **Neither channel yields a valid FI for that recording.** Raising the WPT level is the root fix;
> repointing `EEG_CHANNELS` alone would just swap one wrong number for another.

> **Output locations.** `run_pipeline.py` writes its summary PNGs to `--summary-save`
> (as shown above). The standalone `eeg_fi_line_chart.py` ignores that flag and always
> writes to the `GRAPH_*` paths defined in `code/analysis/metadata.py`, which are
> currently absolute (`/Users/minhphan/Documents/Brain-Life/...`). `eeg_fi_line_chart.py`
> takes no file argument — it batch-processes every EDF in `DATA_EDF_DIR`. Edit
> `metadata.py` to point these at your own machine.

---

## Experiment Tasks

The PsychoPy tasks in `code/experiment/` are run on the acquisition machine while EEG/fNIRS/PPG
are recorded. Every run — a whole session via `run_all_experiments.py`, or a single task on its
own — creates one folder per session at `code/results/behaviors/<participant>_<timestamp>/`
holding exactly two files: `task.csv` (every trial and event of the session in one table, keyed
by the `task_type` column) and `metadata.json` (demographics plus task order, which tasks
completed, per-task scores, and the `aborted` flag). That location is resolved relative to
`experiment_io.py` rather than the shell's working directory, so it is the same folder no matter
where you launch from.

> **Tuning the tasks.** Two central files hold everything you'd want to adjust:
> `content.py` for all on-screen **text**, and `settings.py` for all **numeric parameters**
> — durations, stimulus/response intervals, trial counts, the CPT-X target ratio, ink colours,
> font sizes, and the baseline/rest durations. Edit those rather than the individual task files.

The session opens with a resting baseline (eyes open 1m30, then eyes closed 1m30), then the
six focus tasks below in randomized order with a 1-minute rest between each.

| Task | Script | Description |
|------|--------|-------------|
| Passive video | `passive_video_psychopy.py` | Passive visual observation of continuous motion, no response, 3 min. Plays a drop-in `passive_video.*` file if present, else a self-contained optic-flow animation |
| Fairy tale | `fairy_tale_psychopy.py` | Silent reading of a paged story, page views logged with timestamps, 3 min |
| Addition | `addition_game_psychopy.py` | Sum two 3-digit numbers, type answer + ENTER, continuous for 3 min |
| CPT-X | `cpt_x_psychopy.py` | Sustained attention: letters flash 250 ms; X → C, any other letter → SPACE, 3 min |
| Multiplication | `multiplication_game_psychopy.py` | Multiply two 2-digit numbers, same format, 3 min |
| Stroop | `stroop_game_psychopy.py` | Respond to ink colour: C = blue/green, M = red/yellow. Word shown 250 ms, keys accepted only after it disappears, 5 min |

### Run the full session (recommended)

```bash
python code/experiment/run_all_experiments.py
```

`run_all_experiments.py` runs the baseline plus all six tasks in one session:

- The demographics dialog (participant, age, gender, handedness) is shown **once** at the start.
- Task order is **randomized** each session.
- One window is shared by every task, so the screen never flashes between them — the transitions
  advance **automatically** (a short countdown), with no key press needed to confirm readiness.
  SPACE is only an optional early-skip; **ESC** aborts the whole session and saves partial data.
- The whole session lands in one folder, `code/results/behaviors/<participant>_<timestamp>/`,
  whose `metadata.json` records the randomized order, which tasks completed, and whether the
  session was aborted.

### Run a single task

Each script is still runnable on its own (it shows its own demographics dialog):

```bash
python code/experiment/stroop_game_psychopy.py
```

---

## Pipeline Steps

| Step | Description |
|------|-------------|
| 1. EEG | Quality checks (correlation, zero-signal, artifact ratio, band noise) + EDF export |
| 2. fNIRS | Scalp Coupling Index (SCI), SNR, CV, ΔOD, MBLL → HbO/HbR |
| 3. PPG | SNR, entropy, template matching, perfusion index |
| 4. FI | Focus Index (β/α) timeline from EDF via sliding-window Welch PSD |
| 5. Summary | Combined 4-panel figure + paired t-test statistics table (task vs adjacent rest) |

---

## Key Parameters (`metadata.py`)

| Parameter | Value | Description |
|-----------|-------|-------------|
| `TASK_DUR` | 110 s | Task/baseline block duration |
| `REST_DUR` | 60 s | Rest period between blocks |
| `PREFOCUS_DUR` | 10 s | Pre-focus window before each task |
| `EEG_FS` | 244 Hz | EEG sampling rate |
| `FNIRS_FS` | 100 Hz | fNIRS sampling rate |
| `EEG_CHANNELS` | AF3, AF4 | Channels used for FI computation |
| `EEG_ALPHA` | 8–13 Hz | Alpha band |
| `EEG_BETA` | 13–30 Hz | Beta band |
| `EEG_FI_WIN` | 5 s | Sliding window size for Welch PSD |
| `EEG_FI_STEP` | 1 s | Step size between windows |

---

## Output

Each subject produces:

| File | Location | Description |
|------|----------|-------------|
| `<stem>_summary.png` | `graph/summary/` | 4-panel figure: fNIRS HbO/HbR · PPG · EEG FI · stats table |
| `<stem>_FI.png` | `graph/eeg/` | Standalone EEG Focus Index chart with per-task mean lines |
| `<stem>_fnirs.png` | `graph/fnirs/` | Standalone fNIRS HbO/HbR chart with timeline shading |
| PPG standalone | — | *Coming soon* |
| `<stem>.edf` | `data/raw/edf/good/` | Exported EDF from EEG quality check |
