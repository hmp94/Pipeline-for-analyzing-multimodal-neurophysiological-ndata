import numpy as np
import pandas as pd
import pywt
import matplotlib.pyplot as plt
import os
from pyedflib import highlevel, FILETYPE_EDFPLUS
from scipy.signal import butter, lfilter, iirnotch, welch
from scipy.stats import pearsonr
import warnings
warnings.filterwarnings('ignore')
from scipy.stats import entropy, pearsonr
from scipy.signal import welch
import time



# =========================================================
# USER SETTINGS
# =========================================================
sampling_frequency = 244
wavelet_name = "db4"
decomp_level = 4


band_amplitude_metric = "mad"
TARGET_BAND_RULES = {
    # "D4": {"target_amp": 35.0, "max_amp": 120.0},
    "D3": {"target_amp": 25.0, "max_amp": 55.0},
    "D2": {"target_amp": 8.0,  "max_amp": 22.0},
    "D1": {"target_amp": 0.1,  "max_amp": 1.0}, 
}

# Scale limits:
min_scale = 0.25
max_scale = 1.00

use_post_clip = True
use_explicit_band_clip = True



def dc_blocking_filter(data, alpha=0.99):
    y = np.zeros_like(data, dtype=np.float32)
    y[0] = data[0]
    for i in range(1, len(data)):
        y[i] = data[i] - data[i-1] + alpha * y[i-1]
    return y

def butter_bandpass(lowcut, highcut, fs, order=4):
    nyq = 0.5 * fs
    b, a = butter(order, [lowcut/nyq, highcut/nyq], btype='band')
    return b, a

def bandpass_filter(data, lowcut, highcut, fs, order=4):
    b, a = butter_bandpass(lowcut, highcut, fs, order)
    return lfilter(b, a, data)


def notch_filter(data, notch_freq, fs, Q=30.0):
    w0 = notch_freq / (0.5 * fs)
    b, a = iirnotch(w0, Q)
    return lfilter(b, a, data)


def preprocess_eeg(data, fs=244):
    # Step 1: DC Blocking
    dc_removed = dc_blocking_filter(data)

    # Step 2: Notch Filtering
    notch_60 = notch_filter(dc_removed, 60, fs, Q=12)
    notch_50 = notch_filter(notch_60, 50, fs, Q=5)
    notch_32 = notch_filter(notch_50, 32, fs, Q=10)

    # Step 3: Bandpass Filtering (1–35 Hz)
    filtered = bandpass_filter(notch_32, 1, 35, fs)

    return filtered
    
def highpass_filter(data, highcut, fs, order=4):
    nyq = 0.5 * fs
    b, a = butter(order, highcut/nyq, btype='high')
    return lfilter(b, a, data)

# =========================================================
# Utilities
# =========================================================
def get_first_nan_trimmed_pair(ch1_series, ch2_series):
    """
    Trim two pandas Series at the first NaN found in either channel.
    """
    nan_idx_ch1 = ch1_series[ch1_series.isna()].index.min()
    nan_idx_ch2 = ch2_series[ch2_series.isna()].index.min()

    first_nan_idx = min(
        nan_idx_ch1 if pd.notna(nan_idx_ch1) else len(ch1_series),
        nan_idx_ch2 if pd.notna(nan_idx_ch2) else len(ch2_series)
    )

    ch1_trim = ch1_series.iloc[:first_nan_idx].to_numpy(dtype=np.float32)
    ch2_trim = ch2_series.iloc[:first_nan_idx].to_numpy(dtype=np.float32)
    return ch1_trim, ch2_trim


def coeff_frequency_bands(fs, level):
    """
    Approximate DWT frequency bands.

    Level 4 at fs=244 Hz:
      A4: 0 - 7.625 Hz
      D4: 7.625 - 15.25 Hz
      D3: 15.25 - 30.5 Hz
      D2: 30.5 - 61 Hz
      D1: 61 - 122 Hz
    """
    bands = {}
    bands[f"A{level}"] = (0.0, fs / (2 ** (level + 1)))

    for j in range(level, 0, -1):
        low = fs / (2 ** (j + 1))
        high = fs / (2 ** j)
        bands[f"D{j}"] = (low, high)

    return bands


def estimate_sigma(detail_coeffs):
    """
    Robust noise estimate from detail coefficients.
    """
    detail_coeffs = np.asarray(detail_coeffs)
    if len(detail_coeffs) == 0:
        return 0.0
    return np.median(np.abs(detail_coeffs)) / 0.6745


# =========================================================
# BASIC HELPERS
# =========================================================
def convert_to_uV(raw_signal):
    """ADC counts → µV at 0.095367 µV/count, in float.

    Kept in float for the same reason as the copy in csv_to_edf_denoised.py: the
    electrode DC offset puts every sample outside int16's ±32767, so casting here
    wraps modulo 65536 and injects ±65536 µV steps. Only used by
    processing_all_files() below, which nothing currently calls.
    """
    return np.asarray(1_000_000 * (raw_signal - 8388608) * 1.6 / 8388608 / 2,
                      dtype=np.float64)


def robust_band_amplitude(coeffs, metric="p95"):
    coeffs = np.asarray(coeffs, dtype=np.float32)

    if coeffs.size == 0:
        return 0.0

    if metric == "p95":
        return float(np.percentile(np.abs(coeffs), 95))
    elif metric == "mad":
        med = np.median(coeffs)
        return float(np.median(np.abs(coeffs - med)))
    elif metric == "rms":
        return float(np.sqrt(np.mean(coeffs ** 2)))
    else:
        raise ValueError(f"Unknown metric: {metric}")


def estimate_sigma(detail_coeffs):
    detail_coeffs = np.asarray(detail_coeffs, dtype=np.float32)
    if detail_coeffs.size == 0:
        return 0.0
    med = np.median(detail_coeffs)
    return float(np.median(np.abs(detail_coeffs - med)) / 0.6745)


def get_first_nan_trimmed_pair(ch1_series, ch2_series):
    nan_idx_ch1 = ch1_series[ch1_series.isna()].index.min()
    nan_idx_ch2 = ch2_series[ch2_series.isna()].index.min()

    first_nan_idx = min(
        nan_idx_ch1 if pd.notna(nan_idx_ch1) else len(ch1_series),
        nan_idx_ch2 if pd.notna(nan_idx_ch2) else len(ch2_series)
    )

    ch1_trim = ch1_series.iloc[:first_nan_idx].to_numpy(dtype=np.float32)
    ch2_trim = ch2_series.iloc[:first_nan_idx].to_numpy(dtype=np.float32)
    return ch1_trim, ch2_trim


# =========================================================
# WPT HELPERS
# =========================================================
def packet_band(fs, level, index):
    """
    Frequency band for a Wavelet Packet node in frequency order.

    bandwidth = (fs/2) / (2**level)
    """
    bw = (fs / 2.0) / (2 ** level)
    low = index * bw
    high = (index + 1) * bw
    return low, high


def get_wp_nodes_and_bands(signal, fs, wavelet="db4", level=4, mode="symmetric"):
    """
    Return WaveletPacket object, nodes in freq order, and their bands.
    """
    signal = np.asarray(signal, dtype=np.float32)
    wp = pywt.WaveletPacket(data=signal, wavelet=wavelet, mode=mode, maxlevel=level)
    nodes = wp.get_level(level, order="freq")

    bands = []
    for i, node in enumerate(nodes):
        low, high = packet_band(fs=fs, level=level, index=i)
        bands.append((node.path, i, low, high))

    return wp, nodes, bands


def get_wp_frequency_bands(fs, level):
    bands = []
    n_nodes = 2 ** level
    for i in range(n_nodes):
        low, high = packet_band(fs, level, i)
        bands.append((i, low, high))
    return bands


def overlaps_band(low1, high1, low2, high2):
    return max(low1, low2) < min(high1, high2)


def should_process_packet(low, high, target_bands):
    for b_low, b_high in target_bands:
        if overlaps_band(low, high, b_low, b_high):
            return True
    return False


# =========================================================
# WPT THRESHOLDING
# =========================================================
def wavelet_packet_threshold_bands(
    signal,
    fs,
    wavelet="db4",
    level=4,
    target_bands=((23.0, 27.0), (30.0, 37.0)),
    mode="symmetric",
    threshold_rule="adaptive",
    threshold_type="soft",
    threshold_scale=1.5,
    packet_thresholds=None,
    preserve_ratio=0.15,
    min_threshold=5.0,
    metric_for_logging="p95",
):
    """
    Threshold only WPT packets that overlap the selected target frequency bands.

    Parameters
    ----------
    signal : array-like
        Input EEG.
    fs : float
        Sampling frequency.
    wavelet : str
        Wavelet name.
    level : int
        WPT decomposition level.
    target_bands : tuple of (low, high)
        Frequency regions to suppress.
    mode : str
        Signal extension mode.
    threshold_rule : str
        "adaptive", "universal", or "fixed".
    threshold_type : str
        "soft", "hard", or "garrote".
    threshold_scale : float
        Multiplier applied to threshold estimate.
    packet_thresholds : dict or None
        Optional manual thresholds keyed by node index.
        Example: {6: 35.0, 8: 28.0, 9: 28.0}
    preserve_ratio : float
        Protect very small coefficients under preserve_ratio * T.
    min_threshold : float
        Lower bound on threshold.
    metric_for_logging : str
        Metric for reporting current packet amplitude.

    Returns
    -------
    reconstructed : np.ndarray
    wp_before : WaveletPacket
    wp_after : WaveletPacket
    packet_info : dict
    """
    signal = np.asarray(signal, dtype=np.float32)

    if signal.size < 16:
        wp = pywt.WaveletPacket(data=signal, wavelet=wavelet, mode=mode, maxlevel=level)
        return signal.copy(), wp, wp, {}

    if packet_thresholds is None:
        packet_thresholds = {}

    wp_before = pywt.WaveletPacket(data=signal, wavelet=wavelet, mode=mode, maxlevel=level)
    nodes_before = wp_before.get_level(level, order="freq")

    wp_after = pywt.WaveletPacket(data=None, wavelet=wavelet, mode=mode)
    packet_info = {}

    for i, node in enumerate(nodes_before):
        c = np.asarray(node.data, dtype=np.float32).copy()
        low, high = packet_band(fs, level, i)
        is_target = should_process_packet(low, high, target_bands)

        current_amp = robust_band_amplitude(c, metric=metric_for_logging)
        sigma = estimate_sigma(c)

        if is_target:
            n = max(len(c), 2)

            if i in packet_thresholds:
                T = float(packet_thresholds[i])
                threshold_source = "manual"
            else:
                if threshold_rule == "adaptive":
                    T = threshold_scale * sigma
                    threshold_source = "adaptive_sigma"
                elif threshold_rule == "universal":
                    T = threshold_scale * sigma * np.sqrt(2.0 * np.log(n))
                    threshold_source = "universal"
                elif threshold_rule == "fixed":
                    T = float(threshold_scale)
                    threshold_source = "fixed_scalar"
                else:
                    raise ValueError(f"Unknown threshold_rule: {threshold_rule}")

            T = max(float(T), float(min_threshold))
            T0 = preserve_ratio * T

            abs_c = np.abs(c)
            sign_c = np.sign(c)

            if threshold_type == "soft":
                c_new = sign_c * np.maximum(abs_c - T, 0.0)

            elif threshold_type == "hard":
                c_new = np.where(abs_c >= T, c, 0.0)

            elif threshold_type == "garrote":
                c_new = np.where(
                    abs_c > T,
                    c * (1.0 - (T ** 2 / np.maximum(abs_c ** 2, 1e-12))),
                    0.0
                )

            else:
                raise ValueError(f"Unknown threshold_type: {threshold_type}")

            if T0 > 0:
                preserve_mask = abs_c < T0
                c_new[preserve_mask] = c[preserve_mask]

            wp_after[node.path] = c_new.astype(np.float32)

            packet_info[i] = {
                "path": node.path,
                "band_hz": (low, high),
                "selected": True,
                "current_amp": float(current_amp),
                "sigma": float(sigma),
                "threshold": float(T),
                "threshold_rule": threshold_source,
                "threshold_type": threshold_type,
                "n_coeffs": int(len(c)),
            }
        else:
            wp_after[node.path] = c.astype(np.float32)

            packet_info[i] = {
                "path": node.path,
                "band_hz": (low, high),
                "selected": False,
                "current_amp": float(current_amp),
                "sigma": float(sigma),
                "threshold": None,
                "threshold_rule": None,
                "threshold_type": None,
                "n_coeffs": int(len(c)),
            }

    reconstructed = wp_after.reconstruct(update=False)
    reconstructed = np.asarray(reconstructed[:len(signal)], dtype=np.float32)

    return reconstructed, wp_before, wp_after, packet_info


# =========================================================
# VISUALIZATION
# =========================================================
def plot_signal_before_after(original, denoised, fs, channel_name="EEG"):
    t = np.arange(len(original)) / fs

    plt.figure(figsize=(14, 4))
    plt.plot(t, original, label="Before denoising", linewidth=1)
    plt.plot(t, denoised, label="After denoising", linewidth=1)
    plt.title(f"{channel_name}: Signal Before vs After WPT Packet Thresholding")
    plt.xlabel("Time (s)")
    plt.ylabel("Amplitude (uV)")
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.show()


def plot_wpt_packet_coeffs(wp_before, wp_after, fs, level, channel_name="EEG"):
    nodes_before = wp_before.get_level(level, order="freq")
    nodes_after = wp_after.get_level(level, order="freq")
    n = len(nodes_before)

    fig, axes = plt.subplots(n, 2, figsize=(15, 2.3 * n))
    fig.suptitle(
        f"{channel_name} WPT Coefficients (fs={fs} Hz, level={level})",
        fontsize=14
    )

    if n == 1:
        axes = np.array([axes])

    for i, (n_before, n_after) in enumerate(zip(nodes_before, nodes_after)):
        low, high = packet_band(fs, level, i)
        band_text = f"{low:.3f} - {high:.3f} Hz"

        axes[i, 0].plot(n_before.data, linewidth=0.8)
        axes[i, 0].set_title(f"Before - node {i} [{n_before.path}] ({band_text})")
        axes[i, 0].set_xlabel("Coefficient index")
        axes[i, 0].set_ylabel("Amplitude")
        axes[i, 0].grid(True, alpha=0.3)

        axes[i, 1].plot(n_after.data, linewidth=0.8)
        axes[i, 1].set_title(f"After - node {i} [{n_after.path}] ({band_text})")
        axes[i, 1].set_xlabel("Coefficient index")
        axes[i, 1].set_ylabel("Amplitude")
        axes[i, 1].grid(True, alpha=0.3)

    plt.tight_layout(rect=[0, 0, 1, 0.97])
    plt.show()

    print(f"\nWPT packet frequency bands for fs = {fs} Hz, level = {level}:")
    for i in range(n):
        low, high = packet_band(fs, level, i)
        print(f"  node {i}: {low:.3f} - {high:.3f} Hz")


def print_packet_info(packet_info):
    print("\nWPT packet thresholding info:")
    for idx, info in packet_info.items():
        low, high = info["band_hz"]
        print(
            f"  node {idx:02d} [{info['path']}]: "
            f"{low:.3f}-{high:.3f} Hz | "
            f"selected={info['selected']} | "
            f"amp={info['current_amp']:.3f} | "
            f"sigma={info['sigma']:.3f} | "
            f"threshold={info['threshold']}"
        )
# =========================================================
# MAIN PIPELINE
# =========================================================
def processing_all_files(folder_path, edf_folder_path, duration, sampling_rate=244, plot=False):
    for csv_file in os.listdir(folder_path):
        if not csv_file.endswith(".csv"):
            continue

        file_path = os.path.join(folder_path, csv_file)
        os.makedirs(edf_folder_path, exist_ok=True)
        edf_path = os.path.join(edf_folder_path, os.path.splitext(csv_file)[0] + ".edf")

        eeg_data_BL = pd.read_csv(file_path)
        eeg_data_BL.columns = eeg_data_BL.columns.str.strip()

        # =========================================================
        # Load channels
        # =========================================================
        AF3 = eeg_data_BL["Header 26 Data"].astype(np.float32)  # BL AF3 = AF3 - T7
        AF4 = eeg_data_BL["Header 24 Data"].astype(np.float32)  # BL AF4 = AF4 - T8

        if duration:
            duration_samples = int(duration * sampling_rate)
            AF3 = AF3[:duration_samples]
            AF4 = AF4[:duration_samples]

        AF3, AF4 = get_first_nan_trimmed_pair(AF3, AF4)

        # =========================================================
        # Convert to uV
        # =========================================================
        AF3_uV = convert_to_uV(AF3)
        AF4_uV = convert_to_uV(AF4)

        # Baseline correction
        AF3_uV = AF3_uV - AF3_uV[0]
        AF4_uV = AF4_uV - AF4_uV[0]

        # =========================================================
        # Preprocessing
        # =========================================================
        AF3_uV_processed = preprocess_eeg(AF3_uV, fs=sampling_rate)
        AF4_uV_processed = preprocess_eeg(AF4_uV, fs=sampling_rate)

        AF3_before_denoise = AF3_uV_processed.copy()
        AF4_before_denoise = AF4_uV_processed.copy()

        # =========================================================
        # WPT thresholding
        # =========================================================
        target_bands = (
            (23.0, 27.0),
            (29.0, 35.0),
            (30.0, 37.0),
            (60.0, 65.0),
        )

        # packet_thresholds = {
        #     6: 35.0,
        #     7: 30.0,
        #     8: 28.0,
        #     9: 28.0,
        #     16: 20.0,
        # }

        before_time = time.time()
        AF3_uV_denoised, AF3_wp_before, AF3_wp_after, AF3_packet_info = wavelet_packet_threshold_bands(
            AF3_before_denoise,
            fs=sampling_rate,
            wavelet=wavelet_name,
            level=3,
            target_bands=target_bands,
            mode="symmetric",
            threshold_rule="adaptive",   # "adaptive", "universal", or "fixed"
            threshold_type="garrote",       # "soft", "hard", or "garrote"
            threshold_scale=10.0,
            packet_thresholds=None,     
            preserve_ratio=0.05,
            min_threshold=1.0,
            metric_for_logging=band_amplitude_metric,
        )

        after_time = time.time()
        print(f"AF3 time: {after_time - before_time}")
        AF4_uV_denoised, AF4_wp_before, AF4_wp_after, AF4_packet_info = wavelet_packet_threshold_bands(
            AF4_before_denoise,
            fs=sampling_rate,
            wavelet=wavelet_name,
            level=3,
            target_bands=target_bands,
            mode="symmetric",
            threshold_rule="adaptive",
            threshold_type="garrote",
            threshold_scale=10.0,
            packet_thresholds=None,
            preserve_ratio=0.05,
            min_threshold=1.0,
            metric_for_logging=band_amplitude_metric,
        )
        print(f"AF4 time: {time.time() - after_time}\n")

        # =========================================================
        # Plot
        # =========================================================
        if plot:
            plot_signal_before_after(AF3_before_denoise, AF3_uV_denoised, sampling_rate, channel_name="AF3")
            plot_signal_before_after(AF4_before_denoise, AF4_uV_denoised, sampling_rate, channel_name="AF4")

            plot_wpt_packet_coeffs(AF3_wp_before, AF3_wp_after, sampling_rate, level=3, channel_name="AF3")
            plot_wpt_packet_coeffs(AF4_wp_before, AF4_wp_after, sampling_rate, level=3, channel_name="AF4")

        print("\nAF3 packet thresholding info:")
        print_packet_info(AF3_packet_info)

        print("\nAF4 packet thresholding info:")
        print_packet_info(AF4_packet_info)


        AF3_delta = highpass_filter(AF3_uV_processed, highcut=4.0, fs=sampling_rate, order=4)
        AF4_delta = highpass_filter(AF4_uV_processed, highcut=4.0, fs=sampling_rate, order=4)

        # =========================================================
        # Align lengths
        # =========================================================
        min_length = min(map(len, [
            AF3_uV, AF4_uV,
            AF3_uV_processed, AF4_uV_processed,
            AF3_uV_denoised, AF4_uV_denoised,
            # AF3_o, AF4_o,
            AF3_delta, AF4_delta
        ]))

        AF3_uV = AF3_uV[:min_length]
        AF4_uV = AF4_uV[:min_length]
        AF3_uV_processed = AF3_uV_processed[:min_length]
        AF4_uV_processed = AF4_uV_processed[:min_length]
        AF3_uV_denoised = AF3_uV_denoised[:min_length]
        AF4_uV_denoised = AF4_uV_denoised[:min_length]
        # AF3_o = AF3_o[:min_length]
        # AF4_o = AF4_o[:min_length]
        AF3_delta = AF3_delta[:min_length]
        AF4_delta = AF4_delta[:min_length]

        # =========================================================
        # Save EDF
        # =========================================================
        signals = np.vstack([
            AF3_uV, AF4_uV,
            AF3_uV_processed, AF4_uV_processed,
            AF3_uV_denoised, AF4_uV_denoised,
            # AF3_o, AF4_o,
            AF3_delta, AF4_delta
        ])

        signal_headers = []
        for label, signal in zip(
            [
                "AF3", "AF4",
                "AF3_processed", "AF4_processed",
                "AF3_wpt_thresholded", "AF4_wpt_thresholded",
                # "AF3_o", "AF4_o",
                "AF3_delta", "AF4_delta"
            ],
            signals
        ):
            signal_headers.append({
                "label": label,
                "dimension": "uV",
                "sample_frequency": sampling_rate,
                "physical_min": float(signal.min()),
                "physical_max": float(signal.max()),
                "digital_min": -32768,
                "digital_max": 32767,
                "transducer": "",
                "prefilter": ""
            })

        highlevel.write_edf(
            edf_path,
            signals,
            signal_headers,
            file_type=FILETYPE_EDFPLUS
        )

        print(f"Converted: {csv_file} -> {edf_path}")
        print("**********************************************************")
        print()

if __name__ == "__main__":
    folder_path = "./wavelet_data/bad_files"
    edf_folder_path = "./wavelet_data/bad_files_wpt_thresh_edf"
    processing_all_files(folder_path, edf_folder_path, duration = 360, sampling_rate = 244, plot = True)