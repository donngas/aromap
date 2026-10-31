"""Numerical engineering calibration sweep; run uv run --locked python -m scripts.calibrate_presets.

Uniform tracer decay, pulse mixing, grid sensitivity and production timestep
checks. These are scenario acceptance checks, not measured-room validation.
"""
import json
from dataclasses import replace
from time import perf_counter
import numpy as np
from scipy.sparse import eye
from scipy.sparse.linalg import expm_multiply
from scipy.ndimage import map_coordinates
from scripts.calibrate_airflow import prepared
from app.simulations.engine.airflow import build_airflow, OPENING_EXCHANGE_M_PER_S, DEVICE_SPEEDS, DEVICE_RADII_M
from app.simulations.engine.solver import transport_matrix, simulate, SolverOptions, SOLVER_VERSION
from app.simulations.models import MetricPoint
from app.simulations.preparation import PREPARATION_VERSION


def opening_run(width=4, depth=4, *, cell=.25, kind='window', cross=False, outdoor='calm', angle=90):
    run = prepared(width, depth, cell=cell, window=True, cross=cross, outdoor=outdoor, removal_ach=.5)
    boundary = tuple(replace(e, kind=kind) for e in run.exterior_openings)
    settings = run.input.airflow.model_copy(update={'wind_direction_degrees': angle})
    field = build_airflow(run.grid, settings, boundary, run.input.geometry)
    return replace(run, exterior_openings=boundary, airflow_field=field)


def decay(run):
    operator = transport_matrix(run) + eye(run.grid.active_cell_count) * run.input.parameters.removal_rate_per_s
    state = expm_multiply(-1800 * operator, np.ones(run.grid.active_cell_count))
    return float(-2 * np.log(state.mean()))


def main():
    results = {'versions': {'solver':SOLVER_VERSION,'preparation':PREPARATION_VERSION},
               'opening_sweep': [], 'device_sweep': [], 'wind_sweep': [],
               'device_geometry_checks': [], 'grid_checks': [], 'single_opening_grid_checks': [],
               'time_checks': [], 'resolution_checks': [], 'device_combination_checks': []}
    for kind in ('window', 'door'):
        for outdoor in ('calm', 'moderate', 'breezy'):
            run = opening_run(kind=kind, outdoor=outdoor)
            for multiplier in (.5, 1., 2.):
                field = replace(run.airflow_field, boundary_exchange=run.airflow_field.boundary_exchange * multiplier)
                results['opening_sweep'].append(dict(kind=kind, outdoor=outdoor, multiplier=multiplier,
                    exchange_m_per_s=OPENING_EXCHANGE_M_PER_S[kind][outdoor]*multiplier,
                    decay_ach=decay(replace(run, airflow_field=field))))
    for kind in ('window', 'door'):
        for outdoor in ('moderate', 'breezy'):
            for multiplier in (.5, 1., 2.):
                run = opening_run(kind=kind, cross=True, outdoor=outdoor)
                field = replace(run.airflow_field, edge_flux=run.airflow_field.edge_flux * multiplier,
                                boundary_outflow=run.airflow_field.boundary_outflow * multiplier)
                results['wind_sweep'].append(dict(kind=kind, outdoor=outdoor, multiplier=multiplier,
                    decay_ach=decay(replace(run, airflow_field=field))))
    for kind in ('fan', 'ac'):
        for strength in ('low', 'medium', 'high'):
            for multiplier in (.5, 1., 2.):
                run = prepared(6, 6, device=strength)
                device = run.input.airflow.devices[0].model_copy(update={'type': kind})
                settings = run.input.airflow.model_copy(update={'devices': [device]})
                field = build_airflow(run.grid, settings, (), run.input.geometry)
                field = replace(field, edge_flux=field.edge_flux * multiplier)
                run = replace(run, airflow_field=field)
                initial = np.zeros(run.grid.active_cell_count)
                initial[run.grid.source_weights[0].cell_indices] = 1.
                states = expm_multiply(-transport_matrix(run), initial, start=0, stop=900, num=91)
                cv = states.std(axis=1) / states.mean(axis=1)
                mixed = np.flatnonzero(cv <= .2)
                results['device_sweep'].append(dict(kind=kind, strength=strength, multiplier=multiplier,
                    push_m_per_s=DEVICE_SPEEDS[kind][strength]*multiplier,
                    max_velocity_m_per_s=float(np.max(np.abs(field.edge_flux))/run.grid.cell_size_m),
                    cv_300s=float(cv[30]), cv_900s=float(cv[-1]),
                    mixing_time_s=int(mixed[0]*10) if len(mixed) else None))
    # Check the selected presets beyond the central square-room fit. Radius
    # sweeps assess shape separately from speed; restore globals immediately.
    for kind in ('fan', 'ac'):
        for width, depth, x, y, angle in ((6,6,3,3,90),(8,4,2,2,0),(8,4,1,1,45)):
            for radius_multiplier in (.75, 1., 1.5):
                run = prepared(width,depth,device='medium')
                device = run.input.airflow.devices[0].model_copy(update={
                    'type':kind,'position_m':MetricPoint(x=x,y=y),'direction_degrees':angle})
                settings = run.input.airflow.model_copy(update={'devices':[device]})
                original = DEVICE_RADII_M[kind]
                try:
                    DEVICE_RADII_M[kind] = original * radius_multiplier
                    field = build_airflow(run.grid,settings,(),run.input.geometry)
                finally:
                    DEVICE_RADII_M[kind] = original
                run = replace(run,airflow_field=field)
                pulse = np.zeros(run.grid.active_cell_count)
                pulse[run.grid.source_weights[0].cell_indices] = 1
                final = expm_multiply(-900 * transport_matrix(run),pulse)
                results['device_geometry_checks'].append(dict(kind=kind,width=width,depth=depth,
                    x=x,y=y,angle=angle,radius_multiplier=radius_multiplier,
                    cv_900s=float(final.std()/final.mean()),
                    mass_ratio=float(final.sum()/pulse.sum())))
    for width, depth in ((4,4),(6,6),(8,4)):
        for cell in (.125,.25,.5):
            for kind in ('window','door'):
                run = opening_run(width,depth,cell=cell,kind=kind,cross=True,outdoor='moderate')
                results['grid_checks'].append(dict(width=width,depth=depth,cell=cell,kind=kind,
                    flow_ach=float(3600*np.maximum(run.airflow_field.boundary_outflow,0).sum()/(run.grid.active_cell_count*cell**2)),
                    decay_ach=decay(run)))
    for case in ('off','fan','ac','both_aligned','both_opposed'):
        run = prepared(6,6,device='medium')
        template = run.input.airflow.devices[0]
        devices = []
        if case in ('fan','both_aligned','both_opposed'):
            devices.append(template.model_copy(update={'id':'f','type':'fan','position_m':MetricPoint(x=2,y=3)}))
        if case in ('ac','both_aligned','both_opposed'):
            devices.append(template.model_copy(update={'id':'a','type':'ac','position_m':MetricPoint(x=4,y=3),
                'direction_degrees':270 if case=='both_opposed' else 90}))
        field = build_airflow(run.grid, run.input.airflow.model_copy(update={'devices':devices}), (), run.input.geometry)
        run = replace(run,airflow_field=field)
        pulse = np.zeros(run.grid.active_cell_count)
        pulse[run.grid.source_weights[0].cell_indices] = 1
        final = expm_multiply(-900 * transport_matrix(run),pulse)
        results['device_combination_checks'].append(dict(case=case,cv_900s=float(final.std()/final.mean()),
            mass_ratio=float(final.sum()/pulse.sum())))
    for kind in ('window','door'):
        for cell in (.125,.25,.5):
            for outdoor in ('calm','moderate','breezy'):
                run = opening_run(cell=cell,kind=kind,outdoor=outdoor)
                results['single_opening_grid_checks'].append(dict(kind=kind,cell=cell,outdoor=outdoor,decay_ach=decay(run)))
    for case in ('device','opening'):
        run = prepared(6,6,device='high') if case=='device' else opening_run(cross=True,outdoor='breezy')
        run = replace(run,input=run.input.model_copy(update={'duration_s':300.,'sample_times_s':[1.,60.,300.]}))
        reference = simulate(run,SolverOptions(max_step_s=.125)).concentration
        for dt in (.25,1.,2.,5.):
            start=perf_counter(); output=simulate(run,SolverOptions(max_step_s=dt)); elapsed=perf_counter()-start
            results['time_checks'].append(dict(case=case,max_step_s=dt,runtime_s=elapsed,
                relative_l1=float(np.abs(output.concentration-reference).sum()/reference.sum()),
                early_relative_l1=float(np.abs(output.concentration[0]-reference[0]).sum()/reference[0].sum()),
                diagnostics=output.diagnostics[0]))
    # Separate spatial quality from timing: identical physical probes on grids,
    # away from the point source where cell averaging changes the local peak.
    for cell in (.25, .4, .5):
        run = prepared(30,30,cell=cell)
        run = replace(run,input=run.input.model_copy(update={'duration_s':600.,'sample_times_s':[60.,300.,600.]}))
        output = simulate(run)
        x,y = np.meshgrid(np.arange(1.,30.,1.),np.arange(1.,30.,1.))
        keep = (x-15)**2 + (y-7.5)**2 >= 1.
        probes = np.array([map_coordinates(frame[0],np.array([y[keep]/cell-.5,x[keep]/cell-.5]),order=1)
                           for frame in output.concentration])
        mass = output.concentration.sum(axis=(1,2,3),dtype=np.float64)*cell**2
        if cell == .25:
            reference_probes,reference_mass = probes,mass
        results['resolution_checks'].append(dict(cell=cell,
            probe_relative_l1=float(np.abs(probes-reference_probes).sum()/reference_probes.sum()),
            mass_relative_l1=float(np.abs(mass-reference_mass).sum()/reference_mass.sum())))
    print(json.dumps(results,indent=2))


if __name__ == '__main__':
    main()
