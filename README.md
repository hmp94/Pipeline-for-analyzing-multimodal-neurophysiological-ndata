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
