# Aromap

Indoor scent-distribution simulator built for the **Sensation** hackathon.
Upload a floor plan, review its geometry and metric scale, then compare diffuser
placements, airflow devices, and opening states over time.

- **Frontend:** React/TypeScript; editable projects, local persistence, scenario comparison, and playback.
- **Backend:** FastAPI/OpenCV for floor-plan recognition; NumPy/SciPy for simulation; SQLite and local files for temporary jobs and results.
- **Model:** height-averaged 2D relative concentration. Outputs support scenario comparison, not measured fragrance concentration or perceived scent intensity.

## Run

From the repository root:

```sh
docker compose up --build
```

Open [the app](http://localhost:5173) or [API documentation](http://localhost:8000/docs).
Defaults require no credentials; [.env.example](.env.example) lists overrides.
For production-style staging, use Compose 2.24.4+ with
`docker compose -p aromap-staging -f compose.yaml -f compose.staging.yaml up --build`.

Backend tests, from `backend/`:

```sh
uv sync --locked
uv run --locked pytest -q
```

Run one backend process/replica with persistent writable storage at `AROMAP_DATA_DIR`
(`/data` in Compose). Jobs are interrupted on restart; temporary resources expire
in 24 hours by default. CI/image workflows are in [.github/workflows](.github/workflows).
See [backend documentation](backend/README.md) for API contracts and configuration.

## Simulation model

The equations below describe the implemented model. Established transport and
numerical methods are distinguished from project-specific approximations.
Preset selection and numerical checks are recorded in the
[calibration report](backend/docs/airflow-calibration.md) and
[sweep results](backend/docs/airflow-calibration-results.json).

Common notation: $C_i$ is relative concentration in cell $i$ (units/m²), $h$ is
cell width (m), $t$ is time (s), and $q$ is signed airflow per unit room height
(m²/s). One relative unit represents 1 mg of consumed formulation, not measured
fragrance chemical mass. Cells exchange scent only across represented connections;
closed walls block transport and open interior doors connect rooms.

### 1. Transport balance

```math
\frac{\partial C}{\partial t}
=D\nabla^2C-\nabla\cdot(\mathbf uC)+S-\lambda C
```

$D$ is effective diffusivity (m²/s), $\mathbf u$ airflow velocity (m/s), $S$
emission per area per second, and $\lambda$ background removal rate (s⁻¹).
Opening losses are boundary terms. The engine solves discrete cell balances.

**Code:** [`transport_matrix`, `source_rates`, `simulate`](backend/app/simulations/engine/solver.py).
**Basis:** conservation-based finite-volume transport [1].

### 2. Diffuser emission

```math
E=s\frac{M}{dH\,3600},\qquad M=1000\rho V,\qquad S_i=\frac{Ew_i}{h^2}
```

$E$ is relative emission per second; $M$ refill mass in mg; $d$ rated lifetime
in days; $H$ rated operating hours/day; $s$ explicit strength multiplier.
For volume input, $\rho$ is density in g/mL and $V$ volume in mL; gram input uses
$M=1000M_g$. Source weights $w_i$ sum to one. Reed diffusers use $H=24$;
emission is continuous while enabled. Missing/unsupported specifications fall
back to 1 g/day before strength adjustment; missing density defaults to 1 g/mL.

**Code:** [`resolve_emission`](backend/app/simulations/emissions.py),
[`source_rates`](backend/app/simulations/engine/solver.py).
**Basis:** product-consumption proxy. The conversion to airborne scent, fallback,
and default density are project assumptions, not experimentally validated emission laws.

### 3. Background mixing

```math
\dot C_i\big|_{\mathrm{mixing}}
=\sum_{j\sim i}\frac{D}{h^2}(C_j-C_i)
```

$j\sim i$ denotes connected neighbouring cells. Low/medium/high presets are
$D=0.002/0.0045/0.006$ m²/s; medium is the default. This represents unresolved
indoor mixing, not molecular diffusion alone.

**Code:** [`transport_matrix`](backend/app/simulations/engine/solver.py),
[presets](backend/app/simulations/limits.py).
**Basis:** finite-volume diffusion [1]; effective indoor diffusivity informed by
Cheng et al. [2]. Rounded presets are not room-specific validation.

### 4. Fan and recirculating A/C push

```math
q^*_{ij}=\sum_d U_d\exp\left(-\frac{r_d^2}{2\sigma_d^2}\right)
\left[(\mathbf x_j-\mathbf x_i)\cdot\hat{\mathbf d}_d\right]
```

For device $d$, $U_d$ is push strength, $\sigma_d$ influence radius,
$\hat{\mathbf d}_d$ its unit direction, and $r_d$ distance from the device to the
edge midpoint; $\mathbf x_i$ is the cell centre. Obstructed influence and Gaussian
weights at or below $10^{-4}$ are zeroed. Devices contribute additively before projection.

| Device | Low / medium / high $U_d$ (m/s) | $\sigma_d$ (m) |
| --- | --- | ---: |
| Fan | 0.08 / 0.16 / 0.28 | 1 |
| A/C | 0.10 / 0.20 / 0.35 | 1.5 |

**Code:** [`build_airflow`](backend/app/simulations/engine/airflow.py).
**Basis:** custom Gaussian surrogate and numerical preset sweeps. No direct physical
validation of this device model is claimed. A/C has no cooling or outdoor-air supply model.

### 5. Airflow projection

```math
q_{ij}=q^*_{ij}+\phi_i-\phi_j,\qquad
\sum_jq_{ij}+\sum_bq_{\mathrm{out},b}=0
```

$\phi_i$ is a correction potential (m²/s); $b$ indexes boundary pieces attached
to the cell. Potentials enforce local air balance. Internal square-face
conductance is face length / centre separation, equal to one.

**Code:** [`build_airflow`](backend/app/simulations/engine/airflow.py).
**Basis:** incompressibility projection principle [3]. This prescribed-field graph
projection does not solve the full Navier–Stokes equations or physical pressure.

### 6. Wind-driven exterior flow

```math
\phi_{\mathrm{outside}}=-A\hat{\mathbf d}_{\mathrm{wind}}\cdot\hat{\mathbf n},
\qquad
q_{\mathrm{out}}=\frac{w}{L+h/2}(\phi_i-\phi_{\mathrm{outside}})
```

$w$ is represented opening-piece width, $\hat{\mathbf n}$ the outward unit normal,
and $L$ an effective resistance length: 2 m for windows, 1 m for doors.
Calm/moderate/breezy amplitudes are $A=0/0.06/0.15$ m²/s. Wind direction is
**toward**, clockwise from image right: 0° right, 90° down. These amplitudes are
potentials, not outdoor wind speeds. Closed openings have no exterior flow.

**Code:** [`build_airflow`](backend/app/simulations/engine/airflow.py),
[`map_exterior_openings`](backend/app/simulations/engine/exterior.py).
**Basis:** custom resistance/potential boundary model. CONTAM [4] provides related
ventilation-model context; it does not establish this formula or its coefficients.

### 7. Opening exchange and removal

```math
q_{\mathrm{exchange}}=wv,\qquad
\dot C_i\big|_{\mathrm{opening}}
=-\frac{\sum_b[\max(q_{\mathrm{out},b},0)+q_{\mathrm{exchange},b}]}{h^2}C_i
```

$v$ is an effective two-way exchange velocity. Outdoor scent concentration is
zero; outgoing air removes scent. State is binary open/closed. Interior doors
connect cells without outdoor loss.

| Open type | Calm / moderate / breezy $v$ (m/s) |
| --- | --- |
| Window | 0.004 / 0.012 / 0.025 |
| Exterior door | 0.006 / 0.018 / 0.035 |

**Code:** [`build_airflow`](backend/app/simulations/engine/airflow.py),
[`transport_matrix`](backend/app/simulations/engine/solver.py).
**Basis:** airflow × concentration mass balance [4]; exchange velocities are project presets.

### 8. Airflow transport of scent

```math
F_{ij}=q_{ij}C_{\mathrm{upstream}},\qquad
\dot C_i=-F_{ij}/h^2,\quad \dot C_j=+F_{ij}/h^2
```

$F_{ij}$ is the signed scent transfer per second. The upstream cell follows the
sign of $q_{ij}$. Transfers conserve scent between cells.

**Code:** [`transport_matrix`](backend/app/simulations/engine/solver.py).
**Basis:** first-order upwind discretization [5]. It introduces numerical spreading,
which increases with coarser cells.

### 9. Background dilution

```math
\lambda=\mathrm{ACH}/3600,\qquad \dot C=-\lambda C,
\qquad C(t)=C_0e^{-\lambda t}
```

ACH is air changes per hour; $C_0$ is initial concentration. Default background
removal is 0.5 ACH and excludes explicitly modeled openings. The exponential is
the analytical reference; production integration uses backward Euler.

**Code:** [defaults](backend/app/simulations/limits.py),
[`simulate`](backend/app/simulations/engine/solver.py).
**Basis:** ventilation mass balance and tracer-gas decay [6]. The default is a
scenario value, not a universal ventilation rate.

### 10. Time integration

```math
[I+\Delta t(K+\lambda I)]C^{n+1}=C^n+\Delta tS
```

$K$ is the discrete transport/loss matrix, $I$ the identity, $n$ the step index,
and $\Delta t$ the integration step. Main steps are at most 2 s, with additional
transport accuracy caps. Startup intervals covering at least the first 2 s
(or the entire shorter run) use steps at most 0.125 s. Output sampling does not
select integration steps.

**Code:** [`simulate`](backend/app/simulations/engine/solver.py).
**Basis:** implicit backward-Euler finite-volume integration [1]. Specific timestep
caps are project accuracy policies, not physical constants.

### 11. Automatic spatial resolution

```math
N_* = \frac{10{,}000}{\sqrt{\max(1,P)}}
\min\left(1,\sqrt{\frac{3600}{T}}\right),\qquad
h_{\mathrm{desired}}=\sqrt{\frac{A_{\mathrm{bbox}}}{N_*}}
```

$P$ is source-channel count, $T$ duration in seconds, and $A_{\mathrm{bbox}}$
bounding-box area in m². Resource limits further constrain $N_*$. Width rounds
upward in 0.05 m increments from the default 0.25 m base to 1 m; geometry
safeguards can refine it. Explicit `settings.grid_cell_size_m` overrides selection.

**Code:** [`automatic_cell_size`, `protect_features`](backend/app/simulations/resolution.py),
[`prepare_run`](backend/app/simulations/preparation.py).
**Basis:** project workload heuristic, not a scientific scaling law.

### 12. Coverage and colour

```math
\mathrm{Coverage}=100\frac{N_{\mathrm{reached}}}{N_{\mathrm{active}}},\qquad
\ell=\frac{\ln(1+40C/C_{\max})}{\ln41}
```

$N_{\mathrm{active}}$ counts indoor cells; $N_{\mathrm{reached}}$ counts those
with $\sum_p C_{p,i} \ge 1$ at the selected time. $p$ indexes diffuser channels.
For colour level $\ell$, $C$ is the selected-channel sum
and $C_{\max}$ its maximum across the run. Values below the coverage threshold
can remain visible; each run has its own colour normalization.

**Code:** [`coverageAt`](frontend/src/simulation/analysis.ts),
[`fieldMax`, `renderFrame`](frontend/src/simulation/heatmap.ts).
**Basis:** project display definitions. Neither the threshold nor log scale models
human scent perception.

## References

1. NIST, [FiPy: Finite Volume Method](https://pages.nist.gov/fipy/en/stable/numerical/discret.html) — transient, diffusion, convection, and source discretization.
2. Cheng et al. (2011), [Modeling Exposure Close to Air Pollution Sources in Naturally Ventilated Residences](https://doi.org/10.1021/es103080p), *Environmental Science & Technology*, 45, 4016–4022 — effective indoor turbulent diffusivity.
3. Chorin (1968), [Numerical Solution of the Navier–Stokes Equations](https://doi.org/10.1090/S0025-5718-1968-0242392-2), *Mathematics of Computation*, 22, 745–762 — incompressibility projection.
4. Dols and Polidoro (2020), [CONTAM User Guide and Program Documentation, Version 3.4](https://doi.org/10.6028/NIST.TN.1887r1), NIST Technical Note 1887 Revision 1 — airflow and contaminant mass-balance modeling.
5. NIST, [FiPy: Numerical Schemes](https://pages.nist.gov/fipy/en/stable/numerical/scheme.html) — upwind discretization and numerical diffusion.
6. ASHRAE, [Handbook—Fundamentals, Chapter 16: Ventilation and Infiltration](https://handbook.ashrae.org/Handbooks/F17/IP/f17_ch16/f17_ch16_ip.aspx) — air-change rates and tracer-gas decay.
