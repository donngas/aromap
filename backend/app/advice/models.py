"""Draft advice contracts; no provider or generation behavior is selected."""

from pydantic import BaseModel, Field

from app.simulations.models import SimulationConfiguration


class AdviceRequest(BaseModel):
    configuration: SimulationConfiguration
    input_fingerprint: str
    simulation_run_id: str | None = None
    question: str | None = None


class Suggestion(BaseModel):
    recommendation: str
    reason: str


class AdviceResponse(BaseModel):
    input_fingerprint: str
    suggestions: list[Suggestion]
    limitations: list[str] = Field(default_factory=list)
