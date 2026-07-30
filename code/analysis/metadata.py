"""
metadata.py — single source of truth for all experiment parameters.
Edit this file only; all analysis scripts import from here.
"""

import os

import numpy as np

# ── Paths — 12-block corpus (absolute, outside the repo) ──────────────────────
DATA_CSV_DIR    = "/Users/minhphan/Documents/Brain-Life/data/raw/csv"
DATA_EDF_DIR    = "/Users/minhphan/Documents/Brain-Life/data/raw/edf/good"
GRAPH_FNIRS_DIR   = "/Users/minhphan/Documents/Brain-Life/graph/fnirs"
GRAPH_EEG_DIR     = "/Users/minhphan/Documents/Brain-Life/graph/eeg"
GRAPH_SUMMARY_DIR = "/Users/minhphan/Documents/Brain-Life/graph/summary"

# ── Paths — 7-block PsychoPy battery (repo-relative) ──────────────────────────
# Resolved from this file's location, not the working directory, so the battery
# entry points behave the same wherever they are launched from.
_ANALYSIS_DIR     = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT         = os.path.dirname(os.path.dirname(_ANALYSIS_DIR))
EEG_BL_DIR        = os.path.join(REPO_ROOT, "code", "results", "eeg_bl")
BEHAVIORS_DIR     = os.path.join(REPO_ROOT, "code", "results", "behaviors")
BATTERY_EDF_DIR   = os.path.join(REPO_ROOT, "data", "derived", "eeg_bl", "edf")
BATTERY_GRAPH_DIR = os.path.join(REPO_ROOT, "graph", "eeg_bl")

# ── Shared timeline ───────────────────────────────────────────────────────────
TASK_DUR     = 110   # seconds — duration of each task/baseline block
PREFOCUS_DUR = 10    # seconds — pre-focus window after every break

REST_DUR = 60  # seconds — rest period between blocks (all signals)

# ── fNIRS device ──────────────────────────────────────────────────────────────
FNIRS_FS          = 100          # Hz
FNIRS_COL_RED     = "Header 27 Data"   # ~730 nm
FNIRS_COL_IR      = "Header 28 Data"   # ~850 nm

# Beer–Lambert extinction coefficients [RED, IR] × [HbO, HbR]  (mM⁻¹ cm⁻¹)
FNIRS_EXT_COEF    = np.array([[446.0,  1115.88],
                               [1022.0,  692.36]], dtype=float)
FNIRS_DISTANCE_CM = 3.5          # source–detector separation (cm)
FNIRS_DPF         = (6.0, 6.0)   # differential pathlength factor [RED, IR]

# Frequency bands
FNIRS_HEMO_BAND   = (0.01, 0.1)  # Hz — hemodynamic bandpass (task band; 0.1 Hz
                                 # upper cut removes Mayer waves ~0.1 Hz and
                                 # respiration ~0.2-0.3 Hz. Was 0.8, which let
                                 # that fluctuation ride on the slow response.)
FNIRS_SCI_BAND    = (0.8,  2.0)  # Hz — scalp coupling index (cardiac)

# Baseline for ΔOD
FNIRS_BASELINE_SKIP_S = 0.0      # seconds to skip at start before baseline window
FNIRS_BASELINE_LEN_S  = 8.0      # seconds — baseline window length

# Denoising defaults
FNIRS_USE_HAMPEL        = True
FNIRS_HAMPEL_WINDOW_SEC = 0.25
FNIRS_HAMPEL_N_SIGMAS   = 6.0
FNIRS_USE_DWT           = True
FNIRS_DWT_WAVELET       = "db4"
FNIRS_DWT_THRESHOLD     = 1.0

# ── EEG device ────────────────────────────────────────────────────────────────
EEG_FS        = 244              # Hz
EEG_CHANNELS  = ("AF3_processed", "AF4_processed")   # channels used for FI computation
EEG_ALPHA     = (8,  13)         # Hz — alpha band
EEG_BETA      = (13, 30)         # Hz — beta band
EEG_FI_WIN    = 5                # seconds — sliding window for FI
EEG_FI_STEP   = 1                # seconds — step size for sliding window
