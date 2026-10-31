import json
import io
import time

import numpy as np
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


@pytest.mark.parametrize("mutate", [
    lambda x: x["placements"][0].update(definition_id="missing"),
    lambda x: x["placements"][1].update(placement_id="A1"),
    lambda x: x["opening_states"][0].update(opening_id="missing"),
    lambda x: x["geometry_m"]["windows"][0].update(wall_id="missing"),
])
def test_configuration_references_are_validated(mutate):
    body = example("request")
    mutate(body)
    with pytest.raises(ValidationError):
        SimulationRequest.model_validate(body)


def test_result_channel_mapping_and_shape():
    result = SimulationResult.model_validate(example("result"))
    assert result.fields.shape == (11, 3, 16, 24)
    assert [channel.placement_id for channel in result.channels] == ["A1", "A2", "B1"]
    assert result.channels[0].definition_id == result.channels[1].definition_id


@pytest.mark.parametrize("mutate", [
    lambda x: x["fields"].update(shape=[11, 2, 16, 24]),
    lambda x: x["fields"]["active_domain_mask"].update(shape=[24, 16]),
    lambda x: x["channels"][1].update(placement_id="A1"),
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


def test_simulation_endpoints_and_swagger(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        body = example("request")
        body["settings"].update(duration_s=1, sample_interval_s=1)
        response = client.post("/api/simulations", json=body)
        assert response.status_code == 202
        accepted = response.json()
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            status = client.get(accepted["status_url"]).json()
            if status["state"] in ("succeeded", "failed"):
                break
            time.sleep(0.05)
        assert status["state"] == "succeeded", status
        result = status["result"]
        fields = client.get(result["fields"]["url"])
        assert fields.status_code == 200
        with np.load(io.BytesIO(fields.content), allow_pickle=False) as arrays:
            assert list(arrays["concentration"].shape) == result["fields"]["shape"]
            assert arrays["active_domain_mask"].dtype == np.bool_
            assert arrays["concentration"][-1].sum() > 0
        invalid = example("request")
        invalid["placements"][0]["definition_id"] = "missing"
        assert client.post("/api/simulations", json=invalid).status_code == 422
        unknown = client.get("/api/simulations/unknown/fields")
        assert unknown.status_code == 404
        assert unknown.json()["detail"]["code"] == "result_not_found"
        assert client.get("/api/simulations/unknown").status_code == 404
        schema = client.get("/openapi.json").json()
        assert schema["paths"]["/api/simulations"]["post"]["responses"]["202"]
        assert "SimulationResult" in schema["components"]["schemas"]
        assert "/api/simulations/{job_id}/mask" not in schema["paths"]


def test_preparation_failure_is_reported_as_job_error(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        body = example("request")
        for placement in body["placements"]:
            placement["enabled"] = False
        accepted = client.post("/api/simulations", json=body)
        assert accepted.status_code == 202
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            status = client.get(accepted.json()["status_url"]).json()
            if status["state"] in ("succeeded", "failed"):
                break
            time.sleep(0.05)
        assert status["state"] == "failed"
        assert status["error"]["code"] == "no_sources"
        assert client.get(accepted.json()["status_url"] + "/fields").status_code == 404
