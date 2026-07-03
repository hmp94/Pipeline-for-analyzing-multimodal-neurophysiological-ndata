# Pipeline for Analyzing Multimodal Neurophysiological Data

A unified processing pipeline for simultaneous **EEG**, **fNIRS**, and **PPG** recordings collected during cognitive focus tasks.

---

## Overview

This pipeline takes raw CSV recordings from the Brain-Life device and produces:
- Signal quality reports for each modality
- EEG Focus Index (FI = β/α) timelines
- fNIRS HbO/HbR concentration changes via Modified Beer–Lambert Law
- PPG heart rate and signal quality metrics
- A combined multi-panel summary figure with Mann-Whitney U statistics

---

## Repository Structure

```
├── code/
│   ├── metadata.py                  # Single source of truth for all parameters
│   ├── run_pipeline.py              # Main entry point — runs all steps
│   ├── eeg_fi_line_chart.py         # EEG Focus Index standalone chart
│   ├── fnirs_analysis.py            # fNIRS SCI, HbO/HbR quality check
│   ├── fnirs_stroop_pipeline.py     # Alternative fNIRS pipeline (Stroop MATLAB logic)
│   ├── csv_to_edf_denoised.py       # EEG CSV → EDF conversion with denoising
│   ├── PPG_check_for_T (1).py       # PPG quality check module
│   └── f-NIRS_check_for_T (1).py   # fNIRS quality check module
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
pip install numpy scipy matplotlib pandas pyedflib
```

All configurable parameters (durations, sampling rates, channel names, paths) live in `metadata.py`. Edit that file only — all scripts import from it.

---

## Usage

### Run the full pipeline on a single file

```bash
python run_pipeline.py data/raw/csv/subject.csv data/raw/edf \
    --summary-save graph/summary
```

### Run on all CSV files in a folder

```bash
python run_pipeline.py data/raw/csv/ data/raw/edf \
    --summary-save graph/summary
```

### Run the standalone EEG FI chart

```bash
python eeg_fi_line_chart.py
```

### Run the standalone fNIRS chart

```bash
python fnirs_analysis.py data/raw/csv/subject.csv
```

---

## Pipeline Steps

| Step | Description |
|------|-------------|
| 1. EEG | Quality checks (correlation, zero-signal, artifact ratio, band noise) + EDF export |
| 2. fNIRS | Scalp Coupling Index (SCI), SNR, CV, ΔOD, MBLL → HbO/HbR |
| 3. PPG | SNR, entropy, template matching, perfusion index |
| 4. FI | Focus Index (β/α) timeline from EDF via sliding-window Welch PSD |
| 5. Summary | Combined 4-panel figure + Mann-Whitney U statistics table |

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
