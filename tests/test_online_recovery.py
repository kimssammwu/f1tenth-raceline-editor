from __future__ import annotations

import numpy as np
import pytest

from f1tenth_raceline.online_recovery import (
    _adaptive_width_candidates,
    geometric_curvature_closed,
    normal_distances_to_bounds,
)


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


def test_normal_widths_measure_same_track_cross_section() -> None:
    theta = np.linspace(0.0, 2.0 * np.pi, 240, endpoint=False)
    center = np.column_stack((2.0 * np.cos(theta), 2.0 * np.sin(theta)))
    inner = np.column_stack((1.6 * np.cos(theta), 1.6 * np.sin(theta)))
    outer = np.column_stack((3.0 * np.cos(theta), 3.0 * np.sin(theta)))

    right, left = normal_distances_to_bounds(center, inner, outer)
    assert np.max(np.abs(right - 1.0)) < 1e-6
    assert np.max(np.abs(left - 0.4)) < 1e-6


def test_normal_widths_follow_reversed_driving_direction() -> None:
    theta = np.linspace(0.0, 2.0 * np.pi, 240, endpoint=False)
    center = np.column_stack((2.0 * np.cos(theta), 2.0 * np.sin(theta)))[::-1]
    inner = np.column_stack((1.6 * np.cos(theta), 1.6 * np.sin(theta)))
    outer = np.column_stack((3.0 * np.cos(theta), 3.0 * np.sin(theta)))

    right, left = normal_distances_to_bounds(center, inner, outer, reverse=True)
    assert np.max(np.abs(right - 0.4)) < 1e-6
    assert np.max(np.abs(left - 1.0)) < 1e-6
