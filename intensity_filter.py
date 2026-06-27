import numpy as np


def hampel_filter(x, fs, window_sec=0.25, window_size=None, n_sigmas=6.0):
    """Simple Hampel filter implemented with a rolling median and MAD."""
    x = np.asarray(x, dtype=float)
    if x.size == 0:
        return x

    if window_size is None:
        window_size = max(3, int(round(window_sec * fs)))
    if window_size % 2 == 0:
        window_size += 1
    if window_size < 3:
        window_size = 3

    if x.size < window_size:
        return x

    pad = window_size // 2
    padded = np.pad(x, (pad, pad), mode="edge")
    median_vals = np.empty_like(x, dtype=float)
    mad_vals = np.empty_like(x, dtype=float)

    for i in range(x.size):
        window = padded[i:i + window_size]
        med = np.median(window)
        mad = np.median(np.abs(window - med))
        median_vals[i] = med
        mad_vals[i] = mad

    threshold = n_sigmas * 1.4826 * mad_vals
    filtered = x.copy()
    outlier_mask = np.abs(x - median_vals) > threshold
    filtered[outlier_mask] = median_vals[outlier_mask]
    return filtered


def dwt_denoise_filter(
    x,
    fs,
    wavelet="db4",
    level=None,
    threshold_scale=1.0,
    threshold_mode="soft",
    extension_mode="symmetric",
):
    """Best-effort DWT denoising with a simple fallback to the input signal."""
    try:
        import pywt
    except ImportError:
        return np.asarray(x, dtype=float)

    x = np.asarray(x, dtype=float)
    if x.size == 0:
        return x

    if level is None:
        level = min(3, int(np.floor(np.log2(x.size))) - 1)
    if level < 1:
        return x

    coeffs = pywt.wavedec(x, wavelet=wavelet, level=level, mode=extension_mode)
    sigma = np.median(np.abs(coeffs[-1])) / 0.6745 if len(coeffs[-1]) > 0 else 0.0
    threshold = threshold_scale * sigma
    if threshold <= 0:
        return x

    denoised_coeffs = [coeffs[0]]
    for coeff in coeffs[1:]:
        denoised_coeffs.append(pywt.threshold(coeff, value=threshold, mode=threshold_mode))
    return pywt.waverec(denoised_coeffs, wavelet=wavelet, mode=extension_mode)[:x.size]
