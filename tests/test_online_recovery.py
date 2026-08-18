from __future__ import annotations

import numpy as np
import pytest

from f1tenth_raceline.online_recovery import _adaptive_width_candidates, geometric_curvature_closed


def test_geometric_curvature_closed_circle() -> None:
    radius = 2.0
    theta = np.linspace(0.0, 2.0 * np.pi, 200, endpoint=False)
    xy = np.column_stack((radius * np.cos(theta), radius * np.sin(theta)))
    kappa = geometric_curvature_closed(xy)
    assert np.all(np.isfinite(kappa))
    assert np.max(np.abs(np.abs(kappa) - 1.0 / radius)) < 1e-6


def test_geometric_curvature_rejects_invalid_shape() -> None:
    with pytest.raises(RuntimeError):
        geometric_curvature_closed(np.zeros((2, 2)))


def test_adaptive_width_candidates_consume_margin_only() -> None:
    values = _adaptive_width_candidates(0.4, 0.3)
    assert values == [0.375, 0.35, 0.325, 0.3]
    assert min(values) == 0.3


def test_adaptive_width_candidates_never_go_below_vehicle() -> None:
    assert _adaptive_width_candidates(0.3, 0.3) == []
    assert _adaptive_width_candidates(0.28, 0.3) == []
    values = _adaptive_width_candidates(0.34, 0.3)
    assert values[-1] == 0.3
    assert all(value >= 0.3 for value in values)
