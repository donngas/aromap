# Airflow calibration investigation

Reproduce from `backend/`:

```sh
uv run --locked python -m scripts.calibrate_airflow
```

The script uses the actual prepared grid and transport operator. It advances a
uniform or point-release tracer with SciPy's matrix exponential, which removes
time-step error but is not the production backward-Euler integration. The
comparisons below are deliberately labeled: none establishes that the simulated
2D fragrance distribution predicts a measured 3D fragrance distribution.

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
