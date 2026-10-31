# Aromap backend

FastAPI backend with domain packages. This is groundwork: models are draft
contracts, not a finished API or simulation implementation. Floor-plan recognition
has an initial OpenCV implementation; no domain endpoints, solver, job runner,
storage provider, or AI provider exist yet.

## Local development

Use Python 3.12+ and uv from this directory:

```sh
uv sync --locked
uv run uvicorn app.main:app --reload
```

The root Compose configuration also builds this service. FastAPI's generated
documentation is available at `/docs`; no domain routes are registered yet.

## Modules and dependencies

| Package | Owns | Main models |
| --- | --- | --- |
| `floor_plans` | Uploaded reference image, editable geometry, calibration, recognition draft | `FloorPlan`, `Layout`, `Wall`, `DoorOpening`, `WindowOpening`, `ScaleCalibration`, `RecognitionDraft` |
| `diffusers` | User definitions, future example profiles, emission assumptions | `DiffuserDefinition`, `RelativeEmissionProfile` |
| `projects` | Portable document, scenario editing contracts, future schema migrations | `ProjectDocument`, `Scenario`, `OpeningState`, `DiffuserPlacement`, `EnvironmentalConditions`, `SimulationSettings` |
| `simulations` | Resolve inputs, prepare grid, run model, describe results | `SimulationInput`, `SimulationGeometry`, `EmissionSource`, `SimulationResult` |
| `advice` | On-demand suggestions referring to explicit project/scenario state | `AdviceRequest`, `Suggestion`, `AdviceResponse` |
| `infrastructure` | Future temporary artifact storage and process execution | `JobStatus` |

`projects` composes floor-plan and diffuser models. `advice` accepts a project
snapshot. Simulation preparation will translate projects into resolved simulation
inputs; the engine must not depend on the project document, FastAPI, database
sessions, or artifact storage. Geometry primitives are currently shared through
`floor_plans`. Infrastructure executes domain work without owning its rules.

Keep future routers, request/response schemas, services, and repositories inside
their owning domain as needed. No global layer directories or generic repository
framework are required. `recognition/` and `simulations/engine/` reserve implementation
boundaries; provider interfaces should follow concrete integration needs.

## Document and model relationships

```text
ProjectDocument (schema_version)
  floor_plan
    reference_image (optional, embedded)
    layout (id, revision)
      walls / doors / windows / optional room labels
      optional scale calibration
  diffuser_definitions[]
  scenarios[]
    placements[] -> diffuser definition IDs
    opening_states[] -> door/window IDs
    environmental conditions
    simulation settings
  active_scenario_id -> scenario ID
```

A definition describes a diffuser; a placement is one instance with a position,
optional strength override, and enabled state. Example and user profiles will
resolve through the same path. Initial emission profiles are constant and relative;
example values and scientific defaults have intentionally not been chosen.

All scenarios currently share the project's current layout and definitions. A
layout edit therefore affects future runs of every scenario. Past runs retain a
complete resolved snapshot. Independent layouts per scenario can be added later
if comparisons require them.

Editable geometry uses image pixels with a top-left origin, x rightward and y
downward. Calibration maps a nonzero pixel segment to a distance in meters.
Draft layouts may be uncalibrated; simulation preparation must reject them.

`PixelPoint` (`floor_plans/models.py`) is used for editable walls, openings,
labels, calibration endpoints, and diffuser placements. `MetricPoint`
(`simulations/models.py`) is used for resolved walls, openings, and emission
sources. Both serialize as `{ "x": ..., "y": ... }`; their containing schemas
establish the units. There is no automatic conversion between these types.

Simulation preparation will compute a uniform scale from calibration:

```text
meters_per_pixel = distance_m / hypot(end.x - start.x, end.y - start.y)
x_m = x_px * meters_per_pixel
y_m = y_px * meters_per_pixel
```

Apply this scale to all geometry, source positions, and layout dimensions before
calling the engine. Reject zero-length calibration segments. Solver cell size
is specified in meters independently of image resolution. This conversion assumes
a uniformly scaled, undistorted plan; perspective images need rectification first.
Frontend zoom/pan changes only display coordinates. Resampling the underlying
image requires transforming geometry and calibration together.

Doors and windows reference a wall and describe an opening segment along it.
Their open/closed states belong to scenarios; unspecified states resolve to closed
during simulation preparation. Closed doors leave the wall impermeable; open doors
become connections. Window ventilation behavior is not yet defined; recognizing a
window does not imply support for simulating its airflow. Room labels are
annotations, not connectivity definitions.

Resolved `SimulationGeometry` uses meters with the same axis directions. Its
open doorways reference wall indices. The computational grid is derived data,
never the editable source of truth. Its mask, indexing, and field artifact format
remain to be designed together with the solver.

Models currently enforce basic types and scalar ranges only. Services must later
validate unique IDs, references, finite numeric values, calibration, wall/door
and window topology, traversable source positions, compatible sample settings, and resource
limits. Successful model construction does not mean a project is simulation-ready.

## Recognition handoff contract

The authoritative callable contract is in
[`app/floor_plans/recognition/interface.py`](app/floor_plans/recognition/interface.py);
the output schema and geometry conventions live in
[`app/floor_plans/models.py`](app/floor_plans/models.py).
The callable delegates to the OpenCV pipeline in
[`app/floor_plans/recognition/pipeline.py`](app/floor_plans/recognition/pipeline.py),
which detects axis-aligned walls plus doors and windows from gaps in them.
Other providers should also live in sibling modules behind this entry point.

```python
from pathlib import Path

from app.floor_plans.recognition.interface import recognize_floor_plan

# Caller-provided absolute path; storage location is configurable.
draft = recognize_floor_plan(Path("/tmp/aromap/uploads/example/source.png"))
```

| Side | Responsibility |
| --- | --- |
| Caller | Validate upload limits/format; normalize EXIF orientation; save the image; pass its absolute path; retain it throughout the call; attach reference image afterward; clean up storage |
| Recognizer | Read image; detect walls, doors, windows; generate IDs; return `RecognitionDraft`; clean up its own intermediates |
| Frontend / scenario | Correct geometry, calibrate scale, choose door/window states |
| Simulation preparation | Validate final geometry and state references; resolve omitted states to closed; convert to metric solver input |

The temporary path above is an example, not a required directory. The recognizer
must not construct storage paths, look up upload IDs, modify/delete the original,
or embed image bytes. It runs synchronously; the caller controls background/process
execution and must keep CPU-heavy work outside the HTTP event loop.

Returned drafts have input-image dimensions, layout revision `1`,
`reference_image=None`, and `calibration=None`. Room labels may be empty. Any
internal resize or rotation must be mapped back to the prepared input image.

Geometry requirements:

- Pixel coordinates use a top-left origin, x rightward and y downward.
- Walls are nonzero, zero-thickness segments. Split every wall at crossings and
  T-junctions: an X crossing produces four segments, a T-junction three. Connected
  segments share identical endpoint coordinates; no junction remains inside a
  returned wall segment.
- Parent walls span their door/window openings. Opening endpoints lie on one
  final wall segment and reference its ID after splitting. If recognition cannot
  resolve an opening's parent unambiguously, omit that opening and warn rather
  than returning a dangling reference.
- Wall IDs are unique within walls; door/window IDs are unique across both opening
  collections. IDs are assigned after topology normalization and retained during
  frontend edits where the corresponding feature survives. Separate recognition
  runs do not promise identical IDs.
- Recognition returns geometry only, with no open/closed state, A/C or fan
  configuration, inferred airflow, or computational grid.

Incomplete recognition returns partial geometry with warnings; no detected
geometry returns an empty layout with a warning. An unreadable image or processing
failure raises `RecognitionError`. These are implementation requirements, not
topology validators already supplied by the placeholder models.

`OpeningState` in `app/projects/models.py` references an opening ID and explicitly
sets `is_open`. Preparation must reject duplicate/unknown references. The old
layout-level `DoorOpening.is_open` field has been removed: callers must put those
values into scenario states. No legacy JSON migration is implemented in this draft
schema. Open-window simulation policy remains follow-up work.

## Planned pipeline

```mermaid
flowchart TD
    Upload["Upload floor-plan image"] --> Recognition["floor_plans: recognize geometry"]
    Recognition --> Edit["Browser: correct layout and calibrate scale"]
    Diffusers["diffusers: user definitions and examples"] --> Project
    Edit --> Project["projects: ProjectDocument and scenarios"]
    Project <-->|"Browser save / load"| JSON["JSON export / import"]
    Project --> Prepare["simulations: validate and resolve SimulationInput"]
    Prepare --> Engine["simulations/engine: grid and 2D solver"]
    Engine --> Result["SimulationResult and sampled fields"]
    Result --> View["Browser: heatmap, playback, comparison"]
    Project -->|"On request"| Advice["advice: suggestions with reasons"]
    Result -.->|"Optional context"| Advice
```

Recognition and diffuser entry can happen in parallel. Infrastructure supports
recognition and simulation with background jobs and temporary artifacts; saved
projects remain browser-owned. The chart describes the planned flow.

1. Upload an image and submit a recognition job. In parallel, the browser lets the
   user enter diffuser definitions or choose examples.
2. Recognition returns `RecognitionDraft`, including warnings. The user corrects
   walls, doors, and windows and calibrates the scale. Recognition does not create the final
   computational grid.
3. The browser maintains a `ProjectDocument`. Users create/delete/move placements
   and change scenario conditions in the interactive editor.
4. Simulation preparation validates the selected scenario, resolves enabled
   placements and strength multipliers into explicit emission rates, converts
   geometry to meters, and produces a detached `SimulationInput` snapshot.
5. Record its input fingerprint, solver version, explicit parameters, and assumptions.
   The fingerprint algorithm and canonical serialization remain to be selected.
   Treat this snapshot as immutable after submission; the current mutable Pydantic
   models do not enforce deep immutability.
6. A process runner builds a boundary-aware grid and executes a single 2D model:
   diffusion/effective mixing, source emission, and ventilation represented as
   removal. Walls block flux; open doors connect spaces. Numerical stability,
   time-step selection, and cost limits belong to preparation/engine code.
7. Store sampled fields as a temporary artifact. Return `SimulationResult` metadata
   with sample times, its input snapshot, artifact ID, and diagnostics. The initial
   contract assumes zero initial concentration and uniform removal/diffusivity;
   record these assumptions explicitly. A 2D areal concentration uses relative
   units per square meter, not a physical airborne concentration or scent rating.
8. The browser retrieves fields and controls heatmap playback, slider, and legend.
   Scrubbing time does not rerun the simulation. Compare scenarios using consistent
   color scales. Fingerprints identify results that no longer match current edits.
9. On explicit request, advice analyzes the selected project/scenario and optional
   run. Verify that a supplied run matches the analyzed input before interpreting
   it. Return reasons, limitations, and the input fingerprint with suggestions.

Recognition and simulation share the job lifecycle `queued -> running ->
succeeded / failed`, with domain-specific payloads and artifacts. HTTP handlers
should submit work rather than run CPU-heavy computation in the event loop.
Execution, status lookup, failure handling, artifact retrieval, and expiry are
planned behavior; `JobStatus` only describes the initial contract.

## Browser persistence and export

No accounts or durable server-side project storage are planned for the MVP.
The browser owns local persistence (preferably IndexedDB) and JSON export/import.
The backend validates incoming data before processing it.

Exports contain the versioned document and, when present, embedded reference image
data. They must remain usable after temporary backend uploads/results expire.
Large concentration arrays and temporary job/run references are excluded from the
default document; imported projects can rerun simulations. Future document format
changes should add explicit migrations and reject unsupported versions clearly.
Temporary storage needs a defined TTL and cleanup policy before deployment.

## Extensions and verification

Improved recognition stays in `floor_plans`; calibrated products stay in
`diffusers`. Furniture would extend geometry and obstacle preparation. Optimization
can become a separate domain that generates scenarios and calls the engine.
Room-specific targets can extend scenarios. Accounts/cloud saving can wrap the
portable document without making the solver depend on persistence.

Keep solver checks independent of recognition using `tests/fixtures/layouts/`.
Future checks should cover closed-wall isolation, open-door transport, conservation
without removal, expected decay with removal, source accounting, and resolution/
time-step behavior. API and job integration tests can follow their implementations.

Results represent approximate relative concentrations under stated assumptions.
Floor plans alone do not determine real airflow, product emission chemistry, or
perceived scent intensity.
