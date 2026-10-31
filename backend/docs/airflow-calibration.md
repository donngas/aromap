# Airflow calibration and automatic resolution

## Current demo presets — 2026-11-01

This section supersedes the historical investigation below. Solver version is
`square-balance-airflow-v5`; preparation version is `square-center-grid-v4`.
The scope is the backend engine and API. Opening state remains binary. Values
are engineering scenario calibration for a hackathon demo, not experimental
validation or predictions of perceived fragrance.

Reproduce from `backend/`:

```sh
uv run --locked python -m scripts.calibrate_presets > docs/airflow-calibration-results.json
uv run --locked pytest -q
uv run --locked python -m scripts.benchmark_simulation --case apartment --cell-size .25 --max-step .25
uv run --locked python -m scripts.benchmark_simulation --case apartment
```

The checked-in JSON records the sweep outcomes. Runtime varies by machine.
The sweep uses the real prepared cell graph and transport operator. Matrix
exponentials isolate spatial/model effects from timestep error; separate tests
use the production backward-Euler solver. No previewer is used in calibration.

### Opening coefficients and repaired projection

| Binary open type | Calm exchange | Moderate exchange | Breezy/strong exchange | Resistance length |
| --- | ---: | ---: | ---: | ---: |
| Window | 0.004 m/s | 0.012 m/s | 0.025 m/s | 2 m |
| Exterior door | 0.006 m/s | 0.018 m/s | 0.035 m/s | 1 m |

Exchange is per unit room height: `q_exchange = represented_width * coefficient`
in m²/s. The constants fold assumed aperture-height and fluctuation differences
into type-specific effective values; actual opening height is not requested.
Closed openings contribute neither exchange nor exterior flow. Interior open
doors connect rooms and do not use these outdoor exchange coefficients.

Wind potential amplitudes are **0 / 0.06 / 0.15 m²/s** for calm/moderate/breezy.
They are potentials, not outdoor wind speeds. The API labels remain unchanged.
Angles specify the direction air travels toward: 0° right, 90° down. Opening
potential is `-amplitude * dot(wind_direction, outward_normal)`.

The old internal projection conductance was `h`, while boundary conductance was
opening width. Refinement therefore changed the room's resistance relative to
its openings. The new potential has units m²/s; internal square-face conductance
is face length / center separation = 1. Boundary conductance is
`opening_piece_width / (type_resistance_length + h/2)`, including the physical
half-cell distance. Thus `q_internal = q_prescribed + phi_i - phi_j` and
`q_out = conductance * (phi_i - phi_external)`. This is a Darcy-like idealization,
not calibrated pressure or CFD. Device-only projection is unchanged by the
common rescaling of internal conductance. Exterior classification now uses a
fixed 0.375 m recognition tolerance instead of a grid-dependent tolerance.

Calibration sequence and decisions:

1. Freeze background mixing at 0.0045 m²/s and background removal at 0.5 ACH.
   Use a uniform tracer, no emission, 4 × 4 m room, one centered 0.8 m opening.
   Compute `-2*ln(M(1800)/M(0))` for a 30-minute equivalent ACH.
2. Sweep half, baseline and double exchange for all three settings and both
   types (18 cases). Choose calm values near 1 ACH total, then moderate and
   strong values with progressively greater removal. Do not force a 3/6 ACH
   single-opening target by excessively increasing the local sink: the model
   becomes limited by room-to-opening transport.
3. Add an opposite opening, sweep wind amplitudes at half/baseline/double for
   moderate and strong conditions and both types (12 cases). Keep the middle
   values: weaker candidates gave less cross-flow separation; doubling strong
   wind produced 49 ACH window and 84 ACH door equivalent decay in this small
   reference room, excessive for the intended middle-of-range demo scenario.
4. Review 4 × 4, 6 × 6 and 8 × 4 m rooms at 0.125/0.25/0.5 m grids for both
   types (18 cases). Test wind reversal, parallel wind and local air balance.
   These cases test transfer/sensitivity, not independent physical validation.

Selected single-opening equivalent ACH, including background removal:

| Type | Calm | Moderate | Breezy/strong |
| --- | ---: | ---: | ---: |
| Window | 1.011 | 1.464 | 1.755 |
| Exterior door | 1.168 | 1.632 | 1.866 |

For example, doubling moderate window exchange changes 1.464 to 1.741 ACH;
doubling strong window exchange changes 1.755 to 1.966 ACH. The diminishing
returns are why the baseline values were retained. In the opposite-opening
4 × 4 m case, moderate/strong decay is 6.994/20.333 ACH for windows and
11.518/36.162 ACH for doors. These are finite-time decay equivalents, not
instantaneous ventilation rates. Cross-flow can flush a room faster than a
well-mixed interpretation of the total volume flow would suggest.

The repaired 6 × 6 m moderate opposite-window flow is
1.697/1.682/1.655 ACH at 0.125/0.25/0.5 m. The old values were
0.227/0.412/0.695 ACH. Remaining raster error is small but not zero. Across the
three shapes and two types, flow changes by less than 5% from 0.125 to 0.5 m.
Concentration and pulse shape remain more grid-sensitive than total air flow.
For a single opening, the additional 18 grid checks show residual transport
error: strong-window decay is 1.686/1.755/1.895 ACH and strong-door decay is
1.785/1.866/2.025 ACH at 0.125/0.25/0.5 m. This roughly 12–13% spread across
the full range is acceptable for the demo, but is not grid-independent local
concentration calibration.

### Fan and recirculating A/C presets

| Type | Low push | Medium push | High push | Gaussian radius |
| --- | ---: | ---: | ---: | ---: |
| Fan | 0.08 m/s | 0.16 m/s | 0.28 m/s | 1 m |
| A/C | 0.10 m/s | 0.20 m/s | 0.35 m/s | 1.5 m |

These are prescribed push coefficients, not outlet specifications or guaranteed
room velocities. Projection supplies balanced return flow. A/C remains a
recirculating device: no thermal effects, outdoor supply, filtration or scent
removal. Device count, placement, direction and walls still affect the result.

Use a 6 × 6 m closed room, point pulse at (3, 1.5), central device at (3, 3)
pointing down, no background removal, and the same mixing coefficient. Measure
roomwide coefficient of variation every 10 s; mixing time is the first time CV
is at most 0.2. Sweep half/baseline/double push for all settings and both types
(18 cases). Selected results:

| Type | Low mixing time | Medium mixing time | High mixing time | Maximum velocity low/medium/high |
| --- | ---: | ---: | ---: | --- |
| Fan | 460 s | 300 s | 200 s | 0.032 / 0.064 / 0.112 m/s |
| A/C | 450 s | 350 s | 240 s | 0.034 / 0.069 / 0.120 m/s |

The baseline gives useful separation in several-minute demo scenarios. Half
strength can mix too slowly; double high strength gives a smaller additional
benefit while increasing solve cost and numerical spreading. Mixing time is not
universally monotonic in speed because steady recirculation can trap a plume.
A/C need not beat a fan in every layout merely because its influence is broader.

Separately sweep radius at 0.75×/1×/1.5× in a square and two off-center rectangular
cases (18 cases). No radius wins everywhere, so retain the existing physical
radii instead of tuning geometry to one pulse. In the 8 × 4 m off-center cases,
selected medium-device CV at 900 s ranges approximately 0.13–0.26. A weakly
connected far region therefore remains less mixed than the central square room.
Closed-room pulse mass is conserved to numerical precision in all these cases.

### Automatic grid and temporal policy

Explicit `settings.grid_cell_size_m` still wins, with the existing 0.1–1 m
validation. Otherwise start at the caller's base (normally 0.25 m), and choose
from 0.05 m increments up to 1 m. The workload target is

`target_cells = 6000 / sqrt(max(1, channels)) * min(1, sqrt(3600 / duration_s))`.

Also constrain the target by the configured cell and dense-output byte limits.
Choose `h >= sqrt(bounding_box_area / target_cells)`. Bounding-box area is used
because stored arrays include inactive cells. Small rooms retain the baseline;
larger/longer/multi-channel cases gradually coarsen. This is a quality/work
heuristic, not a guaranteed runtime limit.

Safeguards cap coarsening to roughly two cells across each open aperture, avoid
new changes in eroded footprint component count relative to the baseline, and
refine automatically if a source, device or exterior opening cannot map, or an
interior open door loses all represented connections after exterior classification. The baseline is a floor: pre-existing sub-cell geometry is reported
with existing warnings/errors. Quality restrictions take priority over hitting
the target cell count; existing memory/runtime limits still apply. Explicit
resolution is recommended when comparing experiments or continuing stored state;
state migration between grids is not introduced.

Physical D, emission and removal coefficients are unchanged. Existing `D/h²`,
source/h², flux/h² and integrated quantity×h² conversions remain authoritative.
Coarsening still increases first-order upwind numerical diffusion and changes
near-source cell peaks. It should be treated as demo quality, with explicit fine
resolution available for detailed analysis. The sweep records a separate fixed
physical-probe spatial comparison away from the point source.

Internal backward-Euler maximum step is now **2 s**, additionally limited by
`duration/4`, `0.25*h²/D`, `0.05/removal`, `0.2*h/max_edge_velocity`, and
`0.25/max_cell_opening_loss`. Opening loss is aggregated per cell, including
multiple opening pieces. These are accuracy limits, not stability requirements.
The stricter 0.2 advection cap was selected after the initial 0.5 cap failed the
existing <1% timestep refinement test at the stronger fan presets. `duration/4`
preserves short-run accuracy. Additionally, the first main intervals covering at
least two seconds (or the entire shorter run) use substeps no larger than
0.125 s. This fixes the missed early-time error in longer runs: the original
2 s main step produced 29.3% error at t=1 s in a 60 s point-source run; the
reviewed policy produces 1.36% against a 0.015625 s reference. Startup and main
stages use at most two LU factorizations, released sequentially, and the step
budget includes both. Output sampling remains independent of integration.

The JSON includes 0.25/1/2/5 s maximum-step comparisons with a 0.125 s production
reference. Fast flows automatically select smaller steps. No endpoint or new
required request field is introduced. Resolved grid assumptions and solver
step/count diagnostics expose the policy; solver/preparation versions changed.

### Performance and spatial quality check

On this development machine, the existing apartment benchmark (20 × 15 m,
four channels, one simulated hour, 121 snapshots, no airflow) changed from
**8.005 s to 0.533 s** solver time when moving from explicit 0.25 m / 0.25 s
to automatic 0.35 m / 2 s: about **15.0× faster** in this run. Cells decreased
from 4800 to 2451 and sampled field size from 8.86 to 4.60 MiB. This measures
both temporal and spatial changes, not either optimization alone. Airflow-heavy
cases will have smaller speedups because their accuracy caps shorten the step.

A separate 30 × 30 m point-source test samples fixed physical probes at 60,
300 and 600 s, excluding the nearest 1 m around the source. Relative probe L1
differences versus 0.25 m cells are **17.8% at 0.4 m** and **12.9% at 0.5 m**;
integrated mass differs by less than 2e-8 relative. Error is not monotonic in
cell width because source position relative to cell centers changes. These
results support coarse grids for an approximate demo, not claims of invariant
local concentration. Use explicit 0.25 m or finer for detailed comparisons.

In the production 300 s high-A/C check, the default policy selects a 0.417 s
main step and differs by 0.113% aggregate field L1 from a 0.125 s reference.
Strong opposite-window flow selects a 0.647 s main step and differs by 0.137%.
Both include startup substeps; snapshot times are 1, 60 and 300 s. These specific errors are not universal bounds.

### Follow-up review

The review also corrected two automatic-resolution gaps: exterior doors were
being checked as interior connections before classification (unnecessarily
forcing baseline resolution), and device/exterior-opening mapping failures were
outside the retry loop. Candidate grids are now fully classified and checked
before acceptance, with budgets recalculated at each refinement. Explicit grid
requests still fail rather than silently changing resolution. Physically invalid
devices retain `invalid_airflow_device`; a valid device unresolved by a requested
grid reports `unresolved_airflow_device`.

Gaussian influence at or below the visibility-ray cutoff is now zeroed before
wall filtering. Previously those untested tails could drive tiny velocities in a
disconnected room; the closed-wall regression test now covers this distant case.

The refreshed JSON adds off/fan/A/C/both-aligned/both-opposed pulse checks in a
6 × 6 m room, with medium devices at (2,3) and (4,3). At 900 s the corresponding
CVs are approximately 0.310/0.014/0.019/0.012/0.002; all conserve pulse mass.
Device interaction depends on location and direction, so this does not establish
that two devices always mix faster. The selected opening and device coefficients
are retained. Artifact metadata records solver and preparation versions.

## Historical investigation before v4

The remainder records the earlier literature review and old numerical outcomes.
Its preset numbers and timings are historical, not the current defaults. The
old `scripts.calibrate_airflow` remains a literature-sensitivity helper, but uses
the current engine when run today; it does not recreate the old implementation.

## Background mixing: empirical estimates, not direct 2D validation

[Cheng et al. (2011), Table 1](https://web.stanford.edu/~fringer/publications/cheng-etal-est-2011.pdf)
reported 11 effective diffusivities estimated from 30-minute CO concentrations
in two naturally ventilated California residences. We use the paper's revised
0.00107 m²/s estimate for its anomalous room-2 case (their original fit was
0.00260). The sample quartiles using NumPy linear interpolation are:

| Sample | 25th / median / 75th percentile (m²/s) |
| --- | --- |
| All 11 runs | 0.00210 / 0.00449 / 0.005995 |
| Room 1, five runs | 0.00401 / 0.00449 / 0.00515 |
| Room 2, six runs | 0.002035 / 0.00343 / 0.006288 |

The rounded low/medium/high presets are **0.002 / 0.0045 / 0.006 m²/s**;
the default is medium. These describe the middle of this limited dataset, not
its full measured range (approximately 0.001–0.013 m²/s), confidence bounds,
or measured local values. Room-specific quartiles above are a sensitivity
comparison, not independent validation: the combined presets include both rooms.
The source was a 3D point source and sensors were at one height; Aromap is
height-averaged 2D. The estimates cover total unresolved natural mixing and do
not independently identify the residual when an explicit fan field is modeled.
Values therefore remain literature-informed engineering scenarios, not validated
calibration of the 2D engine, and should not be added to a claim of measured
product performance. The study found natural mixing and air exchange correlated;
independent UI controls should not be interpreted as statistically independent.

## Background fresh-air exchange

Keep the existing 0.5 air changes per hour (ACH) default. [Howard-Reed et al.
(2002)](https://www.tandfonline.com/doi/abs/10.1080/10473289.2002.10470775)
reported mean closed-window whole-house rates of 0.37 and 0.41 ACH in two homes;
[ASHRAE](https://handbook.ashrae.org/handbooks/f17/si/F17_Ch16/f17_ch16_si.aspx)
reports a 0.5 ACH median in a sample of 312 houses. Neither describes all rooms
or conditions. This parameter represents exchange **not already represented by
modeled openings**. No room-specific calibration or commercial-space default is
claimed.

## Window: sensitivity check against an independent tracer study

[Heidt et al., office E](https://www.intechopen.com/chapters/16332) reports a
40 m³ office, 0.8 m window width, median closed-window 0.08 ACH and median
1.5 ACH for a tilted window. The observed tilted-window range was 0.5–3.4 ACH;
a widely opened window had median 10 ACH. The article does not give all
geometry, environmental conditions, or effective opening area needed by the
engine. We assume a 2.5 m room height (16 m² footprint), an initially uniform
tracer, 0.08 ACH background removal, 0.0045 m²/s mixing, one window, no other
wind-driven net flow, and estimate the decay over 30 minutes. A 30-minute
room-mean decay is only an approximation to the measurements, whose durations
varied and whose concentration-decay fitting methods were not replicated.

| Assumed footprint, grid | Current medium exchange: equivalent ACH | Exchange velocity fitted to 1.5 ACH (m/s) |
| --- | ---: | ---: |
| 4 × 4 m, 25 cm | 0.493 | 0.0421 |
| 4 × 4 m, 12.5 cm | 0.486 | 0.0628 |
| 5 × 3.2 m, 25 cm | 0.492 | 0.0356 |
| 3.2 × 5 m, 25 cm | 0.477 | 0.1271 |

These are shape/grid **sensitivity calculations**, not held-out validation: the
same 1.5 ACH target is fitted repeatedly and the true footprint is unknown. The
large change in fitted velocity exposes a model-resolution and identifiability
problem; tuning one value to this case would not yield a transferable preset.
Also, a binary open state cannot distinguish the measured tilted and wide-open
conditions. Consequently the existing calm/moderate/breezy exchange velocities
0.001/0.003/0.006 m/s remain **uncalibrated**; this example suggests they can
underestimate exchange in some cases. Wind-potential values 0/0.02/0.05 m/s
likewise remain uncalibrated, and cannot be equated to outdoor wind speeds.

For another sensitivity check, the script adds an assumed opposite 0.8 m
opening to the assumed 4 × 4 m room. Its 30-minute equivalent decays for
calm/moderate/breezy presets are 0.414/1.848/4.130 ACH. The cited office study
reported a 40 ACH median for fully open cross-ventilation, but its second
opening's geometry and weather are not reproduced here. These figures show
sensitivity and a possible underestimation risk, not a matched validation or
a basis for adjusting wind coefficients.

## Fan/A/C: qualitative sensitivity, not an empirical fit

[LBNL's 2025 158 m³ room study](https://eta-publications.lbl.gov/sites/default/files/2026-03/demonstration_of_a_novel_tracer_gas_method.pdf)
measured whole-room tracer mixing times of 174 and 206 s with high neutral
supply air and 451 and 532 s with lower heated supply. Its ventilation uses two
ceiling supply diffusers, return ducts and thermal plumes, with 3D sensor levels;
it is not the simulated 2D horizontal recirculating-device model used for fans and
A/C. The script merely
explores a similarly sized 6 × 9.25 m room, a point pulse, no removal, a central
horizontal device and roomwide 20% coefficient-of-variation threshold. The
analogous results are: off and low >900 s, medium 600 s, high 570 s. Sensor
locations, pulse, geometry and vertical flows differ, so these are **not a
comparison of matched experiments**, not a fit, and not evidence that the devices
predict the LBNL mixing times. The model cannot identify a device's push and
radius from these aggregate times. Each placed device contributes its own field.
Fan and A/C use the same strength-to-speed presets (0.025/0.05/0.1 m/s), while
the fan radius is 1 m and the A/C radius is 1.5 m. These per-type settings remain
**uncalibrated**.

A potential future fan benchmark is [Estaquio et al. (2026)](https://doi.org/10.3390/fluids11040090):
they report a 2 × 3 × 2.5 m room and ten velocity probes with a pedestal fan.
The authors state that raw data are available on request. Those measurements
are at one height, not height averages; their particulate measurements also
cannot directly validate fragrance vapor behavior.

## What would support a defensible fit

Acquire time-resolved, multi-location data with plan geometry, opening dimensions,
height, wind and indoor/outdoor temperatures, fan location/direction, flow rates,
background air exchange, and source schedule. Fit residual mixing, device and
opening parameters on distinct controlled cases, accounting for numerical
resolution and non-identifiability; then assess arrival times, concentrations and
decay on separate held-out geometries/conditions. If the 2D model cannot match
such cases across grids, improve the model before fitting constants. The model's
outputs remain relative formulation consumption proxies, not measured fragrance
concentration or perceived scent.
