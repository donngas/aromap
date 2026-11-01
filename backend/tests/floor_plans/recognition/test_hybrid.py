import base64
from io import BytesIO
import json

import httpx2
from openai import OpenAI
from PIL import Image
import pytest

from app.floor_plans.models import RecognitionDraft
from app.floor_plans.recognition import hybrid
from app.floor_plans.recognition.interface import RecognitionError


def base():
    return RecognitionDraft.model_validate({"floor_plan": {"layout": {
        "id": "layout", "width_px": 200, "height_px": 120,
        "walls": [{"id": "w", "start": {"x": 0, "y": 40}, "end": {"x": 200, "y": 40}}],
        "doors": [{"id": "d", "wall_id": "w", "start": {"x": 20, "y": 40}, "end": {"x": 40, "y": 40}}],
        "windows": [{"id": "n", "wall_id": "w", "start": {"x": 80, "y": 40}, "end": {"x": 100, "y": 40}}],
    }}, "warnings": []})


def review(**updates):
    return hybrid.Review.model_validate(dict(wall_changes=[], opening_changes=[], domain_action="keep",
        indoor_domain=None, room_labels=[], warnings=[]) | updates)


def edit(**updates):
    return dict(action="add", target_id=None, region="full", start={"x": 120, "y": 40},
        end={"x": 140, "y": 40}, confidence="high", reason="Visible jambs and swing arc") | updates


def opening(**updates):
    return edit() | {"kind": "door", "wall_id": "w", "evidence": "swing_arc"} | updates


def test_noop_preserves_baseline_and_ids_without_mutation():
    original = base()
    snapshot = original.model_dump()
    result = hybrid.apply_review(original, review())
    assert result.floor_plan == original.floor_plan
    assert original.model_dump() == snapshot
    assert "applied 0" in result.warnings[-1]


def test_reclassifies_window_and_adds_missing_door_from_crop():
    result = hybrid.apply_review(base(), review(opening_changes=[
        opening(action="replace", target_id="N0", wall_id="W0", start={"x": 80, "y": 40}, end={"x": 100, "y": 40}),
        opening(region="top_right", start={"x": 30, "y": 40}, end={"x": 50, "y": 40}),
    ]))
    layout = result.floor_plan.layout
    assert not layout.windows and len(layout.doors) == 3
    assert {o.id for o in layout.doors} >= {"d", "n"}
    added = next(o for o in layout.doors if o.id not in {"d", "n"})
    assert (added.start.x, added.end.x) == (120, 140)
    assert all(o.wall_id == "w" for o in layout.doors)


@pytest.mark.parametrize("change", [
    opening(target_id="invented"), opening(action="replace", target_id="unknown"),
    opening(wall_id="missing"), opening(start={"x": -1, "y": 40}),
    opening(start={"x": 120, "y": 50}),
    opening(start={"x": 25, "y": 40}, end={"x": 35, "y": 40}),
    opening(region="top_right", start={"x": 150, "y": 40}), opening(confidence="uncertain"),
])
def test_unsupported_opening_edit_preserves_existing_draft(change):
    original = base()
    result = hybrid.apply_review(original, review(opening_changes=[change]))
    assert result.floor_plan == original.floor_plan
    assert any("skipped" in w.lower() or "rejected" in w.lower() for w in result.warnings)


def test_delete_false_opening_does_not_remove_its_wall():
    result = hybrid.apply_review(base(), review(opening_changes=[opening(
        action="remove", target_id="D0", kind=None, wall_id=None, start=None, end=None)]))
    layout = result.floor_plan.layout
    assert not layout.doors and len(layout.windows) == len(layout.walls) == 1


def test_wall_addition_nodes_junction_and_reparents_retained_openings():
    result = hybrid.apply_review(base(), review(wall_changes=[edit(
        start={"x": 150, "y": 40}, end={"x": 150, "y": 110})]))
    layout = result.floor_plan.layout
    assert len(layout.walls) == 3
    assert layout.doors[0].id == "d" and layout.windows[0].id == "n"
    for o in layout.doors + layout.windows:
        parent = next(w for w in layout.walls if w.id == o.wall_id)
        assert hybrid._line(parent).buffer(1e-6).covers(hybrid._line(o))


@pytest.mark.parametrize("change", [
    edit(action="remove", target_id="w", start=None, end=None),
    edit(start={"x": 30, "y": 40}, end={"x": 30, "y": 110}),
    edit(start={"x": 0, "y": 40}, end={"x": 200, "y": 40}),
    edit(action="replace", target_id="w", start={"x": 0, "y": 60}, end={"x": 200, "y": 60}),
])
def test_wall_edits_cannot_orphan_or_split_existing_openings(change):
    original = base()
    result = hybrid.apply_review(original, review(wall_changes=[change]))
    assert result.floor_plan == original.floor_plan
    assert any("rejected wall" in w for w in result.warnings)


def test_domain_and_room_label_validation():
    value = review(domain_action="replace", indoor_domain={"boundary": [
        {"x": 0, "y": 0}, {"x": 200, "y": 0}, {"x": 200, "y": 120}, {"x": 0, "y": 120}], "holes": []},
        room_labels=[{"name": "Kitchen", "position": {"x": 30, "y": 20}}])
    result = hybrid.apply_review(base(), value)
    assert result.floor_plan.layout.indoor_domain is not None
    assert result.floor_plan.layout.room_labels[0].name == "Kitchen"
    value.indoor_domain.boundary[2].x = -1
    rejected = hybrid.apply_review(result, value)
    assert rejected.floor_plan.layout.indoor_domain == result.floor_plan.layout.indoor_domain
    assert len(rejected.floor_plan.layout.room_labels) == 1


def test_sdk_review_contains_baseline_overlay_and_local_crops(tmp_path, monkeypatch):
    image = tmp_path / "image.png"
    Image.new("RGB", (200, 120), "white").save(image)
    original = base()
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(hybrid, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setattr(hybrid, "recognize_opencv", lambda _: original)
    calls = []

    def respond(request):
        body = json.loads(request.content)
        calls.append(body)
        assert body["model"] == "gpt-6-luna" and body["reasoning"] == {"effort": "none"}
        assert body["store"] is False and body["text"]["format"]["strict"] is True
        content = body["input"][0]["content"]
        context = json.loads(content[0]["text"])
        assert context["draft"]["floor_plan"]["layout"]["walls"][0]["id"] == "w"
        assert context["overlay_label_to_id"]["N0"] == "n"
        images = [item for item in content if item["type"] == "input_image"]
        crop_bounds = [v for k, v in context["region_bounds_global_px"].items() if k.startswith("roi_")]
        assert len(images) == 2 + len(crop_bounds)
        for i, item in enumerate(images):
            with Image.open(BytesIO(base64.b64decode(item["image_url"].split(",")[1]))) as im:
                box = crop_bounds[i - 2] if i >= 2 else (0, 0, 200, 120)
                assert im.size == (box[2] - box[0], box[3] - box[1])
        return httpx2.Response(200, json={"id": "resp", "object": "response", "created_at": 0,
            "status": "completed", "model": "gpt-6-luna", "output": [{"id": "msg", "type": "message",
            "role": "assistant", "status": "completed", "content": [{"type": "output_text",
            "text": review().model_dump_json(), "annotations": []}]}]})

    def client(**kwargs):
        assert kwargs["max_retries"] == 0
        return OpenAI(**kwargs, http_client=httpx2.Client(transport=httpx2.MockTransport(respond)))

    monkeypatch.setattr(hybrid, "OpenAI", client)
    result = hybrid.recognize_floor_plan(image)
    assert len(calls) == 1 and result.floor_plan == original.floor_plan


def test_review_failure_is_sanitized(tmp_path, monkeypatch, caplog):
    from unittest.mock import MagicMock
    image = tmp_path / "image.png"
    Image.new("RGB", (200, 120)).save(image)
    monkeypatch.setattr(hybrid, "recognize_opencv", lambda _: base())
    monkeypatch.setattr(hybrid, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    client = MagicMock()
    client.__enter__.return_value = client
    client.responses.parse.side_effect = TimeoutError("private image/provider details")
    monkeypatch.setattr(hybrid, "OpenAI", lambda **k: client)
    with pytest.raises(RecognitionError, match="Hybrid floor-plan recognition failed"):
        hybrid.recognize_floor_plan(image)
    assert "category=timeout" in caplog.text and "private image/provider details" not in caplog.text


@pytest.mark.parametrize("evidence", ["fixed_glazing", "uncertain"])
def test_opening_type_change_requires_door_evidence(evidence):
    original = base()
    result = hybrid.apply_review(original, review(opening_changes=[opening(
        action="replace", target_id="N0", start={"x": 80, "y": 40}, end={"x": 100, "y": 40},
        evidence=evidence)]))
    assert result.floor_plan == original.floor_plan
    assert any("rejected unsupported" in w for w in result.warnings)



def test_identical_replacements_do_not_count_as_corrections_or_reorder_geometry():
    original = base()
    value = review(opening_changes=[opening(action="replace", target_id="D0",
        start={"x": 20, "y": 40}, end={"x": 40, "y": 40})], wall_changes=[edit(
        action="replace", target_id="W0", start={"x": 0, "y": 40}, end={"x": 200, "y": 40})])
    result = hybrid.apply_review(original, value)
    assert result.floor_plan == original.floor_plan
    assert "applied 0" in result.warnings[-1]



def test_moved_wall_and_overlapping_added_aperture_are_rejected_atomically():
    original = base()
    value = review(wall_changes=[edit(action="replace", target_id="w", start={"x": 0, "y": 42}, end={"x": 200, "y": 42})],
        opening_changes=[opening(kind="window", evidence="fixed_glazing", start={"x": 20, "y": 42}, end={"x": 40, "y": 42})])
    result = hybrid.apply_review(original, value)
    assert result.floor_plan == original.floor_plan
    assert any("opening_overlap" in w for w in result.warnings)
    assert not any("Hybrid applied" in w for w in result.warnings)


def test_independent_group_projects_retained_apertures_before_overlap_check():
    original = base()
    value = review(edit_groups=[
        {"wall_changes": [edit(action="replace", target_id="w", start={"x": 0, "y": 42}, end={"x": 200, "y": 42})], "opening_changes": []},
        {"wall_changes": [], "opening_changes": [opening(kind="window", evidence="fixed_glazing", start={"x": 20, "y": 42}, end={"x": 40, "y": 42})]},
    ])
    result = hybrid.apply_review(original, value)
    assert result.floor_plan.layout.doors[0].start.y == 42
    assert len(result.floor_plan.layout.windows) == 1
    assert any("opening_overlap" in w for w in result.warnings)


def test_coordinated_wall_and_opening_deletion_succeeds():
    value = review(wall_changes=[edit(action="remove", target_id="W0", start=None, end=None)], opening_changes=[
        opening(action="remove", target_id=target, start=None, end=None, kind=None, wall_id=None, evidence=None)
        for target in ["D0", "N0"]])
    result = hybrid.apply_review(base(), value)
    layout = result.floor_plan.layout
    assert not layout.walls and not layout.doors and not layout.windows
    assert "applied 3" in result.warnings[-1]


def test_joint_wall_and_opening_relocation_beyond_rounding_tolerance():
    value = review(edit_groups=[{"wall_changes": [edit(action="replace", target_id="W0",
        start={"x": 0, "y": 80}, end={"x": 200, "y": 80})], "opening_changes": [
        opening(action="replace", target_id="D0", start={"x": 20, "y": 80}, end={"x": 40, "y": 80}),
        opening(action="replace", target_id="N0", kind="window", evidence="fixed_glazing", start={"x": 80, "y": 80}, end={"x": 100, "y": 80}),
    ]}])
    layout = hybrid.apply_review(base(), value).floor_plan.layout
    assert layout.walls[0].start.y == layout.doors[0].start.y == layout.windows[0].start.y == 80
    assert layout.doors[0].id == "d" and layout.windows[0].id == "n"


def test_group_rollback_preserves_successful_earlier_edit_when_later_edit_fails():
    original = base()
    value = review(edit_groups=[{"wall_changes": [], "opening_changes": [
        opening(action="remove", target_id="D0", start=None, end=None, kind=None, wall_id=None, evidence=None),
        opening(start={"x": -1, "y": 40}),
    ]}])
    result = hybrid.apply_review(original, value)
    assert result.floor_plan == original.floor_plan


def test_new_parent_reference_and_relative_aperture_in_one_group():
    value = review(edit_groups=[{"wall_changes": [edit(new_ref="new_partition",
        start={"x": 150, "y": 40}, end={"x": 150, "y": 100})], "opening_changes": [
        opening(wall_id="new_partition", wall_span=[.2, .5], start=None, end=None),
    ]}])
    layout = hybrid.apply_review(base(), value).floor_plan.layout
    assert len(layout.doors) == 2
    new = next(o for o in layout.doors if o.id != "d")
    assert new.start.x == new.end.x == 150
    assert (new.start.y, new.end.y) == (52, 70)
    assert new.wall_id in {w.id for w in layout.walls}


def test_type_only_correction_keeps_jamb_coordinates():
    original = base()
    value = review(opening_changes=[opening(action="replace", target_id="N0", start=None, end=None)])
    result = hybrid.apply_review(original, value)
    corrected = next(o for o in result.floor_plan.layout.doors if o.id == "n")
    assert corrected.start == original.floor_plan.layout.windows[0].start
    assert corrected.end == original.floor_plan.layout.windows[0].end


@pytest.mark.parametrize("span", [[-.1,.5],[.2,1.1],[.5,.5],[float("nan"),.5]])
def test_invalid_relative_span_rejected(span):
    original = base()
    result = hybrid.apply_review(original, review(opening_changes=[opening(wall_span=span, start=None, end=None)]))
    assert result.floor_plan == original.floor_plan
