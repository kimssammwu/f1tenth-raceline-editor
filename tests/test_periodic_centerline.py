import numpy as np

from f1tenth_raceline.core import _periodic_resample_closed, smooth_centerline
from f1tenth_raceline.online_recovery import geometric_curvature_closed


def _circle(radius: float = 2.0, n: int = 80, phase: float = 0.0) -> np.ndarray:
    theta = np.linspace(0.0, 2.0 * np.pi, n, endpoint=False) + phase
    return np.column_stack((radius * np.cos(theta), radius * np.sin(theta)))


def test_periodic_resample_has_no_seam_curvature_spike():
    radius = 2.0
    resampled = _periodic_resample_closed(_circle(radius, 40, phase=0.37), step=0.1)
    curvature = np.abs(geometric_curvature_closed(resampled))

    assert len(resampled) > 100
    assert np.max(curvature) < 0.55
    assert np.max(curvature[:3]) < 0.55
    assert np.max(curvature[-3:]) < 0.55


def test_periodic_resample_is_independent_of_contour_start_index():
    points = _circle(2.5, 64)
    a = _periodic_resample_closed(points, step=0.1)
    b = _periodic_resample_closed(np.roll(points, 17, axis=0), step=0.1)

    ka = np.sort(np.abs(geometric_curvature_closed(a)))
    kb = np.sort(np.abs(geometric_curvature_closed(b)))
    assert len(a) == len(b)
    assert np.max(np.abs(ka - kb)) < 1e-8


def test_smoothing_wraps_across_closed_contour_seam():
    points = _circle(20.0, 200)
    noisy = points.copy()
    noisy[0] += np.array([0.8, -0.6])
    smoothed = smooth_centerline(noisy)

    # A disturbance at sample zero must influence both sides of a periodic
    # filter. This guards against reverting to open-ended Savitzky-Golay logic.
    assert not np.allclose(smoothed[-1], points[-1])
    assert not np.allclose(smoothed[1], points[1])


def test_periodic_resample_removes_duplicate_closure_point():
    points = _circle(3.0, 60)
    explicitly_closed = np.vstack((points, points[0]))
    resampled = _periodic_resample_closed(explicitly_closed, step=0.2)

    assert np.linalg.norm(resampled[0] - resampled[-1]) > 1e-6
    assert np.all(np.linalg.norm(np.roll(resampled, -1, axis=0) - resampled, axis=1) > 1e-6)
