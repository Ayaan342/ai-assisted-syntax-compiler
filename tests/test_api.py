from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from ai.correction_orchestrator import CorrectionOrchestrator
from ai.dataset_generator import CorrectionClass
from ai.error_predictor import ErrorPrediction
from ai.llm_fallback import LLMFallbackResult, LLMSuggestion
from backend.app.dependencies import ModelUnavailableError, get_orchestrator
from backend.app.main import app
from compiler.correction import CorrectionAction


class FixedPredictor:
    def __init__(self, confidence: float) -> None:
        self.prediction = ErrorPrediction(
            CorrectionClass.INSERT_RPAREN.value,
            confidence,
            {CorrectionClass.INSERT_RPAREN.value: confidence},
        )

    def predict_error_type(self, context):
        return self.prediction


class FakeFallback:
    model = "mock-groq"

    def __init__(self, result: LLMFallbackResult) -> None:
        self.result = result
        self.calls = 0

    def suggest(self, context, prediction):
        self.calls += 1
        return self.result


@pytest.fixture(autouse=True)
def clear_dependency_overrides():
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


def request(method: str, path: str, **kwargs) -> httpx.Response:
    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(send())


def use_orchestrator(orchestrator: CorrectionOrchestrator) -> None:
    app.dependency_overrides[get_orchestrator] = lambda: orchestrator


def test_health_endpoint_reports_only_safe_readiness() -> None:
    response = request("GET", "/health")
    assert response.status_code == 200
    assert set(response.json()) == {"status", "ml_model_loaded", "groq_configured"}
    assert response.json()["status"] == "ok"


def test_valid_analyze_request_returns_all_compiler_sections() -> None:
    response = request("POST", "/analyze", json={"code": "int main(){return 0;}"})
    body = response.json()
    assert response.status_code == 200 and body["success"]
    assert body["lexical"]["success"] and body["syntax"]["success"]
    assert body["semantic"] == {"ran": True, "success": True, "errors": []}
    assert body["ast"]["node"] == "Program"
    assert body["symbols"]["root"]["id"] == "global"


def test_lexical_error_is_normal_analyze_response() -> None:
    response = request("POST", "/analyze", json={"code": "int main(){ @ return 0;}"})
    body = response.json()
    assert response.status_code == 200 and not body["success"]
    assert not body["lexical"]["success"]
    assert body["lexical"]["errors"][0]["code"] == "ILLEGAL_CHARACTER"


def test_syntax_error_is_normal_analyze_response() -> None:
    response = request("POST", "/analyze", json={"code": "int main(){if(true {return 0;}}"})
    body = response.json()
    assert response.status_code == 200
    assert not body["syntax"]["success"] and body["syntax"]["errors"]
    assert body["semantic"]["ran"] is False and body["ast"] is None


def test_semantic_error_analyze_response() -> None:
    response = request("POST", "/analyze", json={"code": "int main(){return missing;}"})
    body = response.json()
    assert response.status_code == 200
    assert body["syntax"]["success"] and body["semantic"]["ran"]
    assert not body["semantic"]["success"] and body["semantic"]["errors"]


def test_tokens_endpoint_returns_spans_and_lexical_diagnostics() -> None:
    response = request("POST", "/tokens", json={"code": "int x = 1;"})
    body = response.json()
    assert response.status_code == 200 and body["success"]
    assert body["token_count"] == len(body["tokens"])
    assert {"type", "lexeme", "value", "line", "column", "offset", "span"} <= set(
        body["tokens"][0]
    )
    assert "start" in body["tokens"][0]["span"] and "end" in body["tokens"][0]["span"]


def test_ast_endpoint_success() -> None:
    body = request("POST", "/ast", json={"code": "int main(){return 0;}"}).json()
    assert body["success"] and body["ast"]["node"] == "Program"
    assert body["syntax_errors"] == []


def test_ast_endpoint_parse_failure() -> None:
    response = request("POST", "/ast", json={"code": "int main(){return 0"})
    body = response.json()
    assert response.status_code == 200 and not body["success"]
    assert body["ast"] is None and body["syntax_errors"]


def test_symbol_table_endpoint_success() -> None:
    code = "int add(int x){return x;} int main(){return add(1);}"
    body = request("POST", "/symbols", json={"code": code}).json()
    assert body["success"] and body["ran"]
    names = [item["name"] for item in body["symbols"]["root"]["symbols"]]
    assert names == ["add", "main"]


def test_correction_endpoint_uses_existing_high_confidence_orchestrator() -> None:
    source = "int main(){if(true {return 0;}}"
    use_orchestrator(CorrectionOrchestrator(FixedPredictor(0.99)))
    response = request("POST", "/correct", json={"code": source})
    body = response.json()
    assert response.status_code == 200 and body["success"]
    assert body["corrections_applied"] == 1
    assert body["history"][0]["status"] == "APPLIED"
    assert not body["groq_fallback_used"]


def test_correction_response_is_complete_and_serializable() -> None:
    source = "int main(){if(true {return 0;}}"
    use_orchestrator(CorrectionOrchestrator(FixedPredictor(0.99)))
    body = request("POST", "/correct", json={"code": source}).json()
    json.dumps(body)
    assert body["original_code"] == source
    assert "true) {" in body["corrected_code"]
    assert body["confidence_values"] == [0.99]
    assert body["unresolved_syntax_diagnostics"] == []


def test_correction_endpoint_supports_mocked_llm_fallback() -> None:
    source = "int main(){if(true {return 0;}}"
    offset = source.index(" {", source.index("if"))
    suggestion = LLMSuggestion(CorrectionAction.INSERT, ")", offset, offset, "close condition")
    fallback = FakeFallback(LLMFallbackResult(True, True, "mock-groq", suggestion))
    use_orchestrator(CorrectionOrchestrator(FixedPredictor(0.40), llm_fallback=fallback))
    body = request("POST", "/correct", json={"code": source}).json()
    assert body["success"] and body["groq_fallback_used"]
    assert fallback.calls == 1
    assert body["history"][0]["llm_fallback"]["accepted"]


def test_missing_code_request_returns_422() -> None:
    response = request("POST", "/analyze", json={})
    assert response.status_code == 422
    assert response.json()["detail"]


def test_malformed_json_returns_422_without_stack_trace() -> None:
    response = request(
        "POST",
        "/analyze",
        content='{"code":',
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 422
    assert "traceback" not in response.text.lower()


def test_api_never_serializes_groq_key() -> None:
    source = "int main(){if(true {return 0;}}"
    fallback = FakeFallback(
        LLMFallbackResult(False, False, "mock-groq", error="provider unavailable")
    )
    use_orchestrator(CorrectionOrchestrator(FixedPredictor(0.40), llm_fallback=fallback))
    response = request("POST", "/correct", json={"code": source})
    assert "groq_api_key" not in response.text.lower()
    assert "api_key" not in response.text.lower()


def test_missing_model_returns_clean_503() -> None:
    def unavailable():
        raise ModelUnavailableError("Correction model is unavailable; train it first")

    app.dependency_overrides[get_orchestrator] = unavailable
    response = request("POST", "/correct", json={"code": "int main(){return 0;}"})
    assert response.status_code == 503
    assert response.json() == {"detail": "Correction model is unavailable; train it first"}


def test_unexpected_backend_failure_returns_generic_500() -> None:
    class BrokenOrchestrator:
        def correct(self, code):
            raise RuntimeError("private internal detail")

    app.dependency_overrides[get_orchestrator] = BrokenOrchestrator
    response = request("POST", "/correct", json={"code": "int main(){return 0;}"})
    assert response.status_code == 500
    assert response.json() == {"detail": "An unexpected backend error occurred"}
    assert "private internal detail" not in response.text


def test_cors_allows_local_vite_origin() -> None:
    response = request(
        "OPTIONS",
        "/analyze",
        headers={
            "origin": "http://localhost:5173",
            "access-control-request-method": "POST",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_openapi_schema_lists_all_phase8_endpoints() -> None:
    response = request("GET", "/openapi.json")
    assert response.status_code == 200
    assert {"/health", "/analyze", "/correct", "/tokens", "/ast", "/symbols"} <= set(
        response.json()["paths"]
    )
    docs = request("GET", "/docs")
    assert docs.status_code == 200 and "swagger-ui" in docs.text.lower()
