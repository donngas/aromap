# Recognition improvement assessment — 2026-11-01

## Hybrid fixes and repair experiment

The hybrid provider now validates overlaps after every aperture has been projected
onto the candidate wall geometry. Related wall/opening edits are staged and
validated atomically; invalid groups roll back completely. Temporary references
allow new walls and their dependent openings in one group. Legacy flat reviews
with wall changes also form a transaction, fixing coordinated deletion/movement
without requiring an old client to change its payload.

Type-only opening corrections can preserve existing jamb coordinates. Optional
`wall_span` endpoints refer to fractions along a known wall. Source crops now focus
on existing apertures and possible gaps, rather than always using four quadrants.
No changes were made to default OpenCV routing or the LLM-only option in this work.

Regression tests cover the reproduced projection-overlap defect, coordinated
wall/opening deletion and relocation, failed-group rollback, temporary references,
relative positions, crop conversion and no-op preservation. Full backend suite:
**307 passed, 10 skipped**.

Eight live reviews ran inside Docker project `aromap-dev`, using the previously
authorized CAD, colored-home and cafe images. Review used GPT-6 Luna with reasoning
`none`, a strict structured schema, source/overlay images and focused crops.
Five drafts were deliberately corrupted without revealing the injected defect to
the reviewer; three unchanged drafts were preservation controls. The evaluator
called the same `review_draft` function used by the hybrid provider, rather than
claiming the corruptions came naturally from OpenCV or changing production data.

| Input draft | Result |
| --- | --- |
| CAD, correct | Preserved all known openings |
| CAD, interior door removed | Not repaired |
| CAD, window mislabeled as door | Correctly reclassified; original jambs preserved |
| CAD, door aperture shortened by 30 px | Not repaired |
| CAD, partition and its attached door removed | Not repaired; reviewer abstained despite new-wall/group support |
| Colored home, correct | Preserved all known openings |
| Colored home, sliding door mislabeled as window | Not repaired |
| Cafe, correct | Preserved all known openings |

All eight reviews completed. One of five defects was repaired. All 18 checked
opening landmarks in the clean controls remained within five pixels. Median
review time was 3.03 seconds; maximum 5.83 seconds. These are small exploratory
samples, not independent estimates of general accuracy or a direct latency
comparison with the earlier differently composed suite. No token/cost benchmark
was collected. Source-derived before/after drafts and structured review patches
were saved under `/tmp/aromap-hybrid-fix/results` on the evaluation host.

The fixes make application of edits more reliable, but this configuration has not
shown reliable reconstruction of missing geometry. It can be useful for some
classification errors; it is not established as a general improvement over the
classic recognizer. Prioritize classic geometry work rather than more broad prompt
expansion with this model/reasoning setting.

## Classic detector sensitivity

The assessment concerns **drawn pixel stroke width**, not physical wall thickness
in meters. The public draft contains zero-thickness centerlines; metric scale is
owned by user calibration.

Twenty-three noiseless procedural plans varied uniform stroke width, mixed
exterior/interior widths, page rotation, and image scale. Six more cases checked
true oblique connections and a detector-only feasibility probe. Ground truth was
the drawn centerline graph. Wall recall is length within three pixels of predicted
lines (scaled proportionally for the resolution sweep). Enclosed-region counts
also check whether recovered segments form the intended topology.

- Uniform requested OpenCV line widths 2–40 recovered all expected centerline
  length; one-pixel lines failed. Raster line widths can exceed the requested
  `cv2.line` width, so this does not establish reliable two-raster-pixel detection.
- Consistent geometric/stroke scaling from 0.5× to 4× retained full centerline
  recall. The existing global size normalization already handles these clean
  uniform examples reasonably well.
- With requested exterior/interior widths 20/2, 20/4, 40/4 or 40/8, the interior
  partition essentially disappeared: approximately 1.5% of its length was within
  three pixels of recovered outer walls, and only one enclosed region remained
  instead of two. An 8/20 case also lost the thicker interior partition.
- Uniformly rotating the plan by 2°, 5°, 10°, 15° or 45° yielded no recovered walls.
  At 30°, only about 6% of expected wall length was recovered and the output did
  not enclose the plan. This is a page-orientation limitation in addition to the
  separate inability to represent genuine non-right-angle junctions.
- True non-right-angle cases confirmed that distinction:

| Geometry | Classic wall recall | Closed topology |
| --- | ---: | --- |
| Chamfered corner | 94.3% | Outer loop broken |
| Trapezoid | 56.6% | Outer loop broken |
| Diagonal partition inside rectangle | 80.1% | One region instead of two |
| Oblique T-junction | 91.6% | Two regions instead of three |

The causes are explicit in the source:

- `preprocess.estimate_wall_thickness` selects one dominant width, weighted by
  width squared. `_thick_strokes` removes strokes using a kernel derived from
  that single width, with a three-pixel minimum. Thin partitions can disappear.
- `walls.MAX_THICKNESS_RATIO` rejects components wider than twice that estimated
  width, so sufficiently thick secondary walls can disappear too.
- `WallSegment` has only horizontal/vertical orientations. Wall coverage,
  directional morphology, snapping, junction splitting and opening association
  depend on those orientations. Changing only a threshold cannot add general
  angled-wall support.

## Feasible direction for classic improvement

A standalone distance-transform-ridge plus unrestricted Hough-line probe recovered
97.8–100% of expected wall length within three pixels across the six difficult
mixed-width/angled cases, with 100% line precision on those clean images. It used
local ridges rather than a single global stroke-width cutoff. **It did not produce
closed topology:** fragmented/noisy line endpoints still require merging, snapping
and intersection handling. It has not been validated against furniture, text,
scanned noise, doors or windows. The probe is an indication of detector feasibility,
not a replacement ready to serve requests. Artifacts are under
`/tmp/aromap-classic-assessment` on the evaluation host.

A practical implementation order is:

1. Preserve multiple plausible local stroke widths, using distance-transform
   profiles and multiple extraction scales. Score thin connected partitions and
   thick walls separately from short text/furniture strokes. Avoid merely lowering
   the global cutoff, which would admit substantial clutter.
2. Add dominant-angle deskewing for uniformly rotated pages, mapping every result
   back to the prepared-image coordinate system. Deskewing alone does not fix
   chamfers, trapezoids or oblique internal partitions.
3. Represent internal wall centerlines by arbitrary endpoints/directions. Extract
   arbitrary-angle segments, merge collinear fragments and resolve general
   intersections/T-junctions with thickness-aware bounded snapping. Keep existing
   pixel-space output DTOs, which already support arbitrary endpoints.
4. Analyze opening candidates in a wall-local rotated frame, reusing glazing/leaf
   checks where possible, then map apertures back and assign them after junction
   splitting. Gap limits and matching tolerances should depend on local width.
5. Preserve the current orthogonal path until the new path passes held-out mixed-
   width, skewed and oblique plans, plus negative controls with furniture, text,
   faint arcs and grids. Measure false wall additions and closed topology as well
   as centerline recall. Compare runtime and keep image-size limits.

The initial probe supported a classic upgrade. The implementation and subsequent
validation below supersede that initial feasibility-only conclusion.


## Implemented classic improvements

The default classic route now keeps the orthogonal detector as its baseline and
conservatively supplements it with local distance-transform ridges and arbitrary-
angle Hough proposals. Collinear merging requires source ink support; bounded
intersection snapping makes a shared wall graph. New partitions must attach at
both ends and produce substantial enclosed regions inside the existing footprint.
The fallback requires a substantial closed envelope. Opening parents are protected
when trimming short diagonal-end artifacts; ambiguous reassociation retains the
original draft. Proposal extraction is limited to a 2000-pixel image and 256 lines.

Uniformly rotated plans with a failed baseline footprint can be rectified and run
through the existing door/window detector. Bounded supersampling and cubic
interpolation preserve faint swing arcs. Detected jambs are refined from dense
wall ink, with bounded changes, before all geometry is mapped back to original
pixel coordinates. This does not add opening detection along truly oblique walls.

The 25 targeted regression cases cover five mixed-width plans, four true oblique
layouts, seven rotated CAD plans, seven existing fixture preservation checks, and
one blank/light-grid negative-control test, plus an aperture-overlap guard test. Mixed-width and oblique plans exceed
99% wall precision and recall within three pixels and have the expected enclosed
region counts. All seven rotated CAD plans (-10, -2, 2, 5, 15, 30 and 45 degrees)
retain both doors and the window within five pixels of transformed ground truth.
The seven repository fixtures preserve baseline geometry and warnings exactly.

These controlled results support integrating the classic improvements for clean,
reasonable plans. They are not an accuracy estimate on unseen architectural
styles or scans. Large furniture outlines remain a semantic ambiguity; arbitrary-
angle openings, faint walls and one-pixel partitions remain limitations. A next
validation step is a small held-out set of representative real customer plans
with annotated wall graphs and apertures. If those expose semantic failures,
floor-plan-specific wall/door/window segmentation followed by deterministic
vectorization is a more relevant next experiment than further broad LLM review.
A learned line detector alone would still need to distinguish furniture and walls.


The repeated 23-case clean-line sweep recovered 100% wall precision/recall and the
expected two enclosed regions in all 22 cases with requested stroke widths at
least two pixels. The one-pixel control remained undetected. This sweep includes
six mixed-width cases, six rotations and three image scales; tolerance is three
pixels at nominal scale, proportional for the scale sweep. Local single-run
runtime ranged from 0.020 to 0.350 seconds (median 0.075 seconds); these are
procedural images, not production latency estimates. Artifacts:
`/tmp/aromap-classic-assessment/final-sweep.jsonl`.

Final backend regression suite after classic integration and aperture-overlap
guards: **332 passed, 10 skipped**. No live LLM calls were needed for these classic
experiments.
