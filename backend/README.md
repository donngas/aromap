# Aromap backend

FastAPI processes operation-specific inputs. The browser owns editable projects,
local persistence, save-format versions, and JSON export/import. There is no backend
`ProjectDocument` or project CRUD API. SQLite tracks temporary uploads and jobs;
images and recognition results live on the same local volume.

## Browser data ownership (planning direction)

The frontend should persist editable work and prepared image Blobs locally
(IndexedDB is the suggested store), separately from temporary backend image/job
handles and cached results. Pixel geometry and user-entered calibration remain
the editing source of truth; FE can derive metric geometry when submitting work.
Exports should remain usable after backend resources expire.

Each operation receives only its relevant context: recognition uses an uploaded
image ID; future simulation/advice requests carry the selected configuration and
any needed result context, rather than the entire saved project. FE should associate
results with submitted snapshots to avoid applying stale results after edits.
The suggested logical save shape is frontend-owned, not a backend DTO:

```text
Project (schema_version, id, name)
  floor_plan
    prepared_image                   Blob locally, embedded for export
    geometry_px                      dimensions, walls, doors, windows, labels, indoor domain
    calibration                      pixel reference + known length in meters
  diffuser_definitions[]              consumer specifications and provenance
  scenarios[]
    id, name
    placements[]                     ID, definition ID, pixel position, overrides
    opening_states[]
    environmental settings
    simulation settings
  active_scenario_id
```

Backend handles, pending jobs, result arrays, and their submitted snapshots belong
to a separate runtime/cache store. They are not required in portable exports.
Keep pixel geometry/calibration authoritative; derive meters for each request.
Save-format details and advice DTOs remain open. The simulation HTTP contract is
defined below, with numerical defaults and artifact encoding still provisional.

## Run

From `backend/`:

```sh
uv sync --locked
uv run uvicorn app.main:app --reload
uv run pytest -q
```

Use **one API process**. The local queue is not shared across API replicas/workers.
Recognition and simulation share one dispatcher, with up to four waiting jobs.
Each job runs in a spawned child process.
The backend service can also run from the repository root:

```sh
docker compose up --build backend
```

The default Compose target installs development dependencies and enables reload
for mounted `app/` source. Run tests in that environment with:

```sh
docker compose run --rm --no-deps backend uv run --locked pytest -q
```

For production-style staging without reload, development dependencies, or source
mounts:

```sh
docker compose -p aromap-staging -f compose.yaml -f compose.staging.yaml up --build backend
```

Both modes publish `${BACKEND_PORT:-8000}` on `${HOST_BIND:-127.0.0.1}`. Swagger
remains directly accessible on that host port. `/health` returns `{"status":"ok"}`
after initialization and checks SQLite connectivity. Startup validates the configured
recognizer import; `/health` does not run recognition. Compose uses this endpoint
for backend readiness.

Compose mounts `backend-data` at `/data`, retaining SQLite and files across container
recreation. Staging's separate project name gives it a separate volume. Running
`down -v` with the corresponding Compose/project arguments deletes that volume. API documentation and
schemas are at `/docs` and `/openapi.json`.

Recognition uses the built-in OpenCV implementation by default. Operators can
override the importable callable with `AROMAP_RECOGNITION_CALLABLE`; a blank value
uses the default. No mock recognition is served by production endpoints.

## Configuration

Environment variables (or `Settings` in tests):

For Compose, these can be set in the repository root `.env` (the data directory
remains `/data`); see root `.env.example`. A blank CORS setting in Compose derives
localhost/127.0.0.1 origins from `FRONTEND_PORT`. For local uv execution, export
settings in the shell; `.env` is not
automatically loaded by the application.

| Variable | Default | Meaning |
| --- | --- | --- |
| `AROMAP_DATA_DIR` | `.data` relative to working directory | SQLite, uploads, results; `/data` in Compose |
| `AROMAP_CORS_ORIGINS` | `http://localhost:5173` | Comma-separated allowed frontend origins |
| `AROMAP_MAX_UPLOAD_BYTES` | `10485760` | 10 MiB per image |
| `AROMAP_MAX_IMAGE_PIXELS` | `20000000` | Maximum decoded width × height |
| `AROMAP_RETENTION_SECONDS` | `86400` | Upload retention and terminal-job/result retention |
| `AROMAP_CLEANUP_INTERVAL_SECONDS` | `60` | Periodic expired-resource cleanup |
| `AROMAP_QUEUE_CAPACITY` | `4` | Waiting recognition and simulation jobs, in addition to one running job |
| `AROMAP_RECOGNITION_CALLABLE` | `app.floor_plans.recognition.interface:recognize_floor_plan` | Importable recognition function; blank uses the default |
| `AROMAP_RECOGNITION_TIMEOUT_SECONDS` | `60` | Hard recognition deadline in seconds, including child startup |
| `AROMAP_SIMULATION_MAX_WORKING_BYTES` | `536870912` | Estimated simulation working-memory budget in bytes; not a hard process limit |

The storage root contains `registry.sqlite3`, `uploads/<image_id>/image.png`, and
`results/<job_id>.json`. Public IDs are randomly generated; client filenames never
choose filesystem locations. No login is required: anyone holding a resource ID
can access it until expiry. These endpoints are temporary resources, not cloud saves.

## Frontend contract

### API routing

Frontend application code uses relative `/api/...` URLs. Vite and staging Nginx
proxy them to `API_PROXY_TARGET` (default `http://backend:8000`), preserving the
`/api` prefix.

The backend remains directly available on `BACKEND_PORT` for Swagger and API tools.
Host port changes do not change the internal upstream. Direct browser requests
from another origin use configured CORS; same-origin proxied requests need none.
Proxies must allow at least the configured file limit plus 1 MiB multipart overhead.
The returned image/status paths are relative to the API origin and work through
the same `/api` proxy. Without a proxy, resolve them against the backend origin.

### Upload

`POST /api/floor-plans/uploads`, `multipart/form-data`, field **`image`**.
Accept PNG, JPEG, or WebP; reject animation. Validate actual decoded format rather
than trusting the filename or declared MIME type. Normalize EXIF orientation,
strip metadata, and return a prepared PNG without resizing. The dimensions and all
recognized coordinates refer to this prepared image, not the original file.

```javascript
const body = new FormData();
body.append("image", file);
const response = await fetch('/api/floor-plans/uploads', {
  method: "POST", body,
}); // Let the browser set Content-Type and its multipart boundary.
if (!response.ok) throw await response.json();
const uploaded = await response.json();
```

`201 Created`:

```json
{
  "image_id": "opaque-image-id",
  "image_url": "/api/floor-plans/uploads/opaque-image-id/image",
  "width_px": 1600,
  "height_px": 1000,
  "media_type": "image/png",
  "expires_at": "2026-11-01T09:00:00Z"
}
```

`GET /api/floor-plans/uploads/{image_id}/image` returns PNG bytes with
`Cache-Control: no-store`. Resolve returned paths against the backend origin when
FE and BE use different origins. The frontend should retain the prepared image in
IndexedDB for editing/export, rather than depend on an expiring URL. Upload success
does not start recognition.

The file-byte and pixel limits are independent. The total multipart request is
also bounded to the file limit plus 1 MiB of envelope overhead, including chunked
requests. Missing/wrong fields return the standard validation error below.

### Recognition

`POST /api/floor-plans/recognitions`, JSON:

```json
{ "image_id": "opaque-image-id" }
```

`202 Accepted`:

```json
{
  "job_id": "opaque-job-id",
  "status_url": "/api/floor-plans/recognitions/opaque-job-id"
}
```

Queue saturation returns **429 `queue_full`**; retry later.

`GET /api/floor-plans/recognitions/{job_id}` returns `200` with status and an inline,
typed result. Poll roughly once per second and stop at a terminal state.

```json
{
  "job_id": "opaque-job-id",
  "state": "succeeded",
  "created_at": "2026-10-31T09:00:00Z",
  "updated_at": "2026-10-31T09:00:02Z",
  "expires_at": "2026-11-01T09:00:02Z",
  "result": {
    "floor_plan": {
      "layout": {
        "id": "recognized-layout-id",
        "revision": 1,
        "width_px": 1600,
        "height_px": 1000,
        "walls": [],
        "doors": [],
        "windows": [],
        "room_labels": [],
        "indoor_domain": null,
        "calibration": null
      },
      "reference_image": null
    },
    "warnings": ["Example of an empty detection; manual correction needed."]
  },
  "error": null
}
```

States: `queued → running → succeeded / failed`. `result` is null except on success;
`error` is null except on failure, when it contains `{ "code": "...", "message": "..." }`.
A processing failure is a successfully retrieved job status (`200`, `state=failed`),
not an HTTP 500. The example above illustrates the schema, not actual recognition.

Frontend associates a job with its submitted image, attaches the locally retained
reference image to returned geometry, and asks before replacing existing edits.
Recognition does not infer opening states or calibration; the endpoint returns
`calibration: null` in the existing layout schema. Upload/job IDs stay in
runtime state, outside portable frontend saves.

`result.floor_plan.layout.indoor_domain` is an estimated **pixel-coordinate**
footprint for user review/correction, or `null` with a warning when unavailable.
Its shape is `{ "boundary": [PixelPoint, ...], "holes": [[PixelPoint, ...], ...] }`.
All indoor-domain vertex coordinates must be finite pixel values; NaN and infinity are rejected.
Each ring has at least three ordered vertices and closes implicitly; the outer
boundary may be concave (e.g. an L-shaped plan). Holes exclude areas such as outdoor
courtyards, not ordinary rooms or internal walls. Initially there is one outer
polygon; disconnected footprints and polygon topology validation remain future work.

The built-in recognizer estimates a footprint when it can close the exterior walls;
otherwise it returns `null` with a manual-tracing warning. FE lets users correct an estimate
or trace the missing boundary, stores it in pixels, and converts it to meters for
`geometry_m.indoor_domain` in simulation. No new recognition request fields or
separate domain endpoint are required.

### Errors

```json
{ "detail": { "code": "invalid_image", "message": "The image could not be decoded or prepared." } }
```

| HTTP status | Codes / meaning |
| --- | --- |
| 404 | `image_not_found`, `job_not_found`: unknown or expired resource |
| 413 | `image_too_large`: bytes, pixels, or request envelope exceeds limits |
| 415 | `unsupported_image`, `animated_image` |
| 422 | `invalid_image`, `invalid_request` |
| 429 | `queue_full` |
| 500 | `result_unavailable`, `internal_error` |

Provider exceptions are logged server-side; jobs expose a generic
`recognition_failed` error without paths or exception details. Invalid request
fields use the same error envelope, including FastAPI validation failures.

## Simulation API

Routes and typed request/response schemas are exposed in Swagger:

| Route | Behavior |
| --- | --- |
| `POST /api/simulations` | Queues a configuration and returns `202` with `job_id`, `client_request_id`, and `status_url`; returns `429` if the shared queue is full. |
| `GET /api/simulations/{job_id}` | Returns queued, running, succeeded, or failed status with result metadata or an error. |
| `GET /api/simulations/{job_id}/fields` | Downloads the completed field bundle; returns `404` before completion or after expiry. |

Jobs run in an isolated process with a 120-second hard deadline. Preparation and
solver failures are reported in the failed job status. Jobs share the bounded queue
with recognition and are interrupted on backend restart. Results and submitted
snapshots are retained for the configured retention period and then cleaned up.

Request models live in `simulations/models.py` and `simulations/schemas.py`.
See the [example request](tests/fixtures/simulations/request.json) and
[example result metadata](tests/fixtures/simulations/result.json). They are schema
fixtures, not simulated data or working download links.

`SimulationRequest` carries `client_request_id`, `geometry_m`, consumer
`diffuser_definitions`, metric `placements`, `opening_states`, `conditions`, and
`settings`. Send only one selected configuration and its definitions: no image,
pixel geometry, calibration, other scenarios, or entire project document.
Every placement has a stable `placement_id` and `definition_id`; definitions contain
raw capacity/units/lifetime/operating-hour inputs and provenance. Missing product
information is allowed and standalone preparation resolves fallback relative rates.
Optional `density_g_per_ml` supports volume conversion. Product fields use API snake_case names;
the FE's saved input format need not match them.

The initial footprint representation is an `indoor_domain` polygon `boundary` with
optional `holes`, all metric points. Closing edges are implicit. This distinguishes
indoor space from the rectangular image extent. The recognition contract provides
an optional estimated domain in pixels. The planned UI lets the user review/correct
it, or trace a boundary when no estimate is available; FE retains the reviewed
pixel geometry and converts it to meters for the simulation request.
Walls have IDs and metric `start`
and `end`; doors/windows additionally reference a `wall_id`. Placement positions
are explicitly `position_m`. The preparation library now checks polygon validity,
wall/opening topology, source containment, and resource limits during job execution.
A request accepted into the queue can therefore still fail preparation.

Settings require positive `duration_s` and exactly one of `sample_interval_s` or
strictly increasing `sample_times_s` within the duration. Omitted grid size resolves
to **0.25 m (25 cm)**; requests can override it. Spreading/removal parameters still
require explicit resolution; no physical defaults are implied by omission.

Completed status will contain `SimulationResult` metadata:

```text
run_id, input_fingerprint, model_version
grid                              origin_m, cell_size_m, rows, columns, axis directions
channels[]                        channel_id, placement_id, definition_id (ordered)
sample_times_s[]
fields                            url, bundle encoding, concentration axes/shape/units
  active_domain_mask              axes, shape (included in the same download)
resolved_assumptions[], diagnostics[], warnings[], expires_at
```

One channel represents one simulated placement, including separate channels for
placements sharing a definition. Disabled placements do not need a channel. Channel
list order is array order. Field axes are `[time, channel, row, column]`, with shape
`[T, P, H, W]`: sampled times, placement channels, rows, columns. The mask has shape
`[H, W]`; true means usable indoor space. Grid origin is the top-left grid corner;
values represent cell centers at `(x + (column + 0.5)*cell_size,
y + (row + 0.5)*cell_size)`, x rightward/y downward. Units are
`relative_units_per_m2`, not perceived scent strength.

Polling metadata never embeds the large numerical arrays. After success, FE fetches
`fields.url` once: the bundle contains `concentration` and `active_domain_mask`
arrays. There is no separate mask endpoint or download. FE then performs playback
and channel highlighting locally.
The bundle is a compressed NumPy NPZ archive: `concentration` is float32 and
`active_domain_mask` is boolean. Both are standard NPY arrays and do not require pickle. Aggregates by definition
or all placements can be derived under shared relative-unit assumptions instead of
duplicating arrays. Correlate responses using `client_request_id` and retain the
submitted snapshot to determine staleness; `input_fingerprint` identifies resolved
backend input, not the current editor state.


## Simulation preparation and numerical engine

The standalone entry points in `app/simulations/preparation.py` are:

- `prepare_input(...)` returns a detached, serializable `SimulationInput` with a
  resolved metric polygon/holes, walls, explicit opening states, ordered sources,
  explicit sample times, grid size, parameters, versions, assumptions, and fingerprint.
- `prepare_run(...)` additionally builds a `PreparedGrid` and estimates sampled
  output bytes. Neither function touches HTTP, SQLite, jobs, or artifact files.

The caller supplies a model version. The default source resolver is
`simulations/emissions.py:resolve_emission`; callers may replace it through
`resolve_source(definition, placement) -> ResolvedEmissionProfile`. It handles
strength/rated-hour overrides and records assumptions. Provisional spreading and
removal defaults resolve below; request values override caller defaults. There is
no operating schedule yet. The standalone solver is described below.

Interval-based sampling includes zero and the duration, appending a final partial
interval when needed; explicit sample timestamps are preserved. Numerical solver
time steps are selected independently from exported snapshots. The fingerprint covers resolved
input and versions, not client request IDs. FE input models are copied, so later
editor/caller mutations do not alter the prepared snapshot.

Grid code lives under `app/simulations/engine/`:

```text
PreparedGrid
  origin_m, cell_size_m, rows, columns
  active_mask[H,W]                  cell center inside domain, outside holes
  active_index[H,W]                 compact row-major index, -1 outside
  connections[E,2]                 undirected active-cell neighbor pairs
  source_weights[]                 placement/definition IDs, indices, weights
  warnings[]
```

The bounding rectangle rounds upward to cover the polygon; cell centers determine
active cells. Connections consider right/down neighbors once (four-neighbor graph),
exclude segments crossing outdoor areas/holes, and block intersections with walls.
Open door segments are subtracted from their parent wall; closed openings remain
barriers. Open exterior windows and doors are mapped separately to boundary cells.
Walls must be split at junctions, and overlapping walls/openings are rejected.

Each enabled placement initially maps to its containing active cell with weight 1.
Sources outside usable space, on closed walls, without an active containing cell,
or separated from that cell's center by a barrier are rejected rather than snapped
across barriers. Disabled emitters are excluded; zero-start source/channel order
follows request order. Resolved initial state may retain additional residual
channels in its explicit order. `PreparedGrid.expand()` maps
compact active-cell values back to rectangular arrays with zero outside the mask.
Arrays prepared for the solver are read-only. The solver exchanges concentration
only across the prepared connections.

The 25 cm default is adjustable through the request or preparation caller. Warn on
unrepresented/narrow doors, thin footprint regions, and center-classified area
approximation. Finer geometry is not guaranteed accurate merely by smooth rendering;
these are grid approximations, not a fitted mesh.

`PreparationLimits` provides adjustable operational defaults: 100,000 bounding cells,
600 samples, 16 channels (including residual channels), 10,000 geometry elements
(ring vertices plus segment endpoints), 6-hour duration, 0.10–1 m cells, and
256 MiB estimated sampled payload with a warning above 64 MiB. Requests default to
1 hour and automatic 30-second sampling (or the shorter duration). When this would
exceed the sample cap, automatic sampling uses evenly spaced times within the cap,
including zero and the final time. Omitted sampling stays automatic through JSON
round trips. Explicit intervals/timestamps are preserved and rejected if over the
cap; they are never silently coarsened. Sampling is independent of the
solver time step. Sampled `EngineOutput`
concentrations must use float32, be finite/nonnegative, and be zero outside the
active domain. Output timestamps must be nonempty, finite, nonnegative, and strictly
increasing. The boundary rejects invalid values rather than silently correcting
them; any roundoff correction belongs to the solver. Output channel metadata is
always resolved to an explicit tuple. Solver working arrays may use higher precision. Estimates count float32
concentration plus a boolean mask, not sparse-solver working memory or file overhead.
Duration/resolution/output checks precede source resolution and grid allocation.
`ExecutionLimits` sets a provisional 120-second runtime budget and 512 MiB working
memory budget. Preparation checks an array working-set estimate before building
the grid; the solver adds sparse-factorization working-set estimates and checks
deadlines between numerical operations. Invalid, non-finite, negative, or over-budget memory
estimates are rejected. These guards are not an OS memory cap. The simulation job
worker also enforces a process-level deadline, including preparation and serialization.

Provisional physical parameters in `simulations/limits.py`:

| Parameter | Default and basis |
| --- | --- |
| Effective spreading | 0.0045 m²/s, the rounded median of 11 fitted estimates in two residences in [Cheng et al. (2011)](https://pubmed.ncbi.nlm.nih.gov/21456572/). Low/high use rounded quartiles; the study's full range was approximately 0.001–0.013 m²/s. These are scenario choices, not measured values for a submitted layout. |
| Uniform removal | 0.5 air changes/hour, converted to 0.5/3600 per second. This is an illustrative residential assumption, informed by variable residential measurements discussed in [this air-exchange study](https://pmc.ncbi.nlm.nih.gov/articles/PMC5369024/), not an inference from the floor plan. No additional chemical or surface loss is added. |

The spreading parameter represents unresolved mixing, not molecular diffusion or
directional airflow. Directional transport uses a separate approximate field;
a recirculating fan is not automatically
fresh-air exchange. Door width affects represented connections, without a second
width multiplier. Window size alone cannot determine ventilation: pressure, wind,
and thermal driving forces also matter ([NIST CONTAM documentation](https://www.nist.gov/publications/contam-user-guide-and-program-documentation-version-34)).

`EngineOutput` returns `[T,P,H,W]` fields, channel identities, numerical diagnostics,
and an internal compact `final_state`. The simulation job worker publishes the
sampled fields and metadata through the HTTP endpoints.

### Cell balance and solver (implemented)

For each placement channel and active cell, update concentration by **spreading
through connected cells + source emission − uniform removal**:

$$
\frac{C_i^{new}-C_i^{old}}{\Delta t}
= \frac{D}{h^2}\sum_{j\text{ connected to }i}(C_j^{new}-C_i^{new})
+ \frac{q_i}{h^2} - k C_i^{new}.
$$

Here `C` is relative concentration per m², `h` is cell side length in meters,
`D` is effective spreading in m²/s, `q_i` is the source rate assigned to that cell
in relative units/s, and `k` is removal per second. Dividing emission by cell area
preserves the emitted quantity when resolution changes. Each connection transfers
equal/opposite quantities; missing connections implement impermeable boundaries.
No outside zero-concentration neighbors are added. Cell values represent averages
over the full active square cell, stored at its center; boundary geometry remains
the existing grid approximation.

This is a square-cell adaptation of [NIST's finite-volume discretization](https://pages.nist.gov/fipy/en/stable/numerical/discret.html):
neighbor concentration differences approximate diffusive exchange, and no-flux
boundaries prevent leakage. Using new-time values gives implicit backward Euler.
`engine/solver.py:simulate(prepared, options=None)` assembles a sparse transport
matrix and uses [SciPy SuperLU](https://docs.scipy.org/doc/scipy/reference/generated/scipy.sparse.linalg.splu.html).
One factorization is reused for all steps and placement channels, including residual
channels with no active emission. Float64 working states become float32 snapshots;
non-finite values, material negatives, and float32 overflow fail explicitly. Tiny
negative roundoff is clipped to zero and its added quantity is recorded.

The simulation timeline is authoritative. Backend-only `SolverOptions` defaults
to a maximum 0.25-second step, additionally capped by `0.25*h²/D` and `0.05/k` (no
removal cap when `k=0`). These are provisional accuracy controls, not stability
requirements or scientific constants. The duration is divided into equal steps
no larger than that cap, reaching the exact end with one reusable matrix. Runs
requiring more than 200,000 steps are rejected before factorization.

Requested heatmap times do not alter integration: snapshots between computed
states use linear interpolation. The engine always advances the full duration,
even if the last requested snapshot is earlier. `final_state` contains the compact
float64 end state and cumulative elapsed time; it can feed a later internal run.
Checkpoint APIs, state migration, and operating schedules are still unimplemented.
Diagnostics record solver version and the resolved step/count for reproducibility;
future result caching/versioning must include the numerical policy as well as the
prepared input fingerprint.

Memory guards reserve room for arrays and estimated sparse LU fill before solving,
then check actual factor storage. Native library allocation/work cannot be forcibly
interrupted inside this synchronous function. The API runs it in a separate process
with a deadline, but does not enforce a hard RSS cap.

Tests cover conservation, source accumulation, decay, walls/doors/holes, per-placement
superposition and residuals, spatial/time refinement, and independence from snapshot
schedule. These validate the numerical model, not real-world scent perception.
An early-time check on a small point-source layout compared the default 0.25-second
step with a 0.015625-second reference: the relative field L1 difference at one second
was about 3%. The former 2-second candidate gave about 29% and was rejected. This
is a convergence check on that layout, not a universal accuracy guarantee.

Repeatable Linux smoke benchmarks, from `backend/`:

```sh
uv run --locked python -m scripts.benchmark_simulation --case apartment
# Other cases: comparison, large. Run separately for per-process peak RSS.
```

Representative development-machine checks with 25 cm cells and 30-second snapshots:

| Case | Active cells / channels | Simulated duration | Solver wall time | Process peak RSS |
| --- | --- | --- | --- | --- |
| Apartment | 4,800 / 4 | 1 hour | ~7.4 s | ~94 MiB |
| Placement comparison | 10,000 / 16 | 10 minutes | ~15.4 s | ~118 MiB |
| Large footprint | 99,856 / 1 | 1 minute | ~3.2 s | ~351 MiB |

These are synthetic rectangular-layout checks, not performance guarantees. Peak
RSS includes Python/native libraries; long, dense, many-channel combinations may
hit runtime/memory budgets even when individual preparation limits pass.

Temperature corrections remain 1 until supported product data exists. The solver
also supports the idealized directional transport described below.

### Standalone visual preview

Generate a portable HTML file directly from a metric configuration, without a
running API, React, browser uploads, or extra Python dependencies. From `backend/`:

```sh
uv run --locked python -m scripts.preview_simulation \
  --input tests/fixtures/layouts/open_door.json \
  --output .data/previews/open_door.html --scale-max 8
```

Open the generated HTML in a browser. It embeds its own geometry, float32 snapshots,
and active mask, with no external scripts, fonts, network calls, or adjacent-file
fetches. Play/pause, scrub time, select a placement or combined concentration, inspect
cell values, and toggle grid/log density. A plain background, soft single-hue haze,
and fine seeded speckles represent concentration; the marks are not particle
trajectories. Display interpolation uses only connected neighbors, preserving
closed walls and excluded regions. Numeric values remain untransformed. Display
limits remain fixed across time and channels; use the same `--scale-max` and log
setting across files for fair comparisons. Saturated density retains true values in
the numeric inspector. The viewer is a development aid, not the production field
encoding or a second editor.

Input accepts `SimulationConfiguration` or the request shape with `client_request_id`.
The JSON input cap is 2 MiB and the default raw-field/display-neighbor cap is 32 MiB, checked before
simulation. Base64 makes the HTML larger; `--max-preview-mib` explicitly changes
the preview cap, subject to normal engine limits. `--max-step-s` changes numerical
accuracy, while input sampling fields control exported snapshots. Generated files
under `.data/` are gitignored; source fixtures are in `tests/fixtures/layouts/`.

The closed/open doorway examples use identical sources. The split-placement example
uses two half-strength sources to preserve total emission; the courtyard example
exercises an L-shaped domain and an excluded hole. Each runs for one hour with
25 cm cells and 30-second snapshots.

### Emission policy (implemented) and future research candidates

One relative unit represents a surrogate for 1 mg of consumed formulation, not
measured fragrance mass or perceived scent strength. Source rates use relative
units/s; the 2D fields use relative units/m². Keep the same unit across runs.
The implemented `consumption-v1` baseline is usable refill mass divided by stated
operating lifetime: `capacity_g * 1000 / (lifetime_days * rated_hours_per_day * 3600)`.
Volume requires a density conversion; absent density, 1 g/mL is an explicitly
recorded fallback assumption. Missing usable consumption data falls back to an
explicit reference source of 1 g/day. These fallbacks are engineering choices,
not universal measured properties. Water-tank capacity is not fragrance capacity.
Supported estimation covers reed/passive and recognized evaporative liquid/electric
types. Unknown types, ultrasonic, nebulizer, candle, and gel products currently use
the reference fallback with a reason. Their capacity alone is not treated as a
compatible emission model. Gram inputs need no density. Passive reeds resolve to
24 hours/day, recording ignored non-24-hour ratings. Other supported types use the
placement rated-hours override, then product rated hours, then 24. Explicit
`strength_override` multiplies the rate, including zero; intensity labels are not
interpreted as multipliers.

For now, environmental/product correction multipliers are **1**. Do not infer
numerical multipliers from intensity labels. Preserve the resolver boundary for
future calibrated strength and environmental corrections, with reference conditions
and provenance so lifetime-based estimates are not corrected twice for the same
effect. Rated operating hours describe the lifetime estimate; future on/off
schedules are separate. Initial runs assume constant emission while enabled.

Prioritize the following factors when data becomes available. This is a practical
research priority, not a universal ranking of effects across all products:

| Factor | Scientific basis / potential relationship | Data needed before applying a correction |
| --- | --- | --- |
| Formulation and device type | [Chemical Product Evaporation Model study](https://www.mdpi.com/2076-3417/12/6/3112) models chemical/product properties and product mass loss. | Relevant refill mass, composition, device mechanism, or measured loss rates; avoid applying one device model to all types. |
| Temperature | [Reed-diffuser chamber study](https://doi.org/10.1016/j.xcrp.2024.102142) investigates temperature-dependent emissions; [NIST α-pinene data](https://webbook.nist.gov/cgi/cbook.cgi?ID=C80568&Mask=4) illustrates Antoine vapor-pressure coefficients with valid temperature ranges. | Known formulation/representative compound or measured product temperature response, plus reference temperature. Pure-compound vapor pressure alone is not a whole-product emission model. |
| Local air movement | [RIVM mass-transfer description](https://www.rivm.nl/en/consumer-exposure-to-chemical-substances/exposure-models/dustex/equations-describing-emission-and-transfer-of-substance-indoors) relates exposed area, transfer coefficient, and surface-to-air concentration difference, with stated applicability limits. | Local velocity/geometry and an applicable transfer correlation; whole-room ventilation does not determine local transfer. |
| Reed/wick geometry and transport | [RIVM air-freshener fact sheet, section 6.10](https://www.rivm.nl/bibliotheek/rapporten/2021-0233.pdf) describes capillary delivery, exposed reeds, and continuous release; the reed-diffuser chamber study models transport parameters. | Dimensions, material, exposed area, and supporting measurements; reed count alone does not justify a linear multiplier. |

Age/depletion and humidity remain later, product-specific research candidates.
Do not add a generic temperature, airflow, humidity, or reed-count correction
without supporting coefficients. These references motivate future work; their
equations are not currently implemented. Whenever a scientific formula/default is
implemented, document its exact source, units, applicable range, assumptions, and
adaptation to the 2D model alongside it. Label chosen defaults separately from
measured/calibrated values.

### Initial state and future continuation

The solver boundary defaults to zero via `engine/state.py:initial_concentrations`.
`prepare_run(..., initial_state=ResolvedInitialState(...))` also accepts an internal,
already-reconciled compact `[channel, active_cell]` concentration array. It validates
finite nonnegative values, matching grid topology/model version, unique channel
identities, and inclusion of all current emitting sources. It copies input values
into a read-only snapshot; the initial-state digest participates in the run input
fingerprint. `PreparedSimulation.channels` and explicit `EngineOutput.channels`
can include residual channels with no current emitter. The solver uses these
identities instead of assuming channel count equals emitter count.
`initial_concentrations` returns a fresh writable float64 solver array.
No initial-state HTTP field, checkpoint endpoint, or migration is implemented.

A future continuation resolver must validate units, grid/domain compatibility,
model versions, elapsed time, and channel identity, and produce engine-ready
per-channel concentrations. It may need to reconcile new/moved/disabled/deleted
placements or migrate state across geometry/grid changes; migration policy is
outside current scope. New channels can start at zero, but residual concentrations
from disabled/deleted sources must survive with zero further emission. Stable
channel identity and initial concentrations must therefore remain separate from
the list of currently emitting sources. `prepare_run` supports residual-only runs
with every placement disabled or removed, but only when supplied a valid resolved
initial state. Without that state, a zero-source run is rejected. Automatic channel
reconciliation and migration remain continuation work; the HTTP API has no state
handoff yet.
Do not use an expiring job ID as the sole definition of a continuation state.

## Jobs, expiry, and restart behavior

Recognition and simulation jobs share the queue. Uploads and image retrieval are
not jobs. Advice has no endpoint yet.

SQLite stores upload metadata and job kind/state, input image reference,
creation/update/expiry timestamps, result reference, and error details. It never
stores user projects or image bytes. Database transactions finish before computation.

The queue is bounded and in memory, not a durable broker. Shutdown/startup marks
unfinished jobs `failed` with `job_interrupted`; there are no automatic retries or
resumption. On shutdown, an executing child is terminated, with a forced kill if it
does not exit during the grace period. Simulations have a 120-second hard deadline;
recognition defaults to 60 seconds. A timeout fails the job with `execution_timeout`
and the dispatcher continues with the next job. Both deadlines include child startup.

Uploads expire 24 hours after creation by default. Jobs receive a fresh retention
window at completion. Active jobs remain pollable past their provisional expiry;
cleanup never removes their inputs. Files/metadata are retained internally while
referenced by a surviving job even if the public upload URL has expired. Terminal
jobs/results and unreferenced expired uploads are removed on startup and periodically.
Missing files are tolerated; individual filesystem failures are logged and retried.
Unregistered upload/result files (including interrupted temporary writes) are pruned
after one retention window of file age. Registered artifacts and pending job results
are protected, and fresh uploads have time to finish registering.
A successful browser save must not depend on any of these temporary resources.

## Modules and models

| Package | Owns | Contracts |
| --- | --- | --- |
| `floor_plans` | Image endpoints, preparation, recognition orchestration | `UploadedImage`, recognition DTOs, `RecognitionDraft`, `Layout`, `PixelIndoorDomain` |
| `floor_plans/recognition` | Image-to-editable-geometry implementation | Existing `Path → RecognitionDraft` boundary |
| `diffusers` | Raw consumer product specifications | `ConsumerDiffuserDefinition` |
| `simulations` | Metric contracts, emission resolution, grid preparation, numerical solver | `SimulationRequest`, `SimulationInput`, `PreparedGrid`, `EngineOutput`, `SimulationResult` |
| `advice` | Future on-demand interpretation | `AdviceRequest.configuration`, `AdviceResponse` |
| `infrastructure` | Local storage, SQLite, job execution, upload-body limit | Operational resources, not project ownership |

Placements, opening states, conditions, and simulation settings now live in
`simulations/models.py`. `Scenario` is replaced by `SimulationConfiguration`, which
has no saved-scenario ID/name. The browser can compose these API data shapes into
its own versioned project format; the backend has no import/export migrations.
`FloorPlan`/`ReferenceImage` remain for compatibility with the handed-off recognition
contract, but recognition returns `reference_image=None`.

## Recognition handoff contract

The authoritative callable and error contract remain in
[`interface.py`](app/floor_plans/recognition/interface.py), and output models in
[`models.py`](app/floor_plans/models.py):

```python
recognize_floor_plan(image_path: Path) -> RecognitionDraft
```

It delegates to the OpenCV pipeline in
[`pipeline.py`](app/floor_plans/recognition/pipeline.py), which detects axis-aligned
walls (solid or hollow line-drawn) and identifies doors and windows from wall gaps,
swing arcs, and glazing lines. Other providers should live in sibling modules
behind the same entry point.

### Supported input images

Recognition targets **clean digital floor plans**. Show this guidance at upload;
other images still return a draft, but expect to correct or trace it manually.

| Supported | Not supported (unreliable) |
| --- | --- |
| Computer-drawn or exported plan, top-down | Photos, scans, hand or pencil drawings |
| Walls clearly thicker than other lines (solid black/gray, or two lines with a gap) | Walls as thin as shelves, furniture, or text |
| Horizontal and vertical walls | Diagonal or curved walls |
| Light background; plain floor colors are fine | Landscaping, 3D renders, heavy decoration or hatching |
| Doors as gaps with a swing arc; windows as gaps with 2+ thin parallel lines | Busy CAD sheets with many dimensions and title blocks |
| Roughly 500–2000 px, with the plan filling most of the image | Angled photos (perspective distortion) |

When a plan looks unsupported (much of its wall-like content is detached
clutter), the draft includes a warning that results may be unreliable.

#### Base layout format

Recognition is tuned against one reference style: a shop plan like
[`cafe_plan.png`](tests/floor_plans/recognition/fixtures/cafe_plan.png). Plans
drawn this way are expected to come out right without manual fixes:

| Element | How it is drawn | How it is read |
| --- | --- | --- |
| Wall | Solid band clearly thicker than other lines | Wall centerline; short returns at corners and beside doors (at least one wall thickness long) are kept when they meet a longer wall |
| Door | Gap in a wall with a quarter-circle swing arc centered on the hinge | Door from the hinge to the arc's end; two facing arcs make a double door. A door frame under one wall thickness joins the door |
| Window | Gap in a wall with 2+ thin parallel lines inside the wall's thickness | Window across the gap |
| Doorway | Door-sized gap between aligned walls, no symbol | Open floor (e.g. a passage between the sales floor and the stockroom) |

Door swings are found as arcs first (circle fit on curved strokes), so text,
furniture outlines, and full circles such as round tables are not read as doors.

#### Input checklist

What an image needs for recognition to work, with the current thresholds. **T**
is the wall thickness measured from the image. The committed plans in
[`fixtures/`](tests/floor_plans/recognition/fixtures) all meet it.

**Image**
- Clean digital drawing on a light background, not a photo, scan, or sketch.
- About 400–2000 px on the long side. Larger images are scaled down to 2000 px;
  on small images walls are only a few pixels thick, so arcs and glazing get lost.
- No sheet frame or title block close to the walls. Dimension lines and text
  outside the building are fine.

**Walls**
- Dark (gray 100–180 or darker), at least 3 px, and clearly thicker than every
  other line (about twice furniture and text lines). Strokes under 0.35 T are
  ignored.
- Horizontal or vertical only; diagonal walls are missed.
- At least 3 T long, or 1 T if the piece meets another wall.
- Outer walls form a closed loop: every gap in them needs a door or window
  symbol, otherwise there is no indoor outline.
- Little extra drawn on the wall lines; corner column markers add small steps to
  the outline.

**Doors**
- Quarter-circle swing arc (45–120°), hinged on the wall line (within 1.5 T or
  30% of the radius), radius at least 2 T. Solid, dashed, or colored arcs work.
- Gap 3 T–15 T wide (up to 25% of the image's long side when an arc confirms
  it), with the arc covering at least 60% of it.
- Arcs within 1 T of each other form one double door; arcs with wall between
  them are separate doors.
- Sliding doors, or door leaves drawn as thin rectangles, are read as doors only
  on inner walls (see Windows).
- A door drawn half open (CAD style: a straight leaf with only a short arc) is
  found from its leaf: a line from the hinge at a gap end (or up to 1 T in from
  it), 15–75° off the wall, about as long as the gap (3–15 T).

**Windows**
- At least 2 thin parallel lines inside the gap, each along at least 60% of it
  with one unbroken piece at least 35% of the gap, within 0.5–0.75 T of the wall
  line. Dashed lines across a gap are an open passage, not glass.
- Each line at most T/2 or 4 px wide; together they cover at most 80% of that
  band (more is a floor color, not glass).
- On outer walls. Glazing on an inner wall (more than 2 T inside the outline) is
  read as a door.
- Up to half the image's long side wide (glass walls).

**Open floor**
- A gap with no symbol stays open floor.

**Clutter**
- If 15% or more of the wall-like length is detached from the walls, the draft
  warns that results may be unreliable.

- Caller supplies an absolute path to a prepared image, retains it throughout the
  call, and owns storage/cleanup. Recognition must not modify/delete the original.
- Recognizer generates layout/geometry IDs and returns revision `1`, matching image
  dimensions, `reference_image=None`, and `calibration=None`.
- `layout.indoor_domain` is an estimated polygon in prepared-image pixels, or
  `None` with a warning when unavailable. Map its vertices back after any internal
  resizing/rotation, just as for wall endpoints. Consumers may review/correct or
  trace the domain.
  The OpenCV recognizer ([`indoor.py`](app/floor_plans/recognition/indoor.py))
  closes doors and windows, fills the outdoors in from the image edge, and traces
  everything left (all rooms and the walls between them) as **one** `boundary`
  along the outer face of the outer walls, with no `holes`. When the outer walls
  are not closed, it returns `None` with a warning.
- Internal resizing/rotation must map back to input image coordinates: top-left
  origin, x rightward, y downward.
- Walls are nonzero, zero-thickness segments split at every crossing and T-junction.
  An X produces four segments; a T produces three. Connected segments share exact
  endpoint coordinates, with no junction inside a returned segment.
- Parent walls span their door/window openings. Each opening lies along and
  references one final wall segment. Omit ambiguous openings with a warning rather
  than emitting dangling references.
- Wall IDs are unique within walls. Opening IDs are unique across doors/windows.
  Frontend preserves IDs for surviving features; repeated recognition need not
  reproduce the same IDs.
- Return partial/empty geometry with warnings for incomplete/no detection. Raise
  `RecognitionError` for unreadable images or processing failures.
- Do not infer operating states, A/C/fans, airflow, or simulation grids.

The executor checks basic output structure, dimensions, revision, and unset
calibration/reference image. Full geometry/topology validation remains follow-up
work; the model declarations do not enforce it yet.

The recognition contract has nullable `layout.indoor_domain` (`PixelIndoorDomain`);
providers may omit it when they cannot estimate a footprint.
The endpoint still returns `calibration: null`; actual calibration is frontend-owned.

## Backend roadmap

1. **Recognition refinement:** verify pixel geometry and footprint estimates against
   representative prepared images.
2. **Engine refinement:** benchmark and extend the standalone sparse backward-Euler
   implementation using predefined layouts and convergence/physical-balance checks.
3. **Preparation refinement:** benchmark the implemented consumption resolver,
   provisional defaults, resource guards, and initial-state boundary alongside the
   prototype; integrate NPZ playback in the frontend.
4. **Simulation delivery:** integrate queued execution and sampled-field playback into the frontend.
5. **Advice and reliability:** add on-demand interpretation, execution limits,
   recovery improvements, and representative end-to-end checks.

Recognition refinement can progress alongside engine work. Further numerical calibration,
supported environmental corrections, and final delivery DTO details remain design work. Browser
persistence/export stays frontend-owned; no backend project storage is planned.

## Coordinates and future simulation flow

`PixelPoint` is used for editable geometry, calibration endpoints, and placements.
`MetricPoint` is used for resolved solver geometry and sources. Both serialize as
`{ "x": ..., "y": ... }`; containing schemas define their units.
Recognition's `PixelIndoorDomain` uses pixels; simulation's `IndoorDomain` uses
meters. Neither uses screen coordinates. The prepared-image top-left origin and
rightward/downward axes are preserved through FE's scale conversion.

The current planning direction is FE-owned calibration and pixel-to-meter
conversion before submission, rather than requiring a backend scaling operation.
The uniform conversion is:

```text
meters_per_pixel = distance_m / hypot(end.x - start.x, end.y - start.y)
x_m = x_px * meters_per_pixel
y_m = y_px * meters_per_pixel
```

FE should reject absent/zero-length calibration and apply scale to all geometry,
positions, and layout dimensions before submission. Backend still validates metric
inputs and prepares the numerical grid. Metric coordinates retain the same axis
directions. Grid cell size is in
meters and independent of image resolution. Display zoom/pan changes no stored
geometry; resampling the underlying image must transform calibration/geometry too.
Perspective images require rectification before a uniform scale is meaningful.

```mermaid
flowchart TD
    Upload["Browser: upload image"] --> Prepared["Backend: prepared PNG and image ID"]
    Prepared --> Recognition["Recognition job: Path to RecognitionDraft"]
    Prepared --> Browser["Browser: retain image and editable configuration"]
    Recognition --> Browser
    Browser <-->|"Browser-owned"| Save["JSON export / import"]
    Browser --> Simulation["Submit one simulation configuration"]
    Simulation --> Metric["Validate and resolve metric SimulationInput"]
    Metric --> Engine["Grid and 2D solver"]
    Engine --> Result["Sampled fields and metadata"]
    Result --> Playback["Browser: heatmap and playback"]
```

Simulation requests carry metric geometry, definitions,
placements, opening states, conditions, and settings for one configuration. They omit image
bytes and inactive scenarios. Preparation validates references, resolves omitted
opening states to closed, and records explicit assumptions in a detached input.
Open interior doors connect spaces; open exterior doors and windows exchange air
using the approximate boundary model. Metric/grid preparation is implemented independently;
the solver and HTTP execution path are implemented.

The HTTP contract now describes grid alignment, channel/time/array ordering,
relative units, request correlation, NPZ encoding, and queued delivery. Advice accepts explicit configuration
context, not the browser's project document.

Results will represent approximate relative concentrations under stated assumptions,
not accurate real airflow or perceived scent intensity. Test the engine
independently of recognition using predefined layouts under `tests/fixtures/layouts/`.

### Idealized airflow

Airflow is a steady 2D scenario, not measured room airflow or CFD. Diffuser
concentration remains a height-averaged relative quantity per square meter. The
model adds one signed air flux per connected cell edge, measured in m²/s per
unit room height. Fan and recirculating A/C devices generate a localized Gaussian
initial velocity (0.025, 0.05, or 0.1 m/s for low, medium, high; radii 1 m and
1.5 m respectively). These are illustrative engineering presets, not device
specifications. Direction angles are degrees clockwise from image right (y down).

The initial edge fluxes are projected to satisfy incompressible mass conservation.
The continuous analogue is `u = u* - grad(phi)`, `laplacian(phi) = div(u*)`;
the graph discretization solves a sparse Laplacian with no wall-normal flow and
specified idealized exterior potentials. Phi is a correction velocity potential,
not a calibrated physical pressure. The sparse graph equation is solved with
Jacobi-preconditioned conjugate gradients, relative tolerance 1e-10, absolute
tolerance 1e-14, at most 10,000 iterations, and deadline checks. Nonconvergence
fails with `airflow_failed` and suggests a coarser grid or simpler layout. A
conservative projection working-set estimate is checked before allocation; this
is not a hard process RSS limit. Projection and scent-solver peak estimates are
checked separately because their temporary matrices do not coexist. A synthetic
40 m square, 25 cm grid (25,600 cells), one-fan projection took about 0.27 s on
the development machine; this is not a deployment performance guarantee. This follows
the projection principle in
[Vreman (2014)](https://doi.org/10.1016/j.jcp.2014.01.035); one projection of a
prescribed push is not a Navier–Stokes calculation. Wind presets yield approximate
potential amplitudes 0, 0.02, 0.05 m/s for calm, moderate, breezy. They do not
predict actual wind pressures or window ventilation. Wall geometry and grid
resolution limit how faithfully flow turns around obstacles.

The scent solver uses conservative first-order upwind finite-volume advection;
see [NIST FiPy finite-volume equations](https://pages.nist.gov/fipy/en/stable/numerical/discret.html).
This can introduce numerical spreading; refinement comparisons are necessary.
On one 4 m square test with a medium fan, 60 s duration and 0.005 m²/s background
mixing, area-integrated relative field L1 differences versus 10 cm cells were
about 28% at 40 cm and 18% at 20 cm. The default 25 cm grid differed by about
22% from a 12.5 cm run of the same case. A 0.25 s time step differed from 0.0625 s
by about 0.1% on the 20 cm grid. These comparisons include source discretization
and are neither real-world validation nor a universal error bound; near-source
plume shape and results on other layouts can vary substantially.
An opening removes scent in net outgoing flow and, separately, a balanced two-way
exchange equivalent to 0.001, 0.003, or 0.006 m/s times represented width per
unit height. Incoming outdoor air has zero modeled fragrance. These exchange
velocities are illustrative, not experimentally calibrated, and apply in addition
to net flow. Room-wide removal represents *other* background ventilation and
must not include the same openings again. A recirculating fan or A/C is not
fresh-air ventilation. Mixing presets map low/medium/high to 0.002/0.0045/0.006
m²/s effective diffusivity; they represent unresolved mixing rather than purely
molecular diffusion. These rounded quartiles are based on 11 experiments in two
residences, without independently separating the explicit fan contribution, and
are not validated as residual mixing in this 2D solver. See the [calibration
investigation](docs/airflow-calibration.md) for reproducible calculations,
comparisons, and the limits of the window and device presets.

Optional request fields, preserving the original request format when omitted:

```json
{
  "settings": {"mixing_preset": "medium"},
  "conditions": {"removal_rate_per_s": 0.0001388889},
  "airflow": {
    "outdoor_conditions": "moderate",
    "wind_direction_degrees": 0,
    "devices": [{"id": "fan-1", "type": "fan", "position_m": {"x": 2, "y": 1},
                 "direction_degrees": 90, "strength": "medium"}]
  }
}
```

`mixing_preset` and an explicit `effective_diffusivity_m2_per_s` are mutually
exclusive. Devices also accept type `ac`; up to eight are allowed, each must be
in active indoor space. An AC is assumed to recirculate. Clients may supply
background ventilation as `removal_rate_per_s`; this should exclude modeled openings.
Omitted airflow defaults to calm with no devices. Opening states still default to
closed. Classification uses closed wall/domain enclosure faces and tests for walls
between the opening and the boundary, including at ray endpoints and courtyards.
Exterior wall centerlines may be offset by up to 1.5 cells (minimum 0.15 m).
An offset wall that cannot be established as the boundary of a closed wall
enclosure is ambiguous; clients may set an opening's `boundary_kind` to
`"interior"` or `"exterior"` to resolve it. An exterior override must still be
near the domain edge and cannot contradict another enclosing wall. The model
warns when exterior openings are inferred; incomplete or incorrect floor-plan
geometry can still be ambiguous. An open window too far from a boundary or an
opening that cannot be mapped to an indoor cell fails preparation. Openings are sampled into indoor
cells and their widths conserved. No outdoor cells are simulated. Furniture
resistance and height-dependent flow are not implemented.
