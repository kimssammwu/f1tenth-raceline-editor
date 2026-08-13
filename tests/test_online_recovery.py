from __future__ import annotations

import numpy as np
import pytest

from f1tenth_raceline.online_recovery import geometric_curvature_closed


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
