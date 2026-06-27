
import os
import numpy as np
import pandas as pd
from pyedflib import highlevel, FILETYPE_EDFPLUS
from scipy.signal import butter, lfilter, iirnotch, welch
from scipy.stats import pearsonr
import warnings
warnings.filterwarnings('ignore')
from scipy.stats import entropy
from scipy.signal import welch

# Import WPT denoising
from WPT_denoising_threshold import wavelet_packet_threshold_bands

#++++++++++++++++++++++++++ THIS SCRIPT IS USED TO CONVERT .CSV DATA TO .EDF FORMAT FOR EDFBROWSER++++++++++++++

# To run this script, you need to have the following libraries installed:
# install python compiler in your laptop first.
# install packages: pip install pyedflib pandas scipy numpy

RED = '\033[91m'
GREEN = '\033[92m'
YELLOW = '\033[93m'
RESET = '\033[0m'

def colored_flag(is_good):
    return f"{GREEN}GOOD{RESET}" if is_good else f"{RED}BAD{RESET}"

def colored_status_text(status):
    if status == "GOOD":
        return f"{GREEN}{status}{RESET}"
    if status == "BAD":
        return f"{RED}{status}{RESET}"
    return status



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

def preprocess_eeg(data, fs=244, dc = True):
    # Step 1: DC Blocking
    if dc:
        dc_removed = dc_blocking_filter(data)
    else:
        dc_removed = data

    # Step 2: Notch Filtering
    notch_60 = notch_filter(dc_removed, 60, fs, Q=12)
    notch_50 = notch_filter(notch_60, 50, fs, Q=5)
    notch_32 = notch_filter(notch_50, 32, fs, Q=10)

    # Step 3: Bandpass Filtering (1–35 Hz)
    filtered = bandpass_filter(notch_32, 1, 35, fs)
    

    return filtered

def get_numeric_column(column):
    numeric_col = pd.to_numeric(column, errors='coerce')
    filled_col = numeric_col.ffill()
    return filled_col.astype(np.float32)


def highpass_filter(data, cutoff, fs, order=4):
    nyq = 0.5 * fs
    normal_cutoff = cutoff / nyq
    b, a = butter(order, normal_cutoff, btype='high', analog=False)
    y = lfilter(b, a, data)
    return y


def calculate_entropy(signal):
    histogram, bin_edges = np.histogram(signal, bins=256, density=True)
    histogram = histogram + 1e-12  # Avoid log(0)
    ent = entropy(histogram, base=2)
    return ent

def check_zero_signal(AF3_signal, AF4_signal, fs=244, zero_duration=3, threshold=1e-2):
 
    zero_samples = int(zero_duration * fs)
    
    def find_zero_sequences(signal, zero_samples, threshold):
        abs_signal = np.abs(signal)
        is_near_zero = abs_signal <= threshold
        if not np.any(is_near_zero):
            return False, np.array([], dtype=int)
        idx = np.where(is_near_zero)[0]
        # split into consecutive runs
        runs = np.split(idx, np.where(np.diff(idx) != 1)[0] + 1)
        long_runs = [r for r in runs if len(r) >= zero_samples]
        if not long_runs:
            return False, np.array([], dtype=int)
        indices = np.concatenate(long_runs)
        return True, indices
    
    af3_has_zero, af3_indices = find_zero_sequences(AF3_signal, zero_samples, threshold)
    if af3_has_zero:
        return True, "ZERO_SIGNAL_DETECTED_AF3", af3_indices
    
    af4_has_zero, af4_indices = find_zero_sequences(AF4_signal, zero_samples, threshold)
    if af4_has_zero:
        return True, "ZERO_SIGNAL_DETECTED_AF4", af4_indices
    
    return False, "NO_ZERO_SIGNAL", np.array([], dtype=int)


def bandpower_welch(x, fs, f_lo, f_hi, nperseg=None):
    x = np.asarray(x)
    if x.size < 4:
        return 0.0
    if nperseg is None:
        nperseg = min(x.size, int(2 * fs))
    freqs, psd = welch(x, fs=fs, nperseg=nperseg, noverlap=nperseg//2)
    idx = (freqs >= f_lo) & (freqs <= f_hi)
    if not np.any(idx):
        return 0.0
    return np.trapezoid(psd[idx], freqs[idx])


def check_band_frequency_noise(
    AF3_signal, AF4_signal, fs=244, n_parts=4,
    r23_thresh=0.3,          # 20% of 4–35 Hz power sitting in 23–27 
    r20_thresh=0.3,          # 20% of 4–35 Hz power sitting in 20–25 Hz
    r15_thresh=0.3,          # 20% of 4–35 Hz power sitting in 15–20 Hz
    abs_floor_23=0.0,
    abs_floor_20=0.0,
    abs_floor_15=0.0,
    bad_ratio_threshold=1/2, 
):
    def check_signal(sig, label):
        sig = np.asarray(sig)
        if sig.size == 0:
            return True, f"{label}: EMPTY_SIGNAL => BAD", []

        seg_len = sig.size // n_parts
        parts = []
        for i in range(n_parts):
            s = i * seg_len
            e = (i + 1) * seg_len if i < n_parts - 1 else sig.size
            parts.append((s, e, sig[s:e]))

        details = []
        bad_parts = 0

        for i, (s, e, part) in enumerate(parts, start=1):
            # Baselines excluding delta
            p_4_35   = bandpower_welch(part, fs, 4, 35)

            # Noise bands
            p_23_27  = bandpower_welch(part, fs, 23, 27)
            p_20 = bandpower_welch(part, fs, 18, 23)
            p_15 = bandpower_welch(part, fs, 13, 18)

            # Band ratios
            r23 = p_23_27 / (p_4_35  + 1e-12)
            r20 = p_20 / (p_4_35  + 1e-12)
            r15 = p_15 / (p_4_35  + 1e-12)

            triggered = []
            if (r23 > r23_thresh) and (p_23_27 > abs_floor_23):
                triggered.append("23-27Hz")
            if (r20 > r20_thresh) and (p_20 > abs_floor_20):
                triggered.append("20-25Hz")
            if (r15 > r15_thresh) and (p_15 > abs_floor_15):
                triggered.append("15-20Hz")


            part_bad = len(triggered) > 0
            if part_bad:    
                bad_parts += 1

            details.append({
                "part": i,
                "bad": part_bad,
                "time_range": f"{int(s/fs)}-{int(e/fs)}s",
                "triggered": triggered if triggered else ["none"]
            })

        bad_ratio = bad_parts / n_parts
        is_bad = bad_ratio >= bad_ratio_threshold
        status = f"{label}: bad_parts={bad_parts}/{n_parts} ({bad_ratio:.0%}), FINAL={'BAD' if is_bad else 'GOOD'}"
        return is_bad, status, details

    af3_bad, af3_status, af3_details = check_signal(AF3_signal, "AF3")
    af4_bad, af4_status, af4_details = check_signal(AF4_signal, "AF4")
    return af3_bad, af3_status, af4_bad, af4_status, af3_details, af4_details



def check_artifacts(AF3_processed, AF4_processed, fs = 244, 
                         amplitude_threshold = 150, decision_threshold = 0.15):
    """
    Check artifact ratio of signal
    amplitude_threshold: in microvolts
    """

    # Count good samples per channel
    good_AF3 = np.abs(AF3_processed) <= amplitude_threshold
    good_AF4 = np.abs(AF4_processed) <= amplitude_threshold

    artifact_ratio_AF3 = 1 - np.sum(good_AF3) / len(AF3_processed)
    artifact_ratio_AF4 = 1 - np.sum(good_AF4) / len(AF4_processed)

    # Determine quality per channel
    is_good_AF3 = artifact_ratio_AF3 <= decision_threshold
    is_good_AF4 = artifact_ratio_AF4 <= decision_threshold

    # Segment is only good if both channels are good
    is_good_segment = is_good_AF3 and is_good_AF4
    status = "GOOD" if is_good_segment else "BAD"

    return artifact_ratio_AF3, artifact_ratio_AF4, status



############# MAIN FUNCTION ########################
def convert_csv_to_edf(csv_folder_path, edf_folder_path, sampling_frequency, device = 'BL'):
    os.makedirs(edf_folder_path, exist_ok=True)
    csv_files = [f for f in os.listdir(csv_folder_path) if f.endswith('.csv')]
    for csv_file in csv_files:
        csv_path = os.path.join(csv_folder_path, csv_file)
        edf_path = os.path.join(edf_folder_path, os.path.splitext(csv_file)[0] + '.edf')
        
        eeg_data_BL = pd.read_csv(csv_path)
        eeg_data_BL.columns = eeg_data_BL.columns.str.strip()  
        print(f"Processing: {csv_file}")
        if device == 'MUSE':
            AF7 = eeg_data_BL['AF7'].astype(np.float32)
            AF8 = eeg_data_BL['AF8'].astype(np.float32)
            TP9 = eeg_data_BL['TP9'].astype(np.float32)
            TP10 = eeg_data_BL['TP10'].astype(np.float32)
            AF3 = AF7 - TP9
            AF4 = AF8 - TP10
        else:
            # # Extract AF3 and AF4
            AF3 = eeg_data_BL['Header 26 Data'].astype(np.float32)  # BL AF3 = AF3 - T7
            AF4 = eeg_data_BL['Header 24 Data'].astype(np.float32)  # BL AF4 = AF4 - T8

        
        # Find first index of NaN in either channel
        nan_idx_af3 = AF3[AF3.isna()].index.min()
        nan_idx_af4 = AF4[AF4.isna()].index.min()
 

        first_nan_idx = min(nan_idx_af3 if pd.notna(nan_idx_af3) else len(AF3),
                            nan_idx_af4 if pd.notna(nan_idx_af4) else len(AF4))

        
        # Trim signals to remove NaNs
        AF3 = AF3[:first_nan_idx]
        AF4 = AF4[:first_nan_idx]

        # Convert to microvolts (µV)
        def convert_to_uV(raw_signal):
            return (1_000_000 * (raw_signal - 8388608) * 1.6 / 8388608 / 2).astype(np.int16)
        if device == 'BL':
            AF3_uV = convert_to_uV(AF3) 
            AF4_uV = convert_to_uV(AF4)
        else:
            AF3_uV = AF3 
            AF4_uV = AF4


        # Correction
        AF3_uV = AF3_uV - AF3_uV[0]
        AF4_uV = AF4_uV - AF4_uV[0]

       
        # Preprocessing
        AF3_uV_processed = preprocess_eeg(AF3_uV, fs=sampling_frequency)
        AF4_uV_processed = preprocess_eeg(AF4_uV, fs=sampling_frequency)


        print("-------01/ Check lengths:-----")
        print(len(AF3), len(AF4), "original lengths")
        print(len(AF3_uV_processed), len(AF4_uV_processed),  "processed lengths")
        print(f"Length check status: {colored_flag(len(AF3_uV_processed) == len(AF4_uV_processed))}")

        print("-------02/ Check correlation:-----")
        range_list = [[0, min(len(AF3_uV_processed), len(AF4_uV_processed))]]
        min_length = min(len(AF3_uV_processed), len(AF4_uV_processed))
        BL_corr, BL_p_val = pearsonr(AF3_uV_processed[:min_length], AF4_uV_processed[:min_length])
        print(f"BL Pearson correlation: {BL_corr:.4f}, p-value: {BL_p_val:.4f}, status: {colored_flag(BL_corr > 0.2)}")

        AF3_uV_delta = highpass_filter(AF3_uV_processed, cutoff=4, fs=sampling_frequency, order=3)
        AF4_uV_delta = highpass_filter(AF4_uV_processed, cutoff=4, fs=sampling_frequency, order=3)

        BL_corr_delta, BL_p_val_delta = pearsonr(AF3_uV_delta[:min_length], AF4_uV_delta[:min_length])
        print(f"BL Delta Pearson correlation: {BL_corr_delta:.4f}, p-value: {BL_p_val_delta:.4f}, status: {colored_flag(BL_corr_delta > 0.2)}")
         
         # Check for zero signal
        print("-------03/ Check zero signal:-----")
        zero_signal_bad, zero_signal_status, zero_signal_indices = check_zero_signal(AF3_uV_processed, AF4_uV_processed, fs=sampling_frequency, zero_duration=3)
        # is_good = not zero_signal_bad
        print(f"Zero signal check: {zero_signal_status}, N_of_zeros: {len(zero_signal_indices)}, Zero duration: {int(len(zero_signal_indices) / sampling_frequency)} seconds, Status: {colored_flag(not zero_signal_bad)}")
        
        
        # Check artifact ratio
        print("-------04/ Check artifact ratio:-----")
        artifact_ratio_AF3, artifact_ratio_AF4, status = check_artifacts(AF3_uV_processed, AF4_uV_processed, fs=sampling_frequency)
        print(f"AF3 artifact ratio: {100*artifact_ratio_AF3:.4f} %, AF4 artifact ratio: {100*artifact_ratio_AF4:.4f} %, Status: {colored_status_text(status)}")

        # Check for band frequency noise
        print("-------05/ Check band frequency noise:-----")
        af3_bad, af3_status, af4_bad, af4_status, af3_details, af4_details = check_band_frequency_noise(AF3_uV_processed, AF4_uV_processed, fs=sampling_frequency)
        
        if af3_bad:
            print(f"AF3 band noise check: {af3_status}, Status: {colored_flag(not af3_bad)} \nDetails: {[af3_detail['triggered'] for af3_detail in af3_details]}")
        
        if af4_bad:
            print(f"AF4 band noise check: {af4_status}, Status: {colored_flag(not af4_bad)} \nDetails: {[af4_detail['triggered'] for af4_detail in af4_details]}")
        
        print(f"Overall band noise status: {colored_flag(not (af3_bad or af4_bad))}")

        print("-------06/ Calculate Entropy (Optional)-----")
        entropy_AF3 = calculate_entropy(AF3_uV_processed)
        entropy_AF4 = calculate_entropy(AF4_uV_processed)
        print(f"AF3 Entropy: {entropy_AF3:.4f}, AF4 Entropy: {entropy_AF4:.4f}, STATUS: {colored_flag(abs(entropy_AF3 - entropy_AF4) < 1.5)}")

        # Determine overall quality
        bad_reasons = []
        if len(AF3_uV_processed) != len(AF4_uV_processed):
            bad_reasons.append("Length mismatch")
        if BL_corr <= 0.2:
            bad_reasons.append("Low correlation")
        if zero_signal_bad:
            bad_reasons.append("Zero signal detected")
        if status == "BAD":
            bad_reasons.append("High artifact ratio")
        if af3_bad or af4_bad:
            bad_reasons.append("Band frequency noise")


        is_good = len(bad_reasons) == 0
        print(f"-------07/ Overall Status: {colored_status_text('GOOD' if is_good else 'BAD')} -----")
        if not is_good:
            print(f"Bad reasons: {', '.join(bad_reasons)}")


        # If good, save as before
        if is_good:
            quality_folder = 'good'
            edf_subfolder_path = os.path.join(edf_folder_path, quality_folder)
            os.makedirs(edf_subfolder_path, exist_ok=True)
            edf_path = os.path.join(edf_subfolder_path, os.path.splitext(csv_file)[0] + '.edf')

            min_length = min(map(len, [AF3_uV, AF4_uV, AF3_uV_processed, AF4_uV_processed, AF3_uV_delta, AF4_uV_delta]))
            AF3_uV = AF3_uV[:min_length]
            AF4_uV = AF4_uV[:min_length]
            AF3_uV_processed = AF3_uV_processed[:min_length]
            AF4_uV_processed = AF4_uV_processed[:min_length]
            AF3_uV_delta = AF3_uV_delta[:min_length]
            AF4_uV_delta = AF4_uV_delta[:min_length]

            signals = np.vstack([AF3_uV, AF4_uV, AF3_uV_processed, AF4_uV_processed, AF3_uV_delta, AF4_uV_delta])

            signal_headers = []
            for label, signal in zip(['AF3', 'AF4', 'AF3_processed', 'AF4_processed', 'AF3_delta', 'AF4_delta'], signals):
                signal_headers.append({
                    'label': label,
                    'dimension': 'uV',
                    'sample_frequency': sampling_rate,  
                    'physical_min': signal.min(),
                    'physical_max': signal.max(),
                    'digital_min': -32768,
                    'digital_max': 32767,
                    'transducer': '',
                    'prefilter': ''
                })

            highlevel.write_edf(
                edf_path,
                signals,
                signal_headers,
                file_type=FILETYPE_EDFPLUS
            )

            print(f"Converted: {csv_file} → {edf_path} (GOOD)")

            csv_quality_folder = os.path.join(csv_folder_path, quality_folder)
            os.makedirs(csv_quality_folder, exist_ok=True)
            csv_new_path = os.path.join(csv_quality_folder, csv_file)
            os.rename(csv_path, csv_new_path)
            print(f"Moved CSV: {csv_file} → {csv_quality_folder}")
            print()
        else:
            # BAD: Apply WPT denoising
            print(f"Applying WPT denoising to {csv_file}...")
            # Use same parameters as in WPT_denoising_threshold.py
            target_bands = (
                (23.0, 27.0),
                (29.0, 35.0),
                (30.0, 37.0),
                (60.0, 65.0),
            )
            AF3_uV_denoised, *_ = wavelet_packet_threshold_bands(
                AF3_uV_processed,
                fs=sampling_frequency,
                wavelet="db4",
                level=3,
                target_bands=target_bands,
                mode="symmetric",
                threshold_rule="adaptive",
                threshold_type="garrote",
                threshold_scale=10.0,
                packet_thresholds=None,
                preserve_ratio=0.05,
                min_threshold=1.0,
                metric_for_logging="mad",
            )
            AF4_uV_denoised, *_ = wavelet_packet_threshold_bands(
                AF4_uV_processed,
                fs=sampling_frequency,
                wavelet="db4",
                level=3,
                target_bands=target_bands,
                mode="symmetric",
                threshold_rule="adaptive",
                threshold_type="garrote",
                threshold_scale=10.0,
                packet_thresholds=None,
                preserve_ratio=0.05,
                min_threshold=1.0,
                metric_for_logging="mad",
            )

            # Re-check quality on denoised signals
            min_length = min(map(len, [AF3_uV, AF4_uV, AF3_uV_processed, AF4_uV_processed, AF3_uV_denoised, AF4_uV_denoised]))
            AF3_uV = AF3_uV[:min_length]
            AF4_uV = AF4_uV[:min_length]
            AF3_uV_processed = AF3_uV_processed[:min_length]
            AF4_uV_processed = AF4_uV_processed[:min_length]
            AF3_uV_denoised = AF3_uV_denoised[:min_length]
            AF4_uV_denoised = AF4_uV_denoised[:min_length]

            # Re-run checks
            BL_corr, _ = pearsonr(AF3_uV_denoised, AF4_uV_denoised)
            zero_signal_bad, _, _ = check_zero_signal(AF3_uV_denoised, AF4_uV_denoised, fs=sampling_frequency, zero_duration=3)
            artifact_ratio_AF3, artifact_ratio_AF4, status = check_artifacts(AF3_uV_denoised, AF4_uV_denoised, fs=sampling_frequency)
            af3_bad, _, af4_bad, _, _, _ = check_band_frequency_noise(AF3_uV_denoised, AF4_uV_denoised, fs=sampling_frequency)

            bad_reasons_denoised = []
            if len(AF3_uV_denoised) != len(AF4_uV_denoised):
                bad_reasons_denoised.append("Length mismatch")
            if BL_corr <= 0.2:
                bad_reasons_denoised.append("Low correlation")
            if zero_signal_bad:
                bad_reasons_denoised.append("Zero signal detected")
            if status == "BAD":
                bad_reasons_denoised.append("High artifact ratio")
            if af3_bad or af4_bad:
                bad_reasons_denoised.append("Band frequency noise")

            is_good_denoised = len(bad_reasons_denoised) == 0
            print(f"Denoised status: {colored_status_text('GOOD' if is_good_denoised else 'BAD')}")
            if not is_good_denoised:
                print(f"Bad reasons after denoising: {', '.join(bad_reasons_denoised)}")

            # Save to good_denoised or bad_denoised
            denoised_folder = 'good_denoised' if is_good_denoised else 'bad_denoised'
            edf_subfolder_path = os.path.join(edf_folder_path, denoised_folder)
            os.makedirs(edf_subfolder_path, exist_ok=True)
            edf_path = os.path.join(edf_subfolder_path, os.path.splitext(csv_file)[0] + '.edf')

            signals = np.vstack([AF3_uV, AF4_uV, AF3_uV_processed, AF4_uV_processed, AF3_uV_denoised, AF4_uV_denoised])
            signal_headers = []
            for label, signal in zip(['AF3', 'AF4', 'AF3_processed', 'AF4_processed', 'AF3_denoised', 'AF4_denoised'], signals):
                signal_headers.append({
                    'label': label,
                    'dimension': 'uV',
                    'sample_frequency': sampling_rate,  
                    'physical_min': signal.min(),
                    'physical_max': signal.max(),
                    'digital_min': -32768,
                    'digital_max': 32767,
                    'transducer': '',
                    'prefilter': ''
                })
            highlevel.write_edf(
                edf_path,
                signals,
                signal_headers,
                file_type=FILETYPE_EDFPLUS
            )
            print(f"Converted: {csv_file} → {edf_path} ({denoised_folder.upper()})")

            # Move CSV to denoised folder
            csv_quality_folder = os.path.join(csv_folder_path, denoised_folder)
            os.makedirs(csv_quality_folder, exist_ok=True)
            csv_new_path = os.path.join(csv_quality_folder, csv_file)
            os.rename(csv_path, csv_new_path)
            print(f"Moved CSV: {csv_file} → {csv_quality_folder}")
            print()




if __name__ == '__main__':
    csv_folder_path = './Data'
    edf_folder_path = './edf_data'
    sampling_rate = 244  # Hz
    convert_csv_to_edf(csv_folder_path, edf_folder_path, sampling_rate, device='BL')


path = '/user/minhphan/Documents/Brain-Life/drive-download-20260626T064830Z-3-001'

convert_csv_to_edf(path, edf_folder_path, sampling_rate, device='BL')