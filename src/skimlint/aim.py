"""Visual clutter metrics from Aalto Interface Metrics (AIM).

Ported from https://github.com/aalto-ui/aim (MIT License, Copyright (c) User
Interfaces group, Aalto University; see NOTICE). Results match the original
implementation; the changes are speedups only:

- m6: the per-pixel Python loops are vectorized with numpy.
- m7: the Python-loop `histc` is replaced by `np.bincount`; a constant chroma
  channel skips its pyramid, because its subband entropy is always 0.
- m8: separable 1-D convolutions use `scipy.ndimage.convolve1d`, 2-D ones use
  FFT convolution, the edge normalization of a 1-D kernel is computed on one
  row or column, and the `_collapse` pixel loop is a numpy maximum.

Each metric takes an RGB image as an `(height, width, 3)` uint8 array. m1 and m2
take the PNG bytes, because AIM defines them as file sizes.
"""

from __future__ import annotations

import io
from typing import Dict, List, Tuple

import cv2
import numpy as np
import pyrtools as pt
from PIL import Image
from scipy import ndimage, signal
from skimage import transform

# ---------------------------------------------------------------------------
# Shared helpers (aim/common/image_visual_clutter_utils.py)
# ---------------------------------------------------------------------------


def rgb2lab(im: np.ndarray) -> np.ndarray:
    im = im / 255.0
    mask = im >= 0.04045
    im[mask] = ((im[mask] + 0.055) / 1.055) ** 2.4
    im[~mask] = im[~mask] / 12.92
    matrix = np.array(
        [
            [0.412453, 0.357580, 0.180423],
            [0.212671, 0.715160, 0.072169],
            [0.019334, 0.119193, 0.950227],
        ]
    )
    c_im = np.dot(im, matrix.T)
    c_im[:, :, 0] = c_im[:, :, 0] / 95.047
    c_im[:, :, 1] = c_im[:, :, 1] / 100.000
    c_im[:, :, 2] = c_im[:, :, 2] / 108.833
    mask = c_im >= 0.008856
    c_im[mask] = c_im[mask] ** (1 / 3)
    c_im[~mask] = 7.787 * c_im[~mask] + 16 / 116
    im_lab = np.zeros_like(c_im)
    im_lab[:, :, 0] = (116 * c_im[:, :, 1]) - 16
    im_lab[:, :, 1] = 500 * (c_im[:, :, 0] - c_im[:, :, 1])
    im_lab[:, :, 2] = 200 * (c_im[:, :, 1] - c_im[:, :, 2])
    return im_lab


def conv2(x: np.ndarray, y: np.ndarray, mode: str | None = None) -> np.ndarray:
    """MATLAB `conv2`. "same" crops the centre of the full convolution."""
    if mode != "same":
        return signal.convolve2d(x, y)
    if y.shape[0] % 2 == 0 or y.shape[1] % 2 == 0:
        return np.rot90(signal.convolve2d(np.rot90(x, 2), np.rot90(y, 2), mode="same"), 2)
    # With an odd-sized kernel, MATLAB's and SciPy's "same" crops are the same,
    # so the original rot90 round trip is not needed.
    x = np.asarray(x, dtype=np.float64)
    if y.shape[0] == 1:
        return ndimage.convolve1d(x, y[0], axis=1, mode="constant")
    if y.shape[1] == 1:
        return ndimage.convolve1d(x, y[:, 0], axis=0, mode="constant")
    return signal.fftconvolve(x, y, mode="same")


def rr_overlap_conv(kernel: np.ndarray, in_: np.ndarray) -> np.ndarray:
    """Filters `in_`, rescaling the kernel where it hangs over the image edge."""
    out = conv2(in_, kernel, mode="same")
    if kernel.shape[0] == 1 and kernel.shape[1] % 2:
        # The overlap of a row kernel depends on the column only.
        overlapsum = conv2(np.ones((1, in_.shape[1])), kernel, "same")
    elif kernel.shape[1] == 1 and kernel.shape[0] % 2:
        overlapsum = conv2(np.ones((in_.shape[0], 1)), kernel, "same")
    else:
        overlapsum = conv2(np.ones_like(in_), kernel, "same")
    return np.sum(kernel) * out / overlapsum


def rr_gauss_filter_1d(halfsupport: int, sigma: float, center: float = 0) -> np.ndarray:
    t = np.arange(-halfsupport, halfsupport + 1)
    kernel = np.exp(-((t - center) ** 2) / (2 * sigma**2))
    kernel = kernel / np.sum(kernel)
    return kernel.reshape(1, -1)


def dog1_filter(a: int, sigma: float) -> Tuple[np.ndarray, np.ndarray]:
    sigi = 0.71 * sigma
    sigo = 1.14 * sigma
    t = np.arange(-a, a + 1)
    gi = np.exp(-(t**2) / (2 * sigi**2))
    gi = gi / np.sum(gi)
    go = np.exp(-(t**2) / (2 * sigo**2))
    go = go / np.sum(go)
    return gi.reshape(1, -1), go.reshape(1, -1)


def filt2(kernel: np.ndarray, im1: np.ndarray) -> np.ndarray:
    """MATLAB `filter2` with odd reflection at the borders."""
    ky, kx = kernel.shape
    iy, ix = im1.shape
    if kx > ix or ky > iy:
        raise ValueError("borders must be thinner than image")
    imbig = cv2.copyMakeBorder(im1, ky, ky, kx, kx, cv2.BORDER_REFLECT_101)
    imbig = conv2(imbig, kernel, "same")
    return imbig[ky : ky + iy, kx : kx + ix]


def rr_contrast_1channel(pyr: Dict, dog_sigma: float = 2) -> List[np.ndarray]:
    inner_g1, outer_g1 = dog1_filter(round(dog_sigma * 3), dog_sigma)
    contrast = []
    for i in range(len(pyr)):
        inner = filt2(inner_g1.T, filt2(inner_g1, pyr[(i, 0)]))
        outer = filt2(outer_g1.T, filt2(outer_g1, pyr[(i, 0)]))
        contrast.append(abs(inner - outer))
    return contrast


def reduce(image0: np.ndarray, kernel: np.ndarray | None = None) -> np.ndarray:
    if kernel is None:
        kernel = np.array([[0.05, 0.25, 0.4, 0.25, 0.05]])
    ysize, xsize = image0.shape
    image0 = filt2(kernel, image0)
    image1 = image0[:, 0:xsize:2]
    image1 = filt2(kernel.T, image1)
    return image1[0:ysize:2, :]


def rr_overlap_conv_expand(in_: np.ndarray, kernel: np.ndarray) -> np.ndarray:
    ysize, xsize = in_.shape
    kernel = kernel * 2  # sum 2 to account for the zero padding
    tmp = np.zeros([ysize, 2 * xsize])
    tmp[:, 0::2] = in_
    tmp = rr_overlap_conv(kernel, tmp)
    out = np.zeros([2 * ysize, 2 * xsize])
    out[0::2, :] = tmp
    return rr_overlap_conv(kernel.T, out)


def pool_new(in_: List[np.ndarray], sigma: float) -> List[np.ndarray]:
    kernel = rr_gauss_filter_1d(round(2 * sigma), sigma)
    return [reduce(rr_overlap_conv_expand(x, kernel), kernel) for x in in_]


def imrotate(im: np.ndarray, angle: float) -> np.ndarray:
    """Bicubic rotation that keeps the size, with skimage's [0, 1] range handled."""
    immin = np.min(im)
    imrange = np.max(im) - immin
    im = (im - immin) / imrange
    im = transform.rotate(im, angle, order=3, resize=False)
    return im * imrange + immin


def orient_filt_new(pyr: np.ndarray, sigma: float = 16 / 14) -> List[np.ndarray]:
    """2nd-derivative filters in the order horizontal, vertical, up-left, down-right."""
    halfsupport = round(3 * sigma)
    gx = rr_gauss_filter_1d(halfsupport, sigma)

    def g(center: float) -> np.ndarray:
        k = conv2(gx, rr_gauss_filter_1d(halfsupport, sigma, center).T)
        return k / np.sum(k)

    ga, gb, gc = g(sigma), g(0), g(-sigma)
    h = -ga + 2 * gb - gc
    v = h.T

    def rotated(angle: float) -> np.ndarray:
        gga, ggb, ggc = (imrotate(k, angle) for k in (ga, gb, gc))
        return -gga / np.sum(gga) + 2 * ggb / np.sum(ggb) - ggc / np.sum(ggc)

    r = rotated(45)
    left = rotated(-45)
    return [filt2(k, pyr) for k in (h, v, left, r)]


def histc(x: np.ndarray, bins: np.ndarray) -> np.ndarray:
    """MATLAB `histc`. Index 0 from `np.digitize` wraps to the last bin, as in AIM."""
    map_to_bins = np.digitize(x, bins)
    counts = np.bincount((map_to_bins - 1) % bins.shape[0], minlength=bins.shape[0])
    return counts.astype(float)


def entropy(x: np.ndarray, nbins: int | None = None) -> float:
    nsamples = x.shape[0]
    if nbins is None:
        nbins = int(np.ceil(np.sqrt(nsamples)))
    elif nbins == 1:
        return 0
    edges = np.histogram(x, bins=nbins - 1)[1]
    ref_hist = histc(x, edges)
    ref_hist = ref_hist / float(np.sum(ref_hist))
    ref_hist = ref_hist[np.nonzero(ref_hist)]
    return float(-np.sum(ref_hist * np.log(ref_hist)))


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def m1_png_file_size(png: bytes) -> int:
    """PNG file size in bytes."""
    return len(png)


def m2_jpeg_file_size(png: bytes) -> int:
    """JPEG file size in bytes, at quality 70."""
    buf = io.BytesIO()
    Image.open(io.BytesIO(png)).convert("RGB").save(buf, format="JPEG", quality=70)
    return buf.tell()


def m3_distinct_rgb_values(rgb: np.ndarray) -> int:
    """Number of RGB values that occur on more than 5 pixels."""
    flat = rgb.reshape(-1, 3).astype(np.uint32)
    keys = (flat[:, 0] << 16) | (flat[:, 1] << 8) | flat[:, 2]
    _, counts = np.unique(keys, return_counts=True)
    return int(np.count_nonzero(counts > 5))


def _blurred_gray(rgb: np.ndarray) -> np.ndarray:
    gray = np.array(Image.fromarray(rgb).convert("L"))
    return cv2.GaussianBlur(src=gray, ksize=(0, 0), sigmaX=2, sigmaY=2)


def m4_contour_density(rgb: np.ndarray) -> float:
    """Share of pixels on a Canny edge, with AIM's desktop thresholds."""
    edges = cv2.Canny(image=_blurred_gray(rgb), threshold1=28.05, threshold2=68.85)
    return np.count_nonzero(edges) / edges.size


def m5_figure_ground_contrast(rgb: np.ndarray) -> float:
    blurred = _blurred_gray(rgb)
    levels = list(range(1, 8))
    high = [round(255 * round(0.1 * level, 1), 2) for level in levels]
    low = [round(0.4 * t, 2) for t in high]
    # Python ints, so that a blank screen raises ZeroDivisionError as in AIM, not NaN.
    edges = [int(np.count_nonzero(cv2.Canny(blurred, lo, hi))) for lo, hi in zip(low, high)]
    weighted = sum(
        (edges[i] - edges[i + 1]) * (1 - (levels[i] - 1) / (len(edges) - 1))
        for i in range(len(edges) - 1)
    )
    try:
        return weighted / (edges[0] - edges[-1])
    except ZeroDivisionError:
        return 0.0


def _contours(rgb: np.ndarray) -> np.ndarray:
    """AIM's contour map for m6.

    The original scans column by column, top to bottom, and marks a pixel when
    a 4-neighbour differs by more than 50 in any channel and that neighbour is
    not marked yet. East and south neighbours are never marked yet, so only the
    north and west tests depend on earlier results. Columns stay sequential;
    the north chain inside a column is solved in closed form: a run of pixels
    that are marked only through their north neighbour alternates.
    """
    rgb = rgb.astype(np.int16)
    h, w = rgb.shape[:2]
    vertical = (np.abs(rgb[1:] - rgb[:-1]) > 50).any(axis=-1)
    horizontal = (np.abs(rgb[:, 1:] - rgb[:, :-1]) > 50).any(axis=-1)
    north = np.zeros((h, w), bool)
    north[1:] = vertical
    south = np.zeros((h, w), bool)
    south[:-1] = vertical
    east = np.zeros((h, w), bool)
    east[:, :-1] = horizontal
    west = np.zeros((h, w), bool)
    west[:, 1:] = horizontal

    out = np.zeros((h, w), bool)
    rows = np.arange(h)
    prev = np.zeros(h, bool)
    for x in range(w):
        base = south[:, x] | east[:, x] | (west[:, x] & ~prev)
        chain = north[:, x] & ~base
        starts = chain & ~np.concatenate(([False], chain[:-1]))
        run_start = np.maximum.accumulate(np.where(starts, rows, 0))
        before = base[np.maximum(run_start - 1, 0)]
        odd = (rows - run_start) % 2 == 1
        prev = np.where(chain, before == odd, base)
        out[:, x] = prev
    return out


def m6_contour_congestion(rgb: np.ndarray) -> float:
    """Share of contour pixels with another contour within 20 px in all 4 directions."""
    contours = _contours(rgb)
    n_contours = np.count_nonzero(contours)
    if n_contours == 0:
        return 0.0
    t = 20
    h, w = contours.shape
    c = contours.astype(np.int32)
    col_sum = np.vstack([np.zeros((1, w), np.int32), np.cumsum(c, axis=0)])
    row_sum = np.hstack([np.zeros((h, 1), np.int32), np.cumsum(c, axis=1)])
    ys = np.arange(h)[:, None]
    xs = np.arange(w)[None, :]

    def window(cum: np.ndarray, lo: np.ndarray, hi: np.ndarray, axis: int) -> np.ndarray:
        lo = np.clip(lo, 0, cum.shape[axis] - 1)
        hi = np.clip(hi, 0, cum.shape[axis] - 1)
        if axis == 0:
            lo_b, hi_b = np.broadcast_to(lo, (h, w)), np.broadcast_to(hi, (h, w))
            return np.take_along_axis(cum, hi_b, 0) - np.take_along_axis(cum, lo_b, 0)
        lo_b, hi_b = np.broadcast_to(lo, (h, w)), np.broadcast_to(hi, (h, w))
        return np.take_along_axis(cum, hi_b, 1) - np.take_along_axis(cum, lo_b, 1)

    north = (ys - t < 0) | (window(col_sum, ys - t, ys, 0) > 0)
    south = (h < ys + 1 + t) | (window(col_sum, ys + 1, ys + 1 + t, 0) > 0)
    east = (w < xs + 1 + t) | (window(row_sum, xs + 1, xs + 1 + t, 1) > 0)
    west = (xs - t < 0) | (window(row_sum, xs - t, xs, 1) > 0)
    congested = contours & north & south & east & west
    return np.count_nonzero(congested) / n_contours


def _band_entropy(channel: np.ndarray) -> List[float]:
    pyr = pt.pyramids.SteerablePyramidFreq(channel, height=3, order=3)
    return [entropy(band.ravel()) for band in pyr.pyr_coeffs.values()]


def m7_subband_entropy(rgb: np.ndarray) -> float:
    """Subband entropy (Rosenholtz et al. 2007)."""
    weight_chroma = 0.0625
    lab = rgb2lab(rgb).astype(np.float32)
    clutter = float(np.mean(_band_entropy(lab[:, :, 0])))
    for chroma in (lab[:, :, 1], lab[:, :, 2]):
        # A constant channel is zeroed, and every subband of zeros has entropy 0.
        if np.max(chroma) - np.min(chroma) >= 0.008:
            clutter += weight_chroma * float(np.mean(_band_entropy(chroma)))
    return clutter / (1 + 2 * weight_chroma)


def _collapse(levels: List[np.ndarray]) -> np.ndarray:
    kernel_1d = np.array([[0.05, 0.25, 0.4, 0.25, 0.05]])
    kernel_2d = conv2(kernel_1d, kernel_1d.T)
    clutter_map = levels[0].copy()
    for scale in range(1, len(levels)):
        here = levels[scale]
        for _ in range(scale):
            here = pt.upConv(image=here, filt=kernel_2d, edge_type="reflect1", step=[2, 2], start=[0, 0])
        h = min(clutter_map.shape[0], here.shape[0])
        w = min(clutter_map.shape[1], here.shape[1])
        np.maximum(clutter_map[:h, :w], here[:h, :w], out=clutter_map[:h, :w])
    return clutter_map


def _color_clutter(l_pyr: Dict, a_pyr: Dict, b_pyr: Dict, levels: int) -> np.ndarray:
    big_g = rr_gauss_filter_1d(round(2 * 3), 3)

    def pooled(x: np.ndarray) -> np.ndarray:
        return rr_overlap_conv(big_g.T, rr_overlap_conv(big_g, x))

    clutter_levels = []
    for i in range(levels):
        l, a, b = l_pyr[(i, 0)], a_pyr[(i, 0)], b_pyr[(i, 0)]
        dl, da, db = pooled(l), pooled(a), pooled(b)
        c00 = pooled(l**2) - dl**2 + 0.0007**2
        c01 = pooled(l * a) - dl * da
        c02 = pooled(l * b) - dl * db
        c11 = pooled(a**2) - da**2 + 0.1**2
        c12 = pooled(a * b) - da * db
        c22 = pooled(b**2) - db**2 + 0.05**2
        det = (
            c00 * (c11 * c22 - c12 * c12)
            - c01 * (c01 * c22 - c12 * c02)
            + c02 * (c01 * c12 - c11 * c02)
        )
        clutter_levels.append(np.sqrt(det) ** (1 / 3))
    return _collapse(clutter_levels)


def _contrast_clutter(l_pyr: Dict, levels: int) -> np.ndarray:
    contrast = rr_contrast_1channel(l_pyr, 1)
    big_g = rr_gauss_filter_1d(round(6), 3)

    def pooled(x: np.ndarray) -> np.ndarray:
        return rr_overlap_conv(big_g.T, rr_overlap_conv(big_g, x))

    clutter_levels = []
    for scale in range(levels):
        mean_d = pooled(contrast[scale])
        mean_d2 = pooled(contrast[scale] ** 2)
        clutter_levels.append(np.sqrt(abs(mean_d2 - mean_d**2)))
    return _collapse(clutter_levels)


def _orientation_clutter(l_pyr: Dict, levels: int) -> np.ndarray:
    filter_scale = 16 / 14 * 1.75
    pool_scale = 1.75
    opp_energy_noise = 1.0
    orient_noise = 0.001
    orient_pool_sigma = 7 / 2

    big_g = rr_gauss_filter_1d(round(8 * orient_pool_sigma), 4 * orient_pool_sigma)

    def pooled(x: np.ndarray) -> np.ndarray:
        return rr_overlap_conv(big_g.T, rr_overlap_conv(big_g, x))

    clutter_levels = []
    for scale in range(levels):
        hvdd = [x**2 for x in orient_filt_new(l_pyr[(scale, 0)], filter_scale)]
        hvdd = pool_new(hvdd, pool_scale)
        total = hvdd[0] + hvdd[1] + hvdd[2] + hvdd[3] + opp_energy_noise
        cmx = (hvdd[0] - hvdd[1]) / total  # H - V
        smx = (hvdd[3] - hvdd[2]) / total  # R - L
        dc, ds = pooled(cmx), pooled(smx)
        c00 = pooled(cmx**2) - dc**2 + orient_noise
        c01 = pooled(cmx * smx) - dc * ds
        c11 = pooled(smx**2) - ds**2 + orient_noise
        clutter_levels.append((c00 * c11 - c01**2) ** (1 / 4))
    return _collapse(clutter_levels)


def m8_feature_congestion(rgb: np.ndarray) -> float:
    """Feature congestion (Rosenholtz et al. 2007): color, contrast, and orientation clutter."""
    levels = 3
    lab = rgb2lab(rgb).astype(np.float32)
    l_pyr = pt.pyramids.GaussianPyramid(lab[:, :, 0], height=levels).pyr_coeffs
    a_pyr = pt.pyramids.GaussianPyramid(lab[:, :, 1], height=levels).pyr_coeffs
    b_pyr = pt.pyramids.GaussianPyramid(lab[:, :, 2], height=levels).pyr_coeffs
    clutter_map = (
        _color_clutter(l_pyr, a_pyr, b_pyr, levels) / 0.2088
        + _contrast_clutter(l_pyr, levels) / 0.0660
        + _orientation_clutter(l_pyr, levels) / 0.0269
    )
    return float(np.mean(clutter_map))


def m13_luminance_std(rgb: np.ndarray) -> float:
    """Standard deviation of Rec. 709 luminance."""
    rgbf = rgb.astype(float)
    luminance = 0.2126 * rgbf[:, :, 0] + 0.7152 * rgbf[:, :, 1] + 0.0722 * rgbf[:, :, 2]
    return float(np.std(luminance))


# Name, description, function, and whether the function takes PNG bytes.
METRICS = {
    "m1": ("png_file_size", "PNG file size in bytes", m1_png_file_size, True),
    "m2": ("jpeg_file_size", "JPEG file size in bytes", m2_jpeg_file_size, True),
    "m3": ("distinct_rgb_values", "Distinct RGB values", m3_distinct_rgb_values, False),
    "m4": ("contour_density", "Contour density", m4_contour_density, False),
    "m5": ("figure_ground_contrast", "Figure-ground contrast", m5_figure_ground_contrast, False),
    "m6": ("contour_congestion", "Contour congestion", m6_contour_congestion, False),
    "m7": ("subband_entropy", "Subband entropy", m7_subband_entropy, False),
    "m8": ("feature_congestion", "Feature congestion", m8_feature_congestion, False),
    "m13": ("luminance_std", "Luminance standard deviation", m13_luminance_std, False),
}


def run_metrics(png: bytes, metric_ids: List[str]) -> Dict[str, float]:
    rgb = np.array(Image.open(io.BytesIO(png)).convert("RGB"))
    results = {}
    for metric_id in metric_ids:
        _, _, fn, takes_png = METRICS[metric_id]
        results[metric_id] = float(fn(png if takes_png else rgb))
    return results
