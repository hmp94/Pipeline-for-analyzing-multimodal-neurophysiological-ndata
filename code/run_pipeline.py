#!/usr/bin/env python3
"""
run_pipeline.py  —  unified multimodal neurophysiology processing pipeline.

Four steps are executed for every CSV recording:

  1. EEG   — quality checks (correlation, zero-signal, artifact ratio, band
              noise), WPT denoising when needed, EDF export
  2. fNIRS — Scalp Coupling Index, SNR, ΔOD, HbO / HbR via MBLL
  3. PPG   — SNR, entropy, template matching, perfusion index
  4. FI    — Focus Index (β/α) timeline chart from the EDF produced in step 1

Usage
-----
  python run_pipeline.py <csv_input> <edf_output> [options]

  <csv_input>   path to a single .csv file  OR  a folder of .csv files
  <edf_output>  folder where EDF files (and quality sub-folders) will be written

Options
-------
  --eeg-fs N        EEG sampling rate Hz          (default 244)
  --device          EEG device: BL or MUSE        (default BL)
  --fnirs-fs N      fNIRS sampling rate Hz         (default 100)
  --ppg-fs N        PPG  sampling rate Hz          (default 100)
  --ppg-skip N      PPG samples to ignore at start (default 0)
  --fnirs-hampel    Hampel spike filter on fNIRS intensity
  --fnirs-dwt       DWT wavelet denoising on fNIRS intensity
  --no-plot         Suppress all matplotlib windows
  --fi-save DIR     Save FI plots to DIR (default: show interactively)

Example
-------
  # single file, plots suppressed, FI charts saved
  python run_pipeline.py data/raw/csv/subject01.csv data/edf \\
      --no-plot --fi-save data/graph

  # whole folder, default settings
  python run_pipeline.py data/raw/csv/ data/edf
"""

import argparse
import importlib.util
import os
import shutil
import sys
import tempfile


# ── Dynamic import  (filenames contain spaces / hyphens) ─────────────────────
def _import_path(module_name, file_path):
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    mod  = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


CODE_DIR = os.path.dirname(os.path.abspath(__file__))

# Ensure sibling modules (intensity_filter, WPT_denoising_threshold, …) are
# importable when the dynamically-loaded modules do their own top-level imports.
if CODE_DIR not in sys.path:
    sys.path.insert(0, CODE_DIR)

_csv_to_edf_mod = _import_path(
    "csv_to_edf_denoised",
    os.path.join(CODE_DIR, "csv_to_edf_denoised.py"),
)
_fnirs_mod = _import_path(
    "fnirs_check",
    os.path.join(CODE_DIR, "f-NIRS_check_for_T (1).py"),
)
_ppg_mod = _import_path(
    "ppg_check",
    os.path.join(CODE_DIR, "PPG_check_for_T (1).py"),
)
_fi_mod = _import_path(
    "eeg_fi",
    os.path.join(CODE_DIR, "eeg_fi_line_chart.py"),
)

convert_csv_to_edf = _csv_to_edf_mod.convert_csv_to_edf
check_fNIRS_SCI    = _fnirs_mod.check_fNIRS_SCI
check_ppg          = _ppg_mod.check_ppg
plot_fi_timeline   = _fi_mod.plot_fi_timeline


# ── Helpers ───────────────────────────────────────────────────────────────────
def _section(title):
    pad = max(0, 55 - len(title))
    print(f"\n── {title} {'─' * pad}")


def _find_edf(edf_dir, stem):
    """Return the first EDF found for this recording (good > good_denoised > bad_denoised)."""
    for sub in ("good", "good_denoised", "bad_denoised"):
        path = os.path.join(edf_dir, sub, stem + ".edf")
        if os.path.exists(path):
            return path
    return None


def _status_str(val):
    if val is None:
        return "skipped"
    if isinstance(val, dict):
        return "OK"
    if val == "done":
        return "OK"
    return str(val)


def _print_summary(results):
    print(f"\n{'=' * 60}")
    print("PIPELINE SUMMARY")
    print(f"{'=' * 60}")
    for r in results:
        name = os.path.basename(r["file"])
        print(f"\n  {name}")
        print(f"    EEG   : {_status_str(r.get('eeg'))}")
        print(f"    fNIRS : {_status_str(r.get('fnirs'))}")
        print(f"    PPG   : {_status_str(r.get('ppg'))}")
        print(f"    FI    : {r.get('fi', 'skipped')}")
    print()


# ── Core pipeline ─────────────────────────────────────────────────────────────
def run_pipeline(
    csv_input,
    edf_output_dir,
    # EEG
    eeg_sampling_rate=244,
    eeg_device="BL",
    # fNIRS
    fnirs_fs=100,
    fnirs_col_red="Header 27 Data",
    fnirs_col_ir="Header 28 Data",
    fnirs_signal_range=None,
    fnirs_use_hampel=False,
    fnirs_use_dwt=False,
    fnirs_plot=True,
    # PPG
    ppg_column="Header 25 Data",
    ppg_fs=100,
    ppg_first_samples_to_ignore=0,
    ppg_plot=False,
    # Focus Index
    fi_channels=("AF3_processed", "AF4_processed"),
    fi_win_sec=5,
    fi_step_sec=1,
    fi_save_dir=None,
):
    """Run all four pipeline steps on one CSV file or a folder of CSV files.

    Returns a list of per-file result dicts with keys:
      file, eeg, fnirs, ppg, fi
    """
    # Collect input files
    if os.path.isdir(csv_input):
        csv_files = sorted(
            os.path.join(csv_input, f)
            for f in os.listdir(csv_input)
            if f.endswith(".csv")
            and not os.path.isdir(os.path.join(csv_input, f))
        )
    else:
        csv_files = [csv_input]

    print(f"\n{'=' * 60}")
    print(f"Pipeline  —  {len(csv_files)} file(s)  →  {edf_output_dir}")
    print(f"{'=' * 60}")

    results = []

    for csv_path in csv_files:
        stem = os.path.splitext(os.path.basename(csv_path))[0]
        print(f"\n{'#' * 60}")
        print(f"  FILE: {stem}")
        print(f"{'#' * 60}")

        record = {"file": csv_path}

        # ── Step 1: EEG ──────────────────────────────────────────────────────
        _section("STEP 1 — EEG quality check + EDF export")
        try:
            # convert_csv_to_edf processes a whole folder; isolate this file
            # in a temporary directory so other files are not affected.
            tmp = tempfile.mkdtemp()
            shutil.copy2(csv_path, tmp)
            convert_csv_to_edf(tmp, edf_output_dir, eeg_sampling_rate, device=eeg_device)
            shutil.rmtree(tmp, ignore_errors=True)
            record["eeg"] = "done"
        except Exception as exc:
            print(f"  [EEG ERROR] {exc}")
            record["eeg"] = f"error: {exc}"

        edf_path = _find_edf(edf_output_dir, stem)

        # ── Step 2: fNIRS ────────────────────────────────────────────────────
        _section("STEP 2 — fNIRS SCI + HbO/HbR quality check")
        try:
            record["fnirs"] = check_fNIRS_SCI(
                csv_path,
                signal_range=fnirs_signal_range,
                plot=fnirs_plot,
                fs=fnirs_fs,
                col_red=fnirs_col_red,
                col_ir=fnirs_col_ir,
                use_hampel=fnirs_use_hampel,
                use_dwt=fnirs_use_dwt,
            )
        except Exception as exc:
            print(f"  [fNIRS ERROR] {exc}")
            record["fnirs"] = f"error: {exc}"

        # ── Step 3: PPG ──────────────────────────────────────────────────────
        _section("STEP 3 — PPG quality check")
        try:
            record["ppg"] = check_ppg(
                csv_path,
                first_samples_to_ignore=ppg_first_samples_to_ignore,
                column_name=ppg_column,
                fs=ppg_fs,
                plot=ppg_plot,
                show_plots=ppg_plot,
            )
        except Exception as exc:
            print(f"  [PPG ERROR] {exc}")
            record["ppg"] = f"error: {exc}"

        # ── Step 4: Focus Index timeline ─────────────────────────────────────
        _section("STEP 4 — Focus Index (β/α) timeline")
        if edf_path:
            print(f"  EDF: {edf_path}")
            try:
                fi_save = None
                if fi_save_dir:
                    os.makedirs(fi_save_dir, exist_ok=True)
                    fi_save = os.path.join(fi_save_dir, stem + "_FI.png")
                plot_fi_timeline(
                    edf_path,
                    channels=fi_channels,
                    win_sec=fi_win_sec,
                    step_sec=fi_step_sec,
                    save_path=fi_save,
                )
                record["fi"] = fi_save if fi_save else "shown"
            except Exception as exc:
                print(f"  [FI ERROR] {exc}")
                record["fi"] = f"error: {exc}"
        else:
            print("  Skipped — no EDF produced for this recording.")
            record["fi"] = "skipped"

        results.append(record)

    _print_summary(results)
    return results


# ── CLI ───────────────────────────────────────────────────────────────────────
def _parse_args():
    p = argparse.ArgumentParser(
        description="Unified multimodal neurophysiology pipeline (EEG + fNIRS + PPG)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("csv_input",      help="CSV file or folder of CSV files")
    p.add_argument("edf_output",     help="Output folder for EDF files")
    p.add_argument("--eeg-fs",       type=int, default=244,  help="EEG sampling rate (default 244)")
    p.add_argument("--device",       default="BL", choices=["BL", "MUSE"], help="EEG device type")
    p.add_argument("--fnirs-fs",     type=int, default=100,  help="fNIRS sampling rate (default 100)")
    p.add_argument("--ppg-fs",       type=int, default=100,  help="PPG sampling rate (default 100)")
    p.add_argument("--ppg-skip",     type=int, default=0,    help="PPG samples to ignore at start")
    p.add_argument("--fnirs-hampel", action="store_true",    help="Hampel filter on fNIRS intensity")
    p.add_argument("--fnirs-dwt",    action="store_true",    help="DWT denoising on fNIRS intensity")
    p.add_argument("--no-plot",      action="store_true",    help="Suppress all matplotlib windows")
    p.add_argument("--fi-save",      default=None,           help="Dir to save FI plots (default: show)")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    run_pipeline(
        csv_input=args.csv_input,
        edf_output_dir=args.edf_output,
        eeg_sampling_rate=args.eeg_fs,
        eeg_device=args.device,
        fnirs_fs=args.fnirs_fs,
        ppg_fs=args.ppg_fs,
        ppg_first_samples_to_ignore=args.ppg_skip,
        fnirs_use_hampel=args.fnirs_hampel,
        fnirs_use_dwt=args.fnirs_dwt,
        fnirs_plot=not args.no_plot,
        ppg_plot=not args.no_plot,
        fi_save_dir=args.fi_save,
    )
