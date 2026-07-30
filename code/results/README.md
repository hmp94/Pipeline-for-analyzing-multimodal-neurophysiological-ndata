# `code/results/` — recorded data, split by source

```
code/results/
├── behaviors/                              # PsychoPy sessions — the only folder the code writes
│   └── <participant>_<YYYYMMDD_HHMMSS>/
│       ├── task.csv                        # every trial/event, keyed by task_type
│       └── metadata.json                   # demographics, task order, completion, scores, aborted
├── eeg_bl/                                 # Brain-Life headband recordings (copied in by hand)
└── eeg_natus/                              # Natus clinical EEG exports (copied in by hand)
```

## `behaviors/`

Written automatically by `code/experiment/experiment_io.py` (`BEHAVIOR_SUBDIR`). Both
`run_all_experiments.py` and each task run on its own create exactly one folder per run. The path
is resolved relative to `experiment_io.py`, not the shell's working directory, so it is the same
folder wherever you launch from. Group `task.csv` by its `task_type` column to split the tasks back
apart; the resting baseline appears as `baseline_start` / `baseline_end` marker rows.

Don't create folders here by hand — the experiment code owns this directory.

## `eeg_bl/` — Brain-Life headband

Raw device CSV, recorded alongside the sessions in `behaviors/`. Filenames are as the device
delivers them, `<subject>_<day>_<HH>_<MM>_F0-F1-…-F12.csv`, where the time is when the recording
*started*. Don't rename them: the name is the only provenance link back to a behavioural session.

Despite the folder name these files are **not EEG-only** — five columns spanning three modalities,
per the mapping in `code/analysis/metadata.py`:

| Column | Signal | Rate |
|--------|--------|------|
| `Header 24 Data` | EEG AF4 (differential AF4−T8) | 244 Hz |
| `Header 25 Data` | PPG | 100 Hz |
| `Header 26 Data` | EEG AF3 (differential AF3−T7) | 244 Hz |
| `Header 27 Data` | fNIRS red, ~730 nm | 100 Hz |
| `Header 28 Data` | fNIRS infrared, ~850 nm | 100 Hz |

Verified against the data: both EEG columns carry a 50.1 Hz mains peak plus an 8.1 Hz alpha peak;
PPG and both fNIRS columns agree on a 1.200 Hz cardiac rhythm (72 bpm), and the fNIRS pulsatile
amplitude is 1.85× larger on IR than on red, the correct ordering for 850 vs 730 nm.

**The row layout is blocked, not interleaved.** The two rates share one row grid, but the slower
signals are packed at the top rather than spread through it: in `ban_29_14_40`, rows 0–166,445 carry
all five columns and rows 166,446–405,488 carry the two EEG columns only. So the EEG gives
405,489 samples / 244 Hz = 1661.8 s and PPG/fNIRS give 166,446 / 100 Hz = 1664.5 s — the same
recording, written at two rates. Read the slower columns by dropping blanks and dividing by 100 Hz;
do not treat a row index as a timestamp for them.

One consequence worth knowing: `fnirs_check.truncate_nan()` cuts at the *first* blank rather than
dropping blanks, which is only equivalent because the blanks are contiguous at the tail. If a future
export ever interleaves them, fNIRS would silently collapse to a handful of samples while PPG
(which calls `.dropna()`) would survive.

Verify integrity with `shasum -a 256 -c SHA256SUMS.txt`.

## `eeg_natus/` — Natus clinical EEG

Reserved for recordings from the Natus clinical system: hospital-grade amplifier, full multi-channel
10–20 scalp montage, its own export format (proprietary `.e`, or EDF). This is the clinical-quality
reference the two-channel Brain-Life headband is compared against. Empty for now — the folder exists
so incoming clinical exports never get mixed in with the headband CSVs.

## Not a pipeline input

`data/raw/csv/` holds the same file format from the same device, but those are the **12-task
analysis corpus** (37–39 min per recording). The files here are **7-task battery** sessions (~28 min).
Don't cross-copy them: the task/rest windowing in `code/analysis/metadata.py` assumes the 12-task
timeline and would segment these wrongly.

`code/analysis/` reads the absolute paths configured in its own `metadata.py`, never this tree.
The experiment and the analysis pipeline are deliberately separate projects — dropping a CSV into
`eeg_bl/` does not feed it to `run_pipeline.py`, and `DATA_CSV_DIR` should not be repointed here.
