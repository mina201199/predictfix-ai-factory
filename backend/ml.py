"""Shared feature extraction: training and serving use the same code."""
import numpy as np
from scipy.stats import kurtosis, skew

WINDOW = 2048
FEATURE_NAMES = ['rms', 'std', 'peak', 'peak_to_peak', 'crest_factor', 'kurtosis', 'skew',
                 'spectral_centroid', 'band_0', 'band_1', 'band_2', 'band_3', 'band_4', 'band_5']
LABELS = {'inner_race': '內圈故障', 'ball': '滾珠故障', 'outer_race': '外圈故障'}

def features(values):
    x = np.asarray(values, dtype=float)
    if x.shape != (WINDOW,) or not np.isfinite(x).all():
        raise ValueError('Expected 2048 finite acceleration samples')
    x = x - x.mean()
    rms = float(np.sqrt(np.mean(x*x)))
    spectrum = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2
    total = float(spectrum.sum()) + 1e-12
    bands = np.array_split(spectrum, 6)
    vector = [rms, float(x.std()), float(np.abs(x).max()), float(np.ptp(x)),
              float(np.abs(x).max()/(rms+1e-12)), float(kurtosis(x)), float(skew(x)),
              float(np.dot(np.arange(len(spectrum)), spectrum)/total)]
    vector.extend(float(b.sum()/total) for b in bands)
    return np.nan_to_num(vector).tolist()
