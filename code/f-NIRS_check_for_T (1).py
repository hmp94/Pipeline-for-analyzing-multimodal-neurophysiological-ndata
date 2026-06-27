import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy.stats import pearsonr
from scipy.signal import butter, lfilter, find_peaks
from scipy import signal
from intensity_filter import dwt_denoise_filter, hampel_filter
import warnings
warnings.filterwarnings("ignore")


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



def bandpass_filter(data, lowcut, highcut, fs, order=2):
    """Apply a Butterworth bandpass filter to the data."""
    nyq = 0.5 * fs
    b, a = butter(order, [lowcut / nyq, highcut / nyq], btype='band')
    return lfilter(b, a, data)


def _bandpower_from_psd(f, Pxx, band):
    """Compute band power by integrating PSD over the given frequency band.

    band: tuple (low, high) where high may be None to indicate up to Nyquist.
    """
    f = np.asarray(f)
    Pxx = np.asarray(Pxx)
    low, high = band
    if high is None:
        mask = f >= low
    else:
        mask = (f >= low) & (f <= high)
    if not np.any(mask):
        return 0.0
    return float(np.trapz(Pxx[mask], f[mask]))


def compute_snr(x, fs, signal_band=(0.01, 0.5), noise_band=(0.5, None), nperseg=1024):
    """Compute SNR as bandpower(signal_band) / bandpower(noise_band).

    - x: 1D array-like signal
    - fs: sampling frequency
    - signal_band: (low, high) for the signal band (Hz)
    - noise_band: (low, high) for the noise band; pass high=None to integrate to Nyquist
    Returns: float (np.nan if noise power is zero)
    """
    x = np.asarray(x, dtype=float)
    if x.size == 0:
        return np.nan
    nperseg = min(nperseg, x.size)
    f, Pxx = signal.welch(x, fs, nperseg=nperseg)

    p_signal = _bandpower_from_psd(f, Pxx, signal_band)
    p_noise = _bandpower_from_psd(f, Pxx, noise_band)

    if p_noise <= 0:
        return np.nan
    return float(p_signal / p_noise)

def convert_to_raw(signal_integer):
    # Convert to int
    signal_integer = np.array(signal_integer, dtype=np.int32)
    raw_20bit = signal_integer & 0xFFFFF
    # Step 2: two's complement
    signed_value = np.where(raw_20bit >= (1 << 19), raw_20bit - (1 << 20), raw_20bit)
    # Trimming to the first NaN or first zero
    signed_value = np.trim_zeros(signed_value, 'b')
    return signed_value

def truncate_nan(signal):
    """
    Truncate the signal at the first occurrence of NaN value."""
    if isinstance(signal, np.ndarray):
        nan_indices = np.where(np.isnan(signal))[0]
        if len(nan_indices) > 0:
            nan_idx = nan_indices[0]
            return signal[:nan_idx]
        else:
            return signal
    else:
        # Assuming pandas Series
        nan_idx = signal[signal.isna()].index.min()
        return signal[:nan_idx] if pd.notna(nan_idx) else signal


def calculate_heartrate(ppg_signal, fs):
    peaks, _ = find_peaks(ppg_signal, distance=fs*0.5)  

    peak_intervals = np.diff(peaks) / fs
    heart_rates = 60 / peak_intervals  # 60 seconds / interval in seconds

    # Average heart rate
    avg_hr = np.mean(heart_rates)

    return avg_hr, peaks, heart_rates


def visualize_heart_rate(fNIRS1, fNIRS2, fs):
    hr_signal_fnirs1 = bandpass_filter(fNIRS1, 0.8, 2.0, fs)
    hr_signal_fnirs2 = bandpass_filter(fNIRS2, 0.8, 2.0, fs)

    hr_component_1, peaks_1, hr_values_1 = calculate_heartrate(hr_signal_fnirs1, fs)
    hr_component_2, peaks_2, hr_values_2 = calculate_heartrate(hr_signal_fnirs2, fs)

    print(f"Estimated Heart Rate from fNIRS1: {hr_component_1:.6f} bpm")
    print(f"Estimated Heart Rate from fNIRS2: {hr_component_2:.6f} bpm")
    print(f"Statistical comparison of heart rates: {'Good' if abs(hr_component_1 - hr_component_2) < 5 else 'Bad'} (threshold 5 bpm)")

    # Plot the filtered fNIRS signals used for SCI calculation
    plt.figure(figsize=(12, 6))
    plt.subplot(2, 1, 1)
    plt.plot(hr_signal_fnirs1, label='fNIRS1')
    plt.plot(peaks_1, hr_signal_fnirs1[peaks_1], 'ro', label='fNIRS1 Peaks')
    plt.title('Filtered fNIRS Signals for SCI Calculation (0.8-2.0Hz)')
    plt.xlabel('Sample Index')
    plt.ylabel('Amplitude (mV)')
    plt.legend()
    plt.grid()

    plt.subplot(2, 1, 2)
    plt.plot(hr_signal_fnirs2, label='fNIRS2')
    # Plot peaks
    plt.plot(peaks_2, hr_signal_fnirs2[peaks_2], 'go', label='fNIRS2 Peaks')
    plt.xlabel('Sample Index')
    plt.ylabel('Amplitude (mV)')
    plt.title('Filtered fNIRS Signals for SCI Calculation (0.8-2.0Hz)')
    plt.legend()
    plt.grid()
    plt.show()


def _safe_slice(x, signal_range):
    if signal_range is None:
        return x
    a, b = signal_range
    a = max(0, int(a))
    b = int(b)
    return x[a:min(b, len(x))]


def _compute_delta_od(I, fs, baseline_skip_s=1.0, baseline_len_s=8.0, eps=1e-12):
    """
    ΔOD(t) = -ln(I(t)/I0), with I0 = median over a baseline window (skip first baseline_skip_s seconds).
    Returns (dOD, baseline_idx_slice).
    """
    I = np.asarray(I, dtype=np.float64)
    I = np.clip(I, eps, None)

    skip = int(round(fs * baseline_skip_s))
    base = int(round(fs * baseline_len_s))
    if skip + base > len(I):
        raise ValueError(
            f"Baseline window too long for signal length. "
            f"Need at least {skip+base} samples, got {len(I)}."
        )

    base_slice = slice(skip, skip + base)
    I0 = np.mean(I[base_slice])

    dOD = -np.log(I / I0)

    # Center baseline to 0 (helps plotting and numerical stability; does not change Hb shapes)
    dOD -= np.mean(dOD[base_slice])

    return dOD, base_slice


def _compute_mbll_hb(dOD, ext_coef, distance_cm=3.5, dpf=(6.0, 6.0), scale_uM=1e3):
    """
    dOD: (2, N) where rows are wavelengths (RED, IR).
    ext_coef: (2, 2) where rows are wavelengths, columns are chromophores [HbO, HbR].
    """
    ext_coef = np.asarray(ext_coef, dtype=float)
    dOD = np.asarray(dOD, dtype=float)

    dpf = np.asarray(dpf, dtype=float)  # per wavelength
    L = distance_cm * dpf               # effective pathlength per wavelength (cm)

    # EL: (2 wavelengths x 2 chromophores)
    EL = ext_coef * L[:, None]
    iEL = np.linalg.pinv(EL)

    Hb = iEL @ dOD
    Hb *= scale_uM
    HbO, HbR = Hb[0], Hb[1]
    return HbO, HbR


def check_fNIRS_SCI(
    BL_csv_path,
    signal_range=None,
    plot=True,
    fs=100,
    col_red=" Header 27 Data",
    col_ir=" Header 28 Data",
    # Baseline for ΔOD
    baseline_skip_s=0.0,
    baseline_len_s=8.0,
    # SCI settings
    sci_band=(0.8, 2.0),
    sci_use_log_intensity=False,
    # Hemodynamic filtering
    hemo_band=(0.01, 0.8),
    # MBLL parameters (MUST match your LED wavelengths!)
    ext_coef=np.array([[446, 1115.88],
                       [1022, 692.36]], dtype=float),  # rows: [RED, IR], cols: [HbO, HbR]
    distance_cm=3.5,
    dpf=(6.0, 6.0),
    num_segments=3,
    use_hampel=True,
    hampel_window_sec=0.25,
    hampel_window_size=None,
    hampel_n_sigmas=6.0,
    use_dwt=True,
    dwt_wavelet="db4",
    dwt_level=None,
    dwt_threshold_scale=1.0,
    dwt_threshold_mode="soft",
    dwt_extension_mode="symmetric",
):
    """
    Quality check + OD + HbO/HbR computation for 2-wavelength wearable fNIRS.

    """
    df = pd.read_csv(BL_csv_path)
    df.columns = df.columns.str.strip()
    col_red = col_red.strip()
    col_ir  = col_ir.strip()
    print(f"Processing file: {BL_csv_path}")

    # ---- Load & clean ----
    if col_red not in df.columns or col_ir not in df.columns:
        raise KeyError(f"Missing columns. Found: {list(df.columns)[:10]}... Need '{col_red}' and '{col_ir}'.")

    fNIRS1 = df[col_red].to_numpy()
    fNIRS2 = df[col_ir].to_numpy()

    fNIRS1 = convert_to_raw(fNIRS1)
    fNIRS2 = convert_to_raw(fNIRS2)


    fNIRS1 = truncate_nan(fNIRS1).astype(np.float64)
    fNIRS2 = truncate_nan(fNIRS2).astype(np.float64)

    fNIRS1 = _safe_slice(fNIRS1, signal_range)
    fNIRS2 = _safe_slice(fNIRS2, signal_range)

    n = min(len(fNIRS1), len(fNIRS2))
    fNIRS1 = fNIRS1[:n]
    fNIRS2 = fNIRS2[:n]
    fNIRS1_raw = fNIRS1.copy()
    fNIRS2_raw = fNIRS2.copy()

    if use_hampel:
        fNIRS1 = hampel_filter(
            fNIRS1,
            fs=fs,
            window_sec=hampel_window_sec,
            window_size=hampel_window_size,
            n_sigmas=hampel_n_sigmas,
        )
        fNIRS2 = hampel_filter(
            fNIRS2,
            fs=fs,
            window_sec=hampel_window_sec,
            window_size=hampel_window_size,
            n_sigmas=hampel_n_sigmas,
        )
    if use_dwt:
        fNIRS1 = dwt_denoise_filter(
            fNIRS1,
            fs=fs,
            wavelet=dwt_wavelet,
            level=dwt_level,
            threshold_scale=dwt_threshold_scale,
            threshold_mode=dwt_threshold_mode,
            extension_mode=dwt_extension_mode,
        )
        fNIRS2 = dwt_denoise_filter(
            fNIRS2,
            fs=fs,
            wavelet=dwt_wavelet,
            level=dwt_level,
            threshold_scale=dwt_threshold_scale,
            threshold_mode=dwt_threshold_mode,
            extension_mode=dwt_extension_mode,
        )

    intensity_label_parts = []
    if use_hampel:
        intensity_label_parts.append("Hampel")
    if use_dwt:
        intensity_label_parts.append("DWT")
    denoise_label = "+".join(intensity_label_parts)
    intensity_label = f"{denoise_label}-denoised raw intensity" if denoise_label else "raw intensity"

    # Ensure strictly positive for log/OD (clip, don’t shift)
    eps = 1e-12
    I1_raw = np.clip(fNIRS1_raw, eps, None)
    I2_raw = np.clip(fNIRS2_raw, eps, None)
    I1 = np.clip(fNIRS1, eps, None)
    I2 = np.clip(fNIRS2, eps, None)

    # ---- PSD (selected raw intensity) ----
    if plot:
        f, Pxx_den_I1 = signal.welch(I1, fs, nperseg=1024)
        f, Pxx_den_I2 = signal.welch(I2, fs, nperseg=1024)
        # Convert to dB
        Pxx_dB_I1 = 10 * np.log10(Pxx_den_I1)
        Pxx_dB_I2 = 10 * np.log10(Pxx_den_I2)
        plt.plot(f, Pxx_dB_I1, label='RED', color='blue')
        plt.plot(f, Pxx_dB_I2, label='IR', color='green')
        plt.title(f'Power Spectral Density ({intensity_label})')
        plt.xlabel('Frequency (Hz)')
        plt.ylabel('Power/Frequency (dB/Hz)')
        plt.grid(True)
        plt.legend()
        plt.show()

    # Calculate SNR
    snr_red = compute_snr(I1, fs, signal_band=hemo_band, noise_band=(hemo_band[1], None))
    snr_ir = compute_snr(I2, fs, signal_band=hemo_band, noise_band=(hemo_band[1], None))
    snr_cardiac_red = compute_snr(I1, fs, signal_band=sci_band, noise_band=(sci_band[1], None))
    snr_cardiac_ir = compute_snr(I2, fs, signal_band=sci_band, noise_band=(sci_band[1], None))

    print(f"01/ SNR calculation ({intensity_label}) - Interested band (0.01-0.5 Hz) :")
    print(f"Hemodynamic range check: SNR RED={snr_red:.4f}, IR={snr_ir:.4f}, status: {colored_flag('GOOD') if (snr_red > 1.0 and snr_ir > 1.0) else colored_flag('BAD')} (threshold SNR > 1.0)")
    print(f"Cardiac range check: SNR RED={snr_cardiac_red:.4f}, IR={snr_cardiac_ir:.4f}, status: {colored_flag('GOOD') if (snr_cardiac_red > 1.0 and snr_cardiac_ir > 1.0) else colored_flag('BAD')} (threshold SNR > 1.0)")
    print()

    # ---- 01) Coefficient of Variation (CV) on intensity ----
    cv_1 = np.std(I1) / (np.mean(I1) + 1e-10)
    cv_2 = np.std(I2) / (np.mean(I2) + 1e-10)
    cv_good = (abs(cv_1) < 0.1) and (abs(cv_2) < 0.1)

    print(f"02/ Coefficient of Variation ({intensity_label})")
    print(f"CV RED={cv_1:.4f}, IR={cv_2:.4f}  --> {colored_flag('GOOD') if cv_good else colored_flag('BAD')} (threshold 0.1)")
    print()

    # ---- 02) Scalp Coupling Index (SCI) ----
    if sci_use_log_intensity:
        s1 = -np.log(I1)  # log-intensity (not baseline-referenced)
        s2 = -np.log(I2)
    else:
        s1 = I1
        s2 = I2

    s1_bp = bandpass_filter(s1, sci_band[0], sci_band[1], fs)
    s2_bp = bandpass_filter(s2, sci_band[0], sci_band[1], fs)
    
    baseline_skip_s = 5.0 
    corr_coef, p_value = pearsonr(s1_bp[int(baseline_skip_s * fs):], s2_bp[int(baseline_skip_s * fs):])
    sci_good = corr_coef > 0.75
    print("03/ Scalp Coupling Index (SCI)")
    print(f"SCI r={corr_coef:.4f} (p={p_value:.2e}) --> {colored_flag('GOOD') if sci_good else colored_flag('BAD')} (threshold 0.75)")
    print()

    if plot:
        t = np.arange(n) / fs
        # Plot a short window to see heartbeat-band similarity
        w0 = int(fs * max(baseline_skip_s, 0))
        w1 = min(n, w0 + int(fs * 20))
        plt.figure(figsize=(12, 4))
        plt.plot(t[w0:w1], s1_bp[w0:w1], label="RED (filtered)", color="blue")
        plt.plot(t[w0:w1], s2_bp[w0:w1], label="IR (filtered)", color="green")
        plt.title(f"SCI components ({sci_band[0]}–{sci_band[1]} Hz) | r={corr_coef:.3f}")
        plt.xlabel("Time (s)")
        plt.ylabel("Amplitude (a.u.)")
        plt.grid(True)
        plt.legend()
        plt.show()

    # ---- 03) ΔOD computation (consistent) ----
    dOD1, base_slice = _compute_delta_od(I1, fs, baseline_skip_s, baseline_len_s, eps=eps)
    dOD2, _ = _compute_delta_od(I2, fs, baseline_skip_s, baseline_len_s, eps=eps)
    dOD = np.vstack([dOD1, dOD2])

    # Check Std of OD baseline (should be low, otherwise unstable)
    std_OD1 = np.std(dOD1[int(baseline_skip_s * fs):])
    std_OD2 = np.std(dOD2[int(baseline_skip_s * fs):])
    print(f"04/ ΔOD baseline stability (std after initial skip) - RED={std_OD1:.6f}, IR={std_OD2:.6f} --> {colored_flag('GOOD') if (std_OD1 < 0.05 and std_OD2 < 0.05) else colored_flag('BAD')} (threshold std < 0.05)")

    visualize_heart_rate(dOD[0], dOD[1], fs)

    # Hemodynamic bandpass on ΔOD
    dOD_f = np.vstack([
        bandpass_filter(dOD[0], hemo_band[0], hemo_band[1], fs),
        bandpass_filter(dOD[1], hemo_band[0], hemo_band[1], fs),
    ])

    # ---- 04) MBLL to HbO/HbR ----
    HbO, HbR = _compute_mbll_hb(
        dOD_f,
        ext_coef=ext_coef,
        distance_cm=distance_cm,
        dpf=dpf,
        scale_uM=1,  
    )
    # # Plot HbO/HbR PSD
    # if plot:
    #     f, Pxx_den_I1 = signal.welch(HbO, fs, nperseg=1024)
    #     f, Pxx_den_I2 = signal.welch(HbR, fs, nperseg=1024)
    #     # Convert to dB
    #     Pxx_dB_I1 = 10 * np.log10(Pxx_den_I1)
    #     Pxx_dB_I2 = 10 * np.log10(Pxx_den_I2)
    #     plt.plot(f, Pxx_dB_I1, label='HbO', color='blue')
    #     plt.plot(f, Pxx_dB_I2, label='HbR', color='green')
    #     plt.title(f'Power Spectral Density ({intensity_label})')
    #     plt.xlabel('Frequency (Hz)')
    #     plt.ylabel('Power/Frequency (dB/Hz)')
    #     plt.grid(True)
    #     plt.legend()
    #     plt.show()
        

    hb_corr = pearsonr(HbO, HbR)[0]
    print("05/ MBLL HbO/HbR")
    print(f"HbO–HbR correlation r={hb_corr:.4f} --> STATUS: {colored_flag('GOOD') if hb_corr < 0.5 else colored_flag('BAD')} (threshold 0.5)")


    # ---- Plot: raw intensity, ΔOD, Hb ----
    if plot:
        t = np.arange(n) / fs
        boundaries = np.linspace(0, n, num_segments + 1, dtype=int)
        segments = [(boundaries[i], boundaries[i + 1]) for i in range(num_segments)]

        for (start, end) in segments:
            seg_t = t[start:end]
            seg_hb_corr = pearsonr(HbO[start:end], HbR[start:end])[0]

            plt.figure(figsize=(18, 14))

            # Raw intensity
            plt.subplot(3, 2, 1)
            if use_hampel or use_dwt:
                plt.plot(seg_t, I1_raw[start:end], label="RED raw", color="blue", alpha=0.45)
                plt.plot(seg_t, I2_raw[start:end], label="IR raw", color="green", alpha=0.45)
                plt.plot(seg_t, I1[start:end], label=f"RED {denoise_label}", color="blue")
                plt.plot(seg_t, I2[start:end], label=f"IR {denoise_label}", color="green")
                plt.title(f"Raw intensity with {denoise_label} denoise")
            else:
                plt.plot(seg_t, I1[start:end], label="RED raw", color="blue")
                plt.plot(seg_t, I2[start:end], label="IR raw", color="green")
                plt.title("Raw intensity")
            plt.xlabel("Time (s)")
            plt.ylabel("ADC")
            plt.grid(True)
            plt.legend()

            plt.subplot(3, 2, 2)
            if use_hampel or use_dwt:
                plt.plot(range(start, end), I1_raw[start:end], label="RED raw", color="blue", alpha=0.45)
                plt.plot(range(start, end), I2_raw[start:end], label="IR raw", color="green", alpha=0.45)
                plt.plot(range(start, end), I1[start:end], label=f"RED {denoise_label}", color="blue")
                plt.plot(range(start, end), I2[start:end], label=f"IR {denoise_label}", color="green")
                plt.title(f"Raw intensity with {denoise_label} denoise (sample index)")
            else:
                plt.plot(range(start, end), I1[start:end], label="RED raw", color="blue")
                plt.plot(range(start, end), I2[start:end], label="IR raw", color="green")
                plt.title("Raw intensity (sample index)")
            plt.xlabel("Sample")
            plt.ylabel("ADC")
            plt.grid(True)
            plt.legend()


            # ΔOD (unfiltered for visibility)
            plt.subplot(3, 2, 3)
            plt.plot(seg_t, dOD[0, start:end], label="ΔOD RED", color="blue")
            plt.plot(seg_t, dOD[1, start:end], label="ΔOD IR", color="green")
            plt.title("ΔOD (baseline-referenced)")
            plt.xlabel("Time (s)")
            plt.ylabel("ΔOD (a.u.)")
            plt.grid(True)
            plt.legend()

            plt.subplot(3, 2, 4)
            plt.plot(seg_t, dOD_f[0, start:end], label="ΔOD RED (hemo bp)", color="blue")
            plt.plot(seg_t, dOD_f[1, start:end], label="ΔOD IR (hemo bp)", color="green")
            plt.title(f"ΔOD filtered ({hemo_band[0]}–{hemo_band[1]} Hz)")
            plt.xlabel("Time (s)")
            plt.ylabel("ΔOD (a.u.)")
            plt.grid(True)
            plt.legend()

            # HbO/HbR
            plt.subplot(3, 2, 5)
            plt.plot(seg_t, HbO[start:end], label="HbO", color="blue")
            plt.plot(seg_t, HbR[start:end], label="HbR", color="green")
            plt.title(f"HbO/HbR (r={seg_hb_corr:.3f})")
            plt.xlabel("Time (s)")
            plt.ylabel("µM")
            plt.grid(True)
            plt.legend()

            plt.subplot(3, 2, 6)
            plt.plot(seg_t, HbO[start:end] + HbR[start:end], label="HbT (HbO+HbR)")
            plt.title("HbT")
            plt.xlabel("Time (s)")
            plt.ylabel("µM")
            plt.grid(True)
            plt.legend()

            plt.tight_layout()
            plt.show()

    return {
        "fs": fs,
        "use_hampel": use_hampel,
        "hampel_window_sec": hampel_window_sec,
        "hampel_window_size": hampel_window_size,
        "hampel_n_sigmas": hampel_n_sigmas,
        "use_dwt": use_dwt,
        "dwt_wavelet": dwt_wavelet,
        "dwt_level": dwt_level,
        "dwt_threshold_scale": dwt_threshold_scale,
        "dwt_threshold_mode": dwt_threshold_mode,
        "dwt_extension_mode": dwt_extension_mode,
        "intensity_red_raw": I1_raw,
        "intensity_ir_raw": I2_raw,
        "intensity_red": I1,
        "intensity_ir": I2,
        "cv_red": float(cv_1),
        "cv_ir": float(cv_2),
        "sci_r": float(corr_coef),
        "sci_p": float(p_value),
        "dOD_red": dOD[0],
        "dOD_ir": dOD[1],
        "HbO": HbO,
        "HbR": HbR,
        "Hb_corr": float(hb_corr),
        "baseline_slice": (base_slice.start, base_slice.stop),
        "snr_red": (None if np.isnan(snr_red) else float(snr_red)),
        "snr_ir": (None if np.isnan(snr_ir) else float(snr_ir)),
    }



def compute_psp(x760, x850, fs, win_sec=10, l_freq=0.7, h_freq=1.5):
    """
    x760, x850: 1D arrays for one SD-pair, two wavelengths (preferably in optical density)
    returns: psp_per_window (1D), times (list of (t_start, t_end))
    """
    x = np.vstack([x760, x850])

    # 1) band-pass around cardiac band
    xf = filter_data(x, sfreq=fs, l_freq=l_freq, h_freq=h_freq, verbose=False)

    Nw = int(np.ceil(win_sec * fs))
    n_windows = int(np.floor(xf.shape[1] / Nw))

    psp = np.zeros(n_windows)
    times = []

    for w in range(n_windows):
        s = w * Nw
        e = s + Nw
        c1 = xf[0, s:e]
        c2 = xf[1, s:e]

        # 2) normalize by std (avoid divide-by-zero)
        c1 = c1 / (np.std(c1) or 1.0)
        c2 = c2 / (np.std(c2) or 1.0)

        # 3) full cross-correlation, normalized
        c = np.correlate(c1, c2, mode="full") / Nw

        # 4) periodogram of correlation
        f, pxx = periodogram(c, fs=fs, window="hamming")

        # 5) PSP = max spectral power
        psp[w] = np.max(pxx)

        times.append((s / fs, e / fs))

    return psp, times


if __name__ == "__main__":
    file_path = "/Users/minhphan/Documents/Brain-Life/data/raw/csv/Moon_26_09_39_F0-F1-F9-F3-F5-F7-F11-F2-F8-F4-F6-F10-F12.csv"    
    check_fNIRS_SCI(
        file_path,
        signal_range=None, 
        plot=True,
        use_hampel=False,
        hampel_window_sec=1.0,
        hampel_n_sigmas=6.0,
        use_dwt=False,
        dwt_wavelet="db4",
        dwt_threshold_scale=1.0,
    )
