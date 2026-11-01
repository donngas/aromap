import base64
import json

import httpx2
import pytest
from openai import OpenAI
from PIL import Image

from app.floor_plans.recognition import llm
from app.floor_plans.recognition.interface import RecognitionError


def extraction(**changes):
    value = dict(walls=[{"start": {"x": 0, "y": 4}, "end": {"x": 12, "y": 4}}],
                 openings=[{"wall_index": 0, "kind": "door", "start": {"x": 1, "y": 4},
                            "end": {"x": 3, "y": 4}}], room_labels=[], indoor_domain=None, warnings=[])
    value.update(changes)
    return llm.Extraction.model_validate(value)


def test_sdk_image_request_and_structured_conversion(tmp_path, monkeypatch):
    path = tmp_path / "image.png"
    Image.new("RGB", (12, 8)).save(path)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(llm, "load_dotenv", lambda *a, **k: None)
    calls = []

    def respond(request):
        body = json.loads(request.content)
        calls.append(body)
        assert str(request.url) == "https://api.openai.com/v1/responses"
        assert body["model"] == "gpt-6-luna"
        assert body["reasoning"] == {"effort": "none"}
        assert body["store"] is False
        content = body["input"][0]["content"]
        assert "12 x 8" in content[0]["text"]
        assert base64.b64decode(content[1]["image_url"].split(",")[1]) == path.read_bytes()
        assert body["text"]["format"]["strict"] is True
        assert body["text"]["format"]["schema"]["additionalProperties"] is False
        return httpx2.Response(200, json={
            "id": "resp_test", "object": "response", "created_at": 0, "status": "completed",
            "model": "gpt-6-luna", "output": [{"id": "msg_test", "type": "message",
                "role": "assistant", "status": "completed", "content": [{"type": "output_text",
                    "text": extraction().model_dump_json(), "annotations": []}]}],
        })

    def client(**kwargs):
        assert kwargs["max_retries"] == 0
        return OpenAI(**kwargs, http_client=httpx2.Client(transport=httpx2.MockTransport(respond)))

    monkeypatch.setattr(llm, "OpenAI", client)
    draft = llm.recognize_floor_plan(path)
    layout = draft.floor_plan.layout
    assert len(calls) == 1
    assert layout.doors[0].wall_id == layout.walls[0].id
    assert layout.calibration is None and draft.floor_plan.reference_image is None
    assert layout.revision == 1 and (layout.width_px, layout.height_px) == (12, 8)
    assert draft.warnings


def test_nodes_crossings_and_preserves_opening_reference():
    value = extraction()
    value.walls.append(llm.Segment(start=llm.ImagePoint(x=6, y=0), end=llm.ImagePoint(x=6, y=8)))
    draft = llm.to_draft(value, 12, 8)
    layout = draft.floor_plan.layout
    assert len(layout.walls) == 4
    parent = next(w for w in layout.walls if w.id == layout.doors[0].wall_id)
    assert parent.start.x == 0 and parent.end.x == 6
    value.openings[0].end.x = 8
    draft = llm.to_draft(value, 12, 8)
    assert not draft.floor_plan.layout.doors
    assert any("junction" in warning for warning in draft.warnings)


@pytest.mark.parametrize("mutation", ["bounds", "nan", "zero", "reference", "off_wall", "polygon"])
def test_invalid_geometry_rejected(mutation):
    value = extraction()
    if mutation == "bounds":
        value.walls[0].start.x = -1
    elif mutation == "nan":
        value.walls[0].start.x = float("nan")
    elif mutation == "zero":
        value.walls[0].end = value.walls[0].start
    elif mutation == "reference":
        value.openings[0].wall_index = 2
    elif mutation == "off_wall":
        value.openings[0].start.y = 0
    else:
        value.indoor_domain = llm.IndoorDomain(boundary=[llm.ImagePoint(x=0, y=0),
            llm.ImagePoint(x=4, y=4), llm.ImagePoint(x=0, y=4), llm.ImagePoint(x=4, y=0)], holes=[])
    with pytest.raises(ValueError):
        llm.to_draft(value, 12, 8)


def test_valid_footprint_and_labels():
    value = extraction(indoor_domain={"boundary": [{"x": 0, "y": 0}, {"x": 12, "y": 0},
        {"x": 12, "y": 8}, {"x": 0, "y": 8}], "holes": []},
        room_labels=[{"name": "Cafe", "position": {"x": 2, "y": 2}}])
    layout = llm.to_draft(value, 12, 8).floor_plan.layout
    assert len(layout.indoor_domain.boundary) == 4
    assert layout.room_labels[0].name == "Cafe"


def test_missing_key_does_not_call_api(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(llm, "OpenAI", lambda **k: pytest.fail("API called without key"))
    with pytest.raises(RecognitionError, match="OPENAI_API_KEY"):
        llm.recognize_floor_plan(tmp_path / "unused.png")


@pytest.mark.parametrize("mode,category", [
    ("refusal", "refusal"), ("incomplete", "incomplete_output"),
    ("timeout", "timeout"), ("invalid", "invalid_geometry"),
    ("authentication", "authentication"), ("rate_limit", "rate_limit"),
    ("bad_json", "invalid_structured_output"),
])
def test_provider_failures_are_sanitized(tmp_path, monkeypatch, caplog, mode, category):
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    path = tmp_path / "image.png"
    Image.new("RGB", (12, 8)).save(path)
    monkeypatch.setattr(llm, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    client = MagicMock()
    client.__enter__.return_value = client
    if mode in {"authentication", "rate_limit"}:
        from openai import AuthenticationError, RateLimitError
        error = AuthenticationError if mode == "authentication" else RateLimitError
        client.responses.parse.side_effect = error(
            "sensitive provider body", response=httpx2.Response(
                401 if mode == "authentication" else 429,
                request=httpx2.Request("POST", "https://api.openai.com/v1/responses")),
            body={"secret": "sensitive provider body"})
    elif mode == "bad_json":
        client.responses.parse.side_effect = ValueError("sensitive provider body")
    elif mode == "timeout":
        client.responses.parse.side_effect = TimeoutError("sensitive provider body")
    else:
        value = extraction()
        value.walls[0].start.x = -1
        client.responses.parse.return_value = SimpleNamespace(
            status="incomplete" if mode == "incomplete" else "completed",
            output_parsed=value if mode == "invalid" else None,
            output=[SimpleNamespace(type="message", content=[SimpleNamespace(type="refusal")])])
    monkeypatch.setattr(llm, "OpenAI", lambda **k: client)
    with pytest.raises(RecognitionError, match="LLM floor-plan recognition failed") as exc:
        llm.recognize_floor_plan(path)
    assert exc.value.__suppress_context__
    assert f"category={category}" in caplog.text
    assert "sensitive provider body" not in caplog.text
    assert "test-key" not in caplog.text
    assert str(path) not in caplog.text


@pytest.mark.parametrize("gap,expected_warning", [(0, False), (0.5, True), (1.0, True), (1.01, False)])
def test_near_missed_junction_warning_is_bounded(gap, expected_warning):
    value = extraction()
    value.walls.append(llm.Segment(start=llm.ImagePoint(x=6, y=4 + gap),
                                  end=llm.ImagePoint(x=6, y=8)))
    draft = llm.to_draft(value, 12, 8)
    junction_warnings = [w for w in draft.warnings if "disconnected junction" in w]
    assert bool(junction_warnings) is expected_warning
    # Warnings preserve intentional gaps and the original wall references.
    assert len(draft.floor_plan.layout.walls) == (3 if gap == 0 else 2)
    assert len(draft.floor_plan.layout.doors) == 1
    if gap:
        assert any(w.start.y == 4 + gap for w in draft.floor_plan.layout.walls)
