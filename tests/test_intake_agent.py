"""The intake agent's model chain: fallback when a free-tier model is overloaded.

No network: the chain is built with fake keys and exercised with Pydantic AI's
FunctionModel / TestModel, never a real provider.
"""

from __future__ import annotations

import httpx
import pytest
from orviqo.agents.intake import FALLBACK_ON, build_model
from orviqo.domain.intake import IntakeAction
from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.test import TestModel


@pytest.fixture(autouse=True)
def _fake_google_key(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")


def test_one_model_string_builds_that_model() -> None:
    model = build_model("google:gemini-flash-latest")
    assert isinstance(model, GoogleModel)
    assert model.model_name == "gemini-flash-latest"


def test_a_list_builds_a_fallback_chain_in_order() -> None:
    model = build_model("google:gemini-flash-latest, google:gemini-flash-lite-latest")
    assert isinstance(model, FallbackModel)
    assert [m.model_name for m in model.models] == [
        "gemini-flash-latest",
        "gemini-flash-lite-latest",
    ]


def _failing(error: Exception) -> FunctionModel:
    def respond(messages, info):
        raise error

    return FunctionModel(respond)


@pytest.mark.parametrize(
    "error",
    [
        ModelHTTPError(503, "gemini-flash-latest", {"error": {"status": "UNAVAILABLE"}}),
        httpx.ReadTimeout("timed out"),
    ],
    ids=["overloaded", "timeout"],
)
async def test_an_overloaded_or_slow_model_falls_back_to_the_next(error: Exception) -> None:
    chain = FallbackModel(_failing(error), TestModel(), fallback_on=FALLBACK_ON)
    agent = Agent(chain, output_type=IntakeAction)

    result = await agent.run("Chidi owes 50k")

    assert isinstance(result.output, IntakeAction)  # answered by the second model
