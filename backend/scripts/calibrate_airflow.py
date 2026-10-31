"""Reproduce the limited comparisons in docs/airflow-calibration.md.

Run: uv run --locked python -m scripts.calibrate_airflow
The matrix exponential solves the semi-discrete operator without time-step error;
these approximations are not validation against 3D concentration measurements.
"""
import json
from dataclasses import replace
import numpy as np
from scipy.optimize import brentq
from scipy.sparse import eye
from scipy.sparse.linalg import expm_multiply
from app.simulations.engine.solver import transport_matrix
from app.simulations.limits import MIXING_PRESETS_M2_PER_S
from app.simulations.models import SimulationConfiguration
from app.simulations.preparation import prepare_run

# Cheng et al. Table 1; room 2 uses revised 0.00107, excluding 0.25 m monitors.
ROOM_1_K = [.00190, .00401, .00449, .00515, .00688]
ROOM_2_K = [.00107, .00463, .00223, .00197, .00684, .0129]


def prepared(width, height, *, cell=.25, window=False, cross=False, outdoor='calm', device=None, mixing=.0045, removal_ach=0):
    walls, windows, states = [], [], []
    if window:
        walls = [{'id': 'north', 'start': {'x': 0, 'y': 0}, 'end': {'x': width, 'y': 0}}]
        windows = [{'id': 'w', 'wall_id': 'north', 'start': {'x': width / 2 - .4, 'y': 0}, 'end': {'x': width / 2 + .4, 'y': 0}}]
        states = [{'opening_id': 'w', 'is_open': True}]
        if cross:
            walls.append({'id': 'south', 'start': {'x': 0, 'y': height}, 'end': {'x': width, 'y': height}})
            windows.append({'id': 'w2', 'wall_id': 'south', 'start': {'x': width / 2 - .4, 'y': height}, 'end': {'x': width / 2 + .4, 'y': height}})
            states.append({'opening_id': 'w2', 'is_open': True})
    request = {
        'geometry_m': {'indoor_domain': {'boundary': [{'x': 0, 'y': 0}, {'x': width, 'y': 0}, {'x': width, 'y': height}, {'x': 0, 'y': height}]}, 'walls': walls, 'windows': windows},
        'diffuser_definitions': [{'id': 'source', 'name': 'source', 'diffuser_type': 'test'}],
        'placements': [{'placement_id': 'source', 'definition_id': 'source', 'position_m': {'x': width / 2, 'y': height / 4}}],
        'opening_states': states, 'conditions': {'removal_rate_per_s': removal_ach / 3600},
        'settings': {'duration_s': 1800, 'sample_times_s': [1800], 'grid_cell_size_m': cell, 'effective_diffusivity_m2_per_s': mixing},
        'airflow': {'outdoor_conditions': outdoor, 'wind_direction_degrees': 90,
                    'devices': [] if device is None else [{'id': 'device', 'type': 'ac', 'position_m': {'x': width / 2, 'y': height / 2}, 'direction_degrees': 90, 'strength': device}]},
    }
    return prepare_run(SimulationConfiguration.model_validate(request), model_version='calibration-study')


def window_decay_ach(run, exchange_velocity):
    """30-minute room-mean equivalent decay with an initially uniform tracer."""
    widths = np.array([edge.length_m for edge in run.exterior_openings])
    field = replace(run.airflow_field, boundary_exchange=widths * exchange_velocity)
    operator = transport_matrix(replace(run, airflow_field=field))
    operator += eye(run.grid.active_cell_count) * run.input.parameters.removal_rate_per_s
    final = expm_multiply(-1800 * operator, np.ones(run.grid.active_cell_count))
    return float(-2 * np.log(final.mean()))


def window_comparisons():
    # Office E has volume 40 m³ and window width 0.8 m; 2.5 m height and
    # footprints below are assumptions, not reported experimental conditions.
    rows = []
    for width, height, cell in [(4, 4, .25), (4, 4, .125), (5, 3.2, .25), (3.2, 5, .25)]:
        run = prepared(width, height, cell=cell, window=True, removal_ach=.08)
        objective = lambda value: window_decay_ach(run, value) - 1.5
        fit = brentq(objective, 1e-7, .25) if objective(.25) > 0 else None
        rows.append({'assumed_width_m': width, 'assumed_depth_m': height, 'grid_m': cell,
                     'current_medium_decay_ach': window_decay_ach(run, .003),
                     'fitted_exchange_m_per_s': None if fit is None else float(fit)})
    return rows


def fan_comparisons():
    # LBNL room is 6.10 x 9.34 m with 3D HVAC/thermal effects. Use 6 x 9.25 m,
    # illustrative source and horizontal device; these do not replicate the study.
    values = {}
    for strength in (None, 'low', 'medium', 'high'):
        run = prepared(6, 9.25, device=strength)
        initial = np.zeros(run.grid.active_cell_count)
        initial[run.grid.source_weights[0].cell_indices] = 1
        states = expm_multiply(-transport_matrix(run), initial, start=0, stop=900, num=91)
        cv = states.std(axis=1) / states.mean(axis=1)
        below = np.flatnonzero(cv <= .2)
        values[strength or 'off'] = {'mixing_time_s': int(below[0] * 10) if len(below) else None,
                                     'cv_at_900s': float(cv[-1])}
    return values


def cross_window_comparisons():
    """One assumed layout; no claim about the experiment's unknown second opening."""
    values = {}
    for outdoor, exchange in [('calm', .001), ('moderate', .003), ('breezy', .006)]:
        run = prepared(4, 4, window=True, cross=True, outdoor=outdoor, removal_ach=.08)
        values[outdoor] = window_decay_ach(run, exchange)
    return values


def main():
    values = np.array(ROOM_1_K + ROOM_2_K)
    print(json.dumps({
        'cheng_k_m2_per_s': {'combined_quartiles': np.quantile(values, [.25, .5, .75]).tolist(),
                             'room_1_quartiles': np.quantile(ROOM_1_K, [.25, .5, .75]).tolist(),
                             'room_2_quartiles': np.quantile(ROOM_2_K, [.25, .5, .75]).tolist(),
                             'rounded_presets': MIXING_PRESETS_M2_PER_S},
        'office_window_sensitivity_not_validation': window_comparisons(),
        'assumed_opposite_windows_decay_ach_not_validation': cross_window_comparisons(),
        'lbl_room_fan_sensitivity_not_validation': fan_comparisons(),
    }, indent=2))


if __name__ == '__main__':
    main()
