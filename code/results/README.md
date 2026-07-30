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
| `Header 24 Data` | EEG AF4 (differential AF4−T8) | 244 Hz, dense |
| `Header 25 Data` | PPG | 100 Hz, sparse |
| `Header 26 Data` | EEG AF3 (differential AF3−T7) | 244 Hz, dense |
| `Header 27 Data` | fNIRS red, ~730 nm | 100 Hz, sparse |
| `Header 28 Data` | fNIRS infrared, ~850 nm | 100 Hz, sparse |

There is one row per EEG sample at 244 Hz; the PPG and fNIRS columns are left empty on rows that
fall between their 100 Hz samples, so roughly 59% of cells in those three columns are blank.

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
