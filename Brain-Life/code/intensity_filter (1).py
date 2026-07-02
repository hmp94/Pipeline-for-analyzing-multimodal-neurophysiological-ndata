import numpy as np


def _fill_nan_for_filtering(signal):
    """Return a finite copy for filtering and a mask of original NaNs."""
    x = np.asarray(signal, dtype=float)
    nan_mask = np.isnan(x)
    if x.size == 0 or not np.any(nan_mask):
        return x.copy(), nan_mask

    finite_idx = np.flatnonzero(~nan_mask)
    if finite_idx.size == 0:
        return np.zeros_like(x, dtype=float), nan_mask

    filled = x.copy()
    filled[nan_mask] = np.interp(
        np.flatnonzero(nan_mask),
        finite_idx,
        x[finite_idx],
    )
    return filled, nan_mask


def dwt_denoise_filter(
    data,
    fs=None,
    wavelet="db4",
    level=None,
    max_level=None,
    threshold_scale=1.0,
    threshold_mode="soft",
    extension_mode="symmetric",
    preserve_nan=True,
    outlier_zscore=2.0,
    outlier_shrinkage=0.05,
):
    """Denoise raw intensity by shrinking outlier wavelet coefficients.

    Each detail coefficient level is treated as its own distribution. Coefficients
    that are robust outliers within that level are shrunk toward the level median;
    non-outlier coefficients are unchanged.
    """
    try:
        import pywt
    except Exception as exc:
        raise ImportError(
            "PyWavelets is required for dwt_denoise_filter. "
            "Install or repair it with: python3 -m pip install --upgrade --force-reinstall PyWavelets"
        ) from exc

    signal, nan_mask = _fill_nan_for_filtering(data)
    n = signal.size
    filtered = signal.copy()

    if n < 4:
        if preserve_nan:
            filtered[nan_mask] = np.nan
        return filtered

    wavelet_obj = pywt.Wavelet(wavelet)
    max_possible_level = pywt.dwt_max_level(n, wavelet_obj.dec_len)
    if max_level is not None:
        max_possible_level = min(max_possible_level, int(max_level))
    if max_possible_level < 1:
        if preserve_nan:
            filtered[nan_mask] = np.nan
        return filtered

    if level is None:
        level = max(1, min(5, max_possible_level))
    else:
        level = int(level)
    level = max(1, min(level, max_possible_level))

    if threshold_mode not in {"soft", "hard"}:
        raise ValueError("threshold_mode must be 'soft' or 'hard'.")

    coeffs = pywt.wavedec(signal, wavelet_obj, mode=extension_mode, level=level)
    cutoff_z = max(float(outlier_zscore) * float(threshold_scale), 1e-8)
    outlier_shrinkage = float(outlier_shrinkage)
    outlier_shrinkage = min(max(outlier_shrinkage, 0.0), 1.0)

    denoised_coeffs = [coeffs[0]]
    for detail in coeffs[1:]:
        detail = np.asarray(detail, dtype=float)
        center = np.median(detail)
        abs_dev = np.abs(detail - center)
        robust_sigma = 1.4826 * np.median(abs_dev)

        if not np.isfinite(robust_sigma) or robust_sigma <= 0:
            q25, q75 = np.percentile(detail, [25, 75])
            # robust_sigma = (q75 - q25) / 1.349
            robust_sigma = q75 - q25

        if not np.isfinite(robust_sigma) or robust_sigma <= 0:
            robust_sigma = np.std(detail)

        if not np.isfinite(robust_sigma) or robust_sigma <= 0:
            denoised_coeffs.append(detail.copy())
            continue

        outlier_limit = cutoff_z * robust_sigma
        outlier_mask = abs_dev > outlier_limit
        shrunk = detail.copy()

        if np.any(outlier_mask):
            signed_dev = detail[outlier_mask] - center
            excess = np.abs(signed_dev) - outlier_limit
            if threshold_mode == "soft":
                new_abs_dev = outlier_limit + outlier_shrinkage * excess
            else:
                new_abs_dev = np.full_like(excess, outlier_limit)
            shrunk[outlier_mask] = center + np.sign(signed_dev) * new_abs_dev

        denoised_coeffs.append(shrunk)

    filtered = pywt.waverec(denoised_coeffs, wavelet_obj, mode=extension_mode)[:n]

    if preserve_nan:
        filtered[nan_mask] = np.nan

    return filtered


def hampel_filter(data, fs=None, window_sec=0.25, window_size=None, n_sigmas=6.0):

    signal = np.asarray(data, dtype=float)
    filtered = signal.copy()

    if signal.size == 0:
        return filtered

    if window_size is None:
        if fs is None:
            window_size = 7
        else:
            window_size = max(1, int(round(window_sec * fs)))

    window_size = int(window_size)
    if window_size < 1:
        return filtered

    scale = 1.4826
    for idx in range(signal.size):
        start = max(0, idx - window_size)
        baseline = filtered[start:idx]
        if baseline.size == 0:
            continue

        median = np.nanmedian(baseline)
        mad = scale * np.nanmedian(np.abs(baseline - median))

        if np.isnan(signal[idx]) or np.isnan(median):
            continue

        if mad == 0:
            abs_dev = np.abs(baseline - median)
            nonzero_dev = abs_dev[abs_dev > 0]
            if nonzero_dev.size == 0:
                continue
            mad = scale * np.nanmedian(nonzero_dev)

        if mad > 0 and np.abs(signal[idx] - median) > n_sigmas * mad:
            filtered[idx] = median

    return filtered
