import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings
from app.main import create_app
from app.simulations.schemas import SimulationRequest, SimulationResult, SimulationStatus

FIXTURES = Path(__file__).parent / "fixtures" / "simulations"


def example(name):
    return json.loads((FIXTURES / f"{name}.json").read_text())


def test_request_round_trip_and_sampling_choices():
    request = SimulationRequest.model_validate(example("request"))
    assert SimulationRequest.model_validate_json(request.model_dump_json()) == request
    assert request.placements[0].position_m.x == 1
    assert request.diffuser_definitions[0].capacity == 200
    body = example("request")
    del body["settings"]["sample_interval_s"]
    body["settings"]["sample_times_s"] = [0, 30, 600]
    assert SimulationRequest.model_validate(body).settings.sample_times_s == [0, 30, 600]


@pytest.mark.parametrize("mutate", [
    lambda x: x.update(calibration={"distance_m": 1}),
    lambda x: x["placements"][0].update(position_px={"x": 10, "y": 20}),
    lambda x: x["placements"][0].update(definition_id="missing"),
    lambda x: x["placements"][1].update(placement_id="A1"),
    lambda x: x["opening_states"][0].update(opening_id="missing"),
    lambda x: x["geometry_m"]["windows"][0].update(wall_id="missing"),
    lambda x: x["settings"].update(sample_times_s=[0, 60]),
    lambda x: x["settings"].update(duration_s=-1),
    lambda x: x["placements"][0]["position_m"].update(x=float("nan")),
    lambda x: x["diffuser_definitions"][0].update(capacity_unit=None),
])
def test_invalid_configuration_is_rejected(mutate):
    body = example("request")
    mutate(body)
    with pytest.raises(ValidationError):
        SimulationRequest.model_validate(body)


def test_result_channel_mapping_and_shape():
    result = SimulationResult.model_validate(example("result"))
    assert result.fields.shape == (11, 3, 16, 24)
    assert [channel.placement_id for channel in result.channels] == ["A1", "A2", "B1"]
    assert result.channels[0].definition_id == result.channels[1].definition_id
    assert SimulationResult.model_validate_json(result.model_dump_json()) == result


@pytest.mark.parametrize("mutate", [
    lambda x: x["fields"].update(shape=[11, 2, 16, 24]),
    lambda x: x["active_domain_mask"].update(shape=[24, 16]),
    lambda x: x["channels"][1].update(placement_id="A1"),
    lambda x: x.update(sample_times_s=[0] * 11),
])
def test_result_metadata_invariants(mutate):
    body = example("result")
    mutate(body)
    with pytest.raises(ValidationError):
        SimulationResult.model_validate(body)


def test_status_lifecycle_contract():
    body = {
        "job_id": "job", "client_request_id": "request", "state": "queued",
        "created_at": "2026-10-31T09:00:00Z", "updated_at": "2026-10-31T09:00:00Z",
        "expires_at": "2026-11-01T09:00:00Z",
    }
    assert SimulationStatus.model_validate(body).result is None
    with pytest.raises(ValidationError):
        SimulationStatus.model_validate({**body, "state": "succeeded"})
    assert SimulationStatus.model_validate({**body, "state": "succeeded", "result": example("result")}).result
    assert SimulationStatus.model_validate({**body, "state": "failed", "error": {
        "code": "simulation_failed", "message": "Could not finish",
    }}).error


def test_placeholder_endpoints_and_swagger(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        response = client.post("/api/simulations", json=example("request"))
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "simulation_unavailable"
        with sqlite3.connect(tmp_path / "registry.sqlite3") as db:
            assert db.execute("SELECT COUNT(*) FROM jobs WHERE kind='simulation'").fetchone()[0] == 0
        invalid = example("request")
        invalid["placements"][0]["definition_id"] = "missing"
        assert client.post("/api/simulations", json=invalid).status_code == 422
        for suffix in ("", "/fields", "/mask"):
            assert client.get(f"/api/simulations/unknown{suffix}").status_code == 404
        schema = client.get("/openapi.json").json()
        assert schema["paths"]["/api/simulations"]["post"]["responses"]["202"]
        assert "SimulationResult" in schema["components"]["schemas"]
        assert "image" not in schema["components"]["schemas"]["SimulationRequest"]["properties"]
