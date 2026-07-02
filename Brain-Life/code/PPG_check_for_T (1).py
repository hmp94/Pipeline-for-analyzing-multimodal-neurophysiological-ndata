import os
import warnings

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.signal import butter, find_peaks, iirnotch, lfilter, savgol_filter, welch
from scipy.stats import kurtosis, skew, entropy

try:
    import neurokit2 as nk
except ImportError:
    nk = None

warnings.filterwarnings("ignore")

PPG_SAMPLING_RATE = 100
PLOT_OUTPUT_DIR = "ppg_plots"
RED = '\033[91m'
GREEN = '\033[92m'
YELLOW = '\033[93m'
RESET = '\033[0m'


def colored_flag(is_good):
    if isinstance(is_good, str):
        status = is_good.upper()
        if status.startswith("GOOD"):
            return f"{GREEN}{is_good}{RESET}"
        if status.startswith("BAD"):
            return f"{RED}{is_good}{RESET}"
        return is_good
    return f"{GREEN}GOOD{RESET}" if is_good else f"{RED}BAD{RESET}"

def colored_status_text(status):
    if status == "GOOD":
        return f"{GREEN}{status}{RESET}"
    if status == "BAD":
        return f"{RED}{status}{RESET}"
    return status


def calculate_entropy(signal):
    histogram, bin_edges = np.histogram(signal, bins=256, density=True)
    histogram = histogram + 1e-12  # Avoid log(0)
    ent = entropy(histogram, base=2)
    return ent



def resolve_column_name(df, column_name):
    df.columns = df.columns.str.strip()
    requested = column_name.strip()
    candidates = [requested, "Header 25 Data", "Header 25", "PPG_raw", "Signal Integer"]

    for candidate in candidates:
        if candidate in df.columns:
            return candidate

    raise KeyError(
        f"Column '{column_name}' was not found. Available columns: {list(df.columns)}"
    )


def truncate_at_first_nan(values):
    values = pd.Series(values)
    nan_positions = np.flatnonzero(values.isna().to_numpy())
    if len(nan_positions) == 0:
        return values
    return values.iloc[: nan_positions[0]]


def convert_to_raw(signal_integer):
    signal_integer = np.asarray(signal_integer, dtype=np.int32)
    raw_20bit = signal_integer & 0xFFFFF
    signed_value = np.where(raw_20bit >= (1 << 19), raw_20bit - (1 << 20), raw_20bit)
    return np.trim_zeros(signed_value, "b")


def dc_blocking_filter(data, alpha=0.99):
    data = np.asarray(data, dtype=float)
    if data.size == 0:
        return data

    y = np.zeros_like(data, dtype=float)
    y[0] = data[0]
    for i in range(1, len(data)):
        y[i] = data[i] - data[i - 1] + alpha * y[i - 1]
    return y


def butter_bandpass(lowcut, highcut, fs, order=4):
    nyq = 0.5 * fs
    low = lowcut / nyq
    high = highcut / nyq
    return butter(order, [low, high], btype="band")


def bandpass_filter(data, fs, lowcut=1, highcut=40, order=4):
    b, a = butter_bandpass(lowcut, highcut, fs, order=order)
    return lfilter(b, a, data)


def notch_filter(data, fs, freq=50.0, q=30.0):
    b, a = iirnotch(freq / (0.5 * fs), q)
    return lfilter(b, a, data)


def calculate_heartrate(ppg_signal, fs):
    peaks, _ = find_peaks(ppg_signal, distance=int(fs * 0.4))
    peak_intervals = np.diff(peaks) / fs

    if len(peak_intervals) == 0:
        return np.nan, peaks, np.array([])

    heart_rates = 60 / peak_intervals
    return np.mean(heart_rates), peaks, heart_rates


def bandpower(data, fs, band, window_sec=4):
    data = np.asarray(data, dtype=float)
    if data.size == 0:
        return np.nan

    fmin, fmax = band
    nperseg = min(len(data), int(window_sec * fs))
    freqs, psd = welch(data, fs=fs, nperseg=nperseg)
    idx_band = np.logical_and(freqs >= fmin, freqs <= fmax)

    if not np.any(idx_band):
        return 0.0

    return np.trapz(psd[idx_band], freqs[idx_band])


def calculate_snr_bandpower(
    signal,
    fs,
    signal_band=(0.5, 5),
    noise_band=((5, 20), (0.001, 0.5)),
    return_log = True
):
    signal_power = bandpower(signal, fs, signal_band)
    noise_power = bandpower(signal, fs, noise_band[0]) + bandpower(signal, fs, noise_band[1])

    if noise_power <= 0 or signal_power <= 0:
        return np.nan
    if return_log:
        return 10 * np.log10(signal_power / noise_power)

    return signal_power / noise_power

def preprocess_ppg(data, fs=PPG_SAMPLING_RATE, use_sg=True):
    dc_removed = dc_blocking_filter(data)
    filtered = bandpass_filter(dc_removed, fs, 0.5, 3)

    if use_sg and len(filtered) >= 19:
        filtered = savgol_filter(filtered, window_length=19, polyorder=5)

    return filtered


def fill_missing(values):
    return pd.Series(values).interpolate().bfill().ffill().to_numpy()


def save_or_show_plot(output_path=None, show=False):
    if output_path:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        plt.savefig(output_path, dpi=150)
        print(f"Saved plot: {output_path}")

    if show:
        plt.show()

    plt.close()


def safe_plot_name(data_path, suffix):
    base_name = os.path.splitext(os.path.basename(data_path))[0]
    return os.path.join(PLOT_OUTPUT_DIR, f"{base_name}_{suffix}.png")


def plot_psd(signal, fs, data_path, suffix, title="Power Spectral Density", show=False):
    freqs, psd = welch(signal, fs, nperseg=min(len(signal), fs * 4))
    plt.figure(figsize=(10, 6))
    plt.semilogy(freqs, psd, label="PSD")
    plt.title(title, fontsize=10)
    plt.xlabel("Frequency (Hz)", fontsize=8)
    plt.ylabel("Power Spectral Density", fontsize=8)
    plt.grid(True, which="both", linestyle="--", linewidth=0.5)
    plt.tick_params(axis="both", labelsize=8)
    plt.legend(fontsize=8)
    plt.tight_layout()
    # plt.show()
    save_or_show_plot(safe_plot_name(data_path, suffix), show=show)


def plot_ppg_segments(ppg_raw, ppg_filtered_sg, ppg_filtered_no_sg, fs, data_path, show=False):
    
    num_segments = 2
    boundaries = np.linspace(0, len(ppg_filtered_sg), num_segments + 1, dtype=int)
    segment_ranges = [(boundaries[i], boundaries[i + 1]) for i in range(num_segments)]

    for segment_idx, (start, end) in enumerate(segment_ranges, start=1):
        plt.figure(figsize=(12, 10))
        time_axis = np.arange(start, end) / fs

        plt.subplot(3, 1, 1)
        plt.plot(time_axis, ppg_raw[start:end], label="Raw", color="gray")
        plt.title(f"PPG Raw Optical Signals - BL - File: {data_path}", fontsize=8)
        plt.xlabel("Time (seconds)", fontsize=5)
        plt.ylabel("Intensity")
        plt.legend()
        plt.tick_params(axis="both", labelsize=8)
        plt.grid(True)

        plt.subplot(3, 1, 2)
        plt.plot(time_axis, ppg_filtered_sg[start:end], label="Filtered (with SG)", color="darkgreen")
        plt.plot(
            time_axis,
            ppg_filtered_no_sg[start:end],
            label="Filtered (without SG)",
            color="blue",
            alpha=0.7,
        )
        plt.title(f"PPG Filtered Optical Signals - BL - File: {data_path}")
        plt.xlabel("Time (seconds)", fontsize=5)
        plt.ylabel("Intensity")
        plt.legend()
        plt.tick_params(axis="both", labelsize=8)
        plt.grid(True)

        plt.subplot(3, 1, 3)
        heart_rate_sg, peaks_sg, _ = calculate_heartrate(ppg_filtered_sg[start:end], fs)
        peaks_in_range_sg = start + peaks_sg
        plt.plot(time_axis, ppg_filtered_sg[start:end], label="Filtered (with SG)", color="darkgreen")
        plt.plot(
            peaks_in_range_sg / fs,
            ppg_filtered_sg[peaks_in_range_sg],
            "ro",
            label="Peaks (SG)",
        )
        plt.title("PPG with Detected Peaks (with SG)")
        plt.xlabel("Time (seconds)")
        plt.ylabel("Amplitude")
        plt.legend()
        plt.grid(True)
        plt.text(
            0.05,
            0.95,
            f"Heart Rate (SG): {heart_rate_sg:.2f} bpm",
            transform=plt.gca().transAxes,
            fontsize=12,
            verticalalignment="top",
            bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.5),
        )
        plt.tight_layout()
        # plt.show()
        save_or_show_plot(
            safe_plot_name(data_path, f"segment_{segment_idx}"),
            show=show,
        )


def check_ppg(
    bl_data_path,
    first_samples_to_ignore=0,
    column_name="Header 25 Data",
    fs=PPG_SAMPLING_RATE,
    plot=False,
    show_plots=False,
):
    bl_ppg_data = pd.read_csv(bl_data_path)
    column_name = resolve_column_name(bl_ppg_data, column_name)

    ppg_values = pd.to_numeric(bl_ppg_data[column_name], errors="coerce")
    ppg_values = truncate_at_first_nan(ppg_values).dropna()
    ppg_raw = convert_to_raw(ppg_values.to_numpy())

    first_samples_to_ignore = max(0, int(first_samples_to_ignore))
    ppg_raw = ppg_raw[first_samples_to_ignore:]

    if len(ppg_raw) < fs:
        raise ValueError(
            f"PPG signal is too short after ignoring {first_samples_to_ignore} samples: "
            f"{len(ppg_raw)} samples remain."
        )

    ppg_raw = fill_missing(ppg_raw)
    print(f"PPG signal loaded: {len(ppg_raw)} samples, sampling rate: {fs} Hz")
    print(f"Entropy of raw PPG signal: {calculate_entropy(ppg_raw):.4f} bits")    
    ppg_filtered_sg = preprocess_ppg(ppg_raw, fs, use_sg=True)
    ppg_filtered_no_sg = preprocess_ppg(ppg_raw, fs, use_sg=False)

    if plot:
        plot_psd(ppg_raw, fs, bl_data_path, "psd_raw", title="PSD of Raw PPG Signal", show=show_plots)
        # plot_psd(
        #     ppg_filtered_sg,
        #     fs,
        #     bl_data_path,
        #     "psd_filtered_sg",
        #     title="PSD of Filtered PPG Signal (with SG)",
        #     show=show_plots,
        # )
        # plot_psd(
        #     ppg_filtered_no_sg,
        #     fs,
        #     bl_data_path,
        #     "psd_filtered_no_sg",
        #     title="PSD of Filtered PPG Signal (without SG)",
        #     show=show_plots,
        # )
        plot_ppg_segments(
            ppg_raw,
            ppg_filtered_sg,
            ppg_filtered_no_sg,
            fs,
            bl_data_path,
            show=show_plots,
        )

    print(f"PPG signal length: {len(ppg_raw)} samples")
    print("Check NaN values in the filtered PPG signal (with Savitzky-Golay):", np.isnan(ppg_filtered_sg).any())
    print("Check NaN values in the filtered PPG signal (without Savitzky-Golay):", np.isnan(ppg_filtered_no_sg).any())

    return check_quality(ppg_raw, ppg_filtered_sg, fs)
    

def check_ppg_windows(
    bl_data_path,
    first_samples_to_ignore=0,
    column_name="Header 25 Data",
    fs=PPG_SAMPLING_RATE,
    window_sec=8,
):
    bl_ppg_data = pd.read_csv(bl_data_path)
    print(f"Processing {bl_data_path} ...")
    column_name = resolve_column_name(bl_ppg_data, column_name)

    ppg_values = pd.to_numeric(bl_ppg_data[column_name], errors="coerce")
    ppg_values = truncate_at_first_nan(ppg_values).dropna()
    ppg_raw = convert_to_raw(ppg_values.to_numpy())

    first_samples_to_ignore = max(0, int(first_samples_to_ignore))
    ppg_raw = ppg_raw[first_samples_to_ignore:]

    if len(ppg_raw) < fs:
        raise ValueError(
            f"PPG signal is too short after ignoring {first_samples_to_ignore} samples: "
            f"{len(ppg_raw)} samples remain."
        )

    ppg_raw = fill_missing(ppg_raw)
    ppg_cleaned = preprocess_ppg(ppg_raw, fs, use_sg=True)
    return check_quality_windows(ppg_raw, ppg_cleaned, fs=fs, window_sec=window_sec)

def quality_status(value, threshold, op=">"):
    if np.isnan(value):
        return "Bad (NaN)"
    if op == ">":
        return "Good" if value > threshold else "Bad"
    if op == ">=":
        return "Good" if value >= threshold else "Bad"
    return "N/A"


def check_quality(ppg_raw, ppg_cleaned, fs=PPG_SAMPLING_RATE, baseline_sec=5):
    baseline = int(baseline_sec * fs)
    ppg_cleaned = fill_missing(ppg_cleaned)[baseline:]
    ppg_raw = fill_missing(ppg_raw)[baseline:]

    print("\n--- PPG Signal Quality Assessment ---")
    snr_raw = calculate_snr_bandpower(ppg_raw, fs=fs)
    print(f"SNR (bandpower, raw): {snr_raw:.2f} dB\tStatus: {colored_flag(quality_status(snr_raw, 5, '>'))}")
    snr_clean = calculate_snr_bandpower(ppg_cleaned, fs=fs)
    print(f"SNR (bandpower, cleaned): {snr_clean:.2f} dB\tStatus: {colored_flag(quality_status(snr_clean, 10, '>'))}")

    cardiac_power_raw = calculate_snr_bandpower(ppg_raw, fs=fs, signal_band=(0.8, 2), noise_band=((5, 50), (0.001, 0.5)))
    cardiac_power_clean = calculate_snr_bandpower(ppg_cleaned, fs=fs, signal_band=(0.8, 2), noise_band=((5, 50), (0.001, 0.5)))
    print(f"Cardiac Power (bandpower, raw): {cardiac_power_raw:.2f} dB\tStatus: {colored_flag(quality_status(cardiac_power_raw, 5, '>'))}")
    print(f"Cardiac Power (bandpower, cleaned): {cardiac_power_clean:.2f} dB\tStatus: {colored_flag(quality_status(cardiac_power_clean, 5, '>'))}")


    entropy_clean = calculate_entropy(ppg_cleaned)
    entropy_raw = calculate_entropy(ppg_raw)
    print(f"Entropy (PPG cleaned): {entropy_clean:.4f} bits\tStatus: {colored_flag(quality_status(entropy_clean, 3.0, '>'))}")
    print(f"Entropy (PPG raw): {entropy_raw:.4f} bits\tStatus: {colored_flag(quality_status(entropy_raw, 6.5, '>'))}")


    template_val = np.nan
    peaks, _ = find_peaks(
        ppg_cleaned,
        distance=int(fs * 0.4),
        prominence=np.std(ppg_cleaned) * 0.3,
    )

    if len(peaks) < 3:
        print("Template matching: Skipped (too few peaks)")
    elif nk is None:
        print("Template matching: Skipped (neurokit2 is not installed)")
    else:
        try:
            quality = nk.ppg_quality(ppg_cleaned, sampling_rate=fs, method="templatematch")
            template_val = np.nanmean(quality)
            print(
                f"Template matching: {template_val:.2f}\t"
                f"Status: {colored_flag(quality_status(template_val, 0.85, '>='))}"
            )
        except Exception as exc:
            print(f"Template matching: Failed ({exc})\tStatus: {colored_flag('Bad')}")

    try:
        skew_val = skew(ppg_cleaned, nan_policy="omit")
        print(f"Skewness: {skew_val:.2f}\tStatus: {colored_flag(quality_status(skew_val, -0.5, '>='))}")
    except Exception as exc:
        skew_val = np.nan
        print(f"Skewness: Failed ({exc})\tStatus: {colored_flag('Bad')}")

    try:
        kurt_val = kurtosis(ppg_cleaned, fisher=False, nan_policy="omit")
        print(f"Kurtosis: {kurt_val:.2f}\tStatus: {colored_flag(quality_status(kurt_val, 2.0, '>='))}")
    except Exception as exc:
        kurt_val = np.nan
        print(f"Kurtosis: Failed ({exc})\tStatus: {colored_flag('Bad')}")

    try:
        dc_component = np.nanmean(np.abs(ppg_raw))
        ac_component = np.nanmax(ppg_cleaned) - np.nanmin(ppg_cleaned)
        perfusion_index = 100 * ac_component / dc_component if dc_component > 0 else np.nan
        print(
            f"Perfusion index: {perfusion_index:.2f}\t"
            f"Status: {colored_flag(quality_status(perfusion_index, 0.5, '>='))}"
        )
    except Exception as exc:
        perfusion_index = np.nan
        print(f"Perfusion index: Failed ({exc})\tStatus: {colored_flag('Bad')}")


    loose_contact = (
    cardiac_power_raw < -5 or (cardiac_power_raw < 5 and template_val < 0.85)
    )
    loose_contact_status = "BAD" if loose_contact else "GOOD"

    print(
        "CONTACT CHECK (WEARING CONDITION): "
        f"{colored_status_text(loose_contact_status)} "
    )

    print("--- End of Assessment ---\n")

    return {
        "snr_bandpower": None if np.isnan(snr_clean) else float(snr_clean),
        "entropy_raw": None if np.isnan(entropy_raw) else float(entropy_raw),
        "entropy_cleaned": None if np.isnan(entropy_clean) else float(entropy_clean),
        "loose_contact": loose_contact_status,
        "template_matching": None if np.isnan(template_val) else float(template_val),
        "skewness": None if np.isnan(skew_val) else float(skew_val),
        "kurtosis": None if np.isnan(kurt_val) else float(kurt_val),
        "perfusion_index": None if np.isnan(perfusion_index) else float(perfusion_index),
    }


def check_quality_windows(ppg_raw, ppg_cleaned, fs=PPG_SAMPLING_RATE, window_sec=8):
    window_samples = int(window_sec * fs)
    if window_samples <= 0:
        raise ValueError("window_sec must be greater than 0.")

    min_length = min(len(ppg_raw), len(ppg_cleaned))
    results = []

    for start in range(0, min_length - window_samples + 1, window_samples):
        end = start + window_samples
        print(
            f"\n=== PPG {window_sec}s Window Quality: "
            f"{start / fs:.2f}-{end / fs:.2f}s ==="
        )

        plt.plot(ppg_raw[start:end], label="Raw", color="gray")
        plt.plot(ppg_cleaned[start:end], label="Cleaned", color="blue")
        plt.title(f"PPG Signal Window: {start / fs:.2f}-{end / fs:.2f}s")
        plt.xlabel("Sample Index")
        plt.ylabel("Amplitude")
        plt.legend()
        plt.grid(True)
        plt.tight_layout()
        plt.show()
        result = check_quality(
            ppg_raw[start:end],
            ppg_cleaned[start:end],
            fs=fs,
            baseline_sec=0,
        )
        # Plot PSD of this window
        # plot_psd(
        #     ppg_raw[start:end],
        #     fs=fs,
        #     title=f"PPG Signal Window: {start / fs:.2f}-{end / fs:.2f}s",
        #     data_path=None,
        #     suffix=None,
        # )

        result["window_start_s"] = start / fs
        result["window_end_s"] = end / fs
        results.append(result)

    print(f"\nTotal {window_sec}s non-overlap windows checked: {len(results)}")
    return results


if __name__ == "__main__":
    file_name = "data_normal/6B82.csv"
    # Check the whole recording
    check_ppg(file_name, first_samples_to_ignore=100, plot=True, show_plots=True)
    # Check windows (if necessary)
    check_ppg_windows(file_name, first_samples_to_ignore=100, window_sec=8)
