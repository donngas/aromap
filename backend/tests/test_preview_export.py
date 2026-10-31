"""The preview remains a standalone bounded artifact, separate from HTTP encoding."""

import base64
import json
import re

import numpy as np
import pytest

from app.simulations.models import SimulationConfiguration
from scripts.preview_simulation import export_preview


def configuration():
    return SimulationConfiguration.model_validate({
        "geometry_m": {"indoor_domain": {"boundary": [
            {"x": 0, "y": 0}, {"x": 1, "y": 0}, {"x": 1, "y": 1}, {"x": 0, "y": 1},
        ]}},
        "diffuser_definitions": [{"id": "A", "name": "Reed", "diffuser_type": "reed"}],
        "placements": [{"placement_id": "A1", "definition_id": "A", "position_m": {"x": .125, "y": .125}}],
        "settings": {"duration_s": 1, "sample_times_s": [0, 1]},
    })


def test_preview_embeds_portable_fields_and_escapes_html(tmp_path):
    destination = tmp_path / "preview.html"
    summary = export_preview(configuration(), destination, title="</script><script>bad()</script>", scale_max=8)
    html = destination.read_text()
    embedded = re.search(r'<script type="application/json" id="simulation">(.*?)</script>', html, re.S).group(1)
    payload = json.loads(embedded)
    assert payload["title"] == "</script><script>bad()</script>"
    assert "<script>bad()" not in html
    assert "fetch(" not in html and "__AROMAP_PAYLOAD__" not in html
    fields = np.frombuffer(base64.b64decode(payload["fields"]), dtype="<f4").reshape(payload["shape"])
    assert fields.shape == (2, 1, 4, 4) and not fields[0].any() and fields[-1].sum() > 0
    assert len(base64.b64decode(payload["mask"])) == 16
    neighbors = np.frombuffer(base64.b64decode(payload["neighbors"]), dtype="<i4").reshape(16, 4)
    assert neighbors[0].tolist() == [-1, 1, -1, 4]
    assert payload["scaleMax"] == 8
    assert summary["final_snapshot_quantity"] == pytest.approx(payload["quantities"][-1][0])


def test_preview_rejects_oversize_before_numerical_execution(tmp_path, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("A rejected preview must not run the solver")
    monkeypatch.setattr("scripts.preview_simulation.simulate", unexpected)
    with pytest.raises(ValueError, match="size limit"):
        export_preview(configuration(), tmp_path / "large.html", max_preview_mib=.000001)
    with pytest.raises(ValueError, match="Color scale"):
        export_preview(configuration(), tmp_path / "bad.html", scale_max=float("nan"))
    with pytest.raises(ValueError, match="extension"):
        export_preview(configuration(), tmp_path / "input.json")


def test_display_interpolation_does_not_connect_across_a_closed_wall(tmp_path):
    config = configuration()
    body = config.model_dump()
    body["geometry_m"]["walls"] = [{"id": "divider", "start": {"x": .5, "y": 0}, "end": {"x": .5, "y": 1}}]
    destination = tmp_path / "wall.html"
    export_preview(SimulationConfiguration.model_validate(body), destination)
    payload = json.loads(re.search(r'id="simulation">(.*?)</script>', destination.read_text(), re.S).group(1))
    neighbors = np.frombuffer(base64.b64decode(payload["neighbors"]), dtype="<i4").reshape(16, 4)
    assert all(neighbors[row*4+1, 1] == -1 and neighbors[row*4+2, 0] == -1 for row in range(4))
