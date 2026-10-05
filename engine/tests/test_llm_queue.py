from types import SimpleNamespace
import json
from datetime import datetime, timezone

from ai_investing.data.inference_control import DeferredInference, InferenceControl
from ai_investing.data import news


def _settings(tmp_path, enabled=True):
    return SimpleNamespace(
        state_path=str(tmp_path / "state.json"),
        llm_queue_enabled=enabled,
    )


def test_queue_persists_request_and_reuses_drained_result(tmp_path):
    settings = _settings(tmp_path)
    control = InferenceControl(settings)
    try:
        result = control.call(
            "event_extraction", ["fast", 6000, True], "prompt",
            lambda: (_ for _ in ()).throw(AssertionError("provider called early")),
            json_mode=True, max_tokens=6000, tier="fast", settings=settings)
        assert isinstance(result, DeferredInference)
        assert control.pending_count() == 1
    finally:
        control.close()

    control = InferenceControl(settings)
    try:
        report = control.drain(lambda job: '{"events": []}')
        assert report == {"done": 1, "failed": 0, "remaining": 0}
        cached = control.call(
            "event_extraction", ["fast", 6000, True], "prompt",
            lambda: (_ for _ in ()).throw(AssertionError("cache missed")),
            json_mode=True, max_tokens=6000, tier="fast", settings=settings)
        assert cached == '{"events": []}'
    finally:
        control.close()


def test_failed_job_is_requeued_for_a_later_window(tmp_path):
    settings = _settings(tmp_path)
    control = InferenceControl(settings)
    try:
        control.call("asset_sentiment", ["fast"], "prompt", lambda: None,
                     max_tokens=100, tier="fast", settings=settings)
        report = control.drain(lambda job: None)
        assert report["done"] == 0
        assert report["failed"] == 1
        assert report["remaining"] == 1
    finally:
        control.close()


def test_queue_provider_uses_byteplus_before_local(tmp_path, monkeypatch):
    settings = SimpleNamespace(
        state_path=str(tmp_path / "state.json"),
        byteplus_api_key="key",
        byteplus_chain_fast=["fast"], byteplus_chain_smart=["smart"],
        byteplus_model_fast="fast", byteplus_model_smart="smart",
        llm_daily_free_tokens=5000,
        local_llm_url="http://local", local_llm_mode="ollama",
    )
    (tmp_path / "llm_usage.json").write_text(json.dumps({
        "day": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "by_model": {}, "by_hour": {},
    }))
    calls = []
    monkeypatch.setattr(news, "_call_byteplus", lambda *args, **kwargs: calls.append("byteplus") or "bp")
    monkeypatch.setattr(news, "local_llm_available", lambda _settings: True)
    monkeypatch.setattr(news, "_call_local", lambda *args, **kwargs: calls.append("local") or "local")
    assert news._call_llm_queue_uncached("prompt", settings) == "bp"
    assert calls == ["byteplus"]


def test_queue_provider_switches_to_local_at_ninety_percent(tmp_path, monkeypatch):
    settings = SimpleNamespace(
        state_path=str(tmp_path / "state.json"),
        byteplus_api_key="key",
        byteplus_chain_fast=["fast"], byteplus_chain_smart=["smart"],
        byteplus_model_fast="fast", byteplus_model_smart="smart",
        llm_daily_free_tokens=5000,
        local_llm_url="http://local", local_llm_mode="ollama",
    )
    (tmp_path / "llm_usage.json").write_text(json.dumps({
        "day": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "by_model": {"fast": 4500, "smart": 4500}, "by_hour": {},
    }))
    calls = []
    monkeypatch.setattr(news, "_call_byteplus", lambda *args, **kwargs: calls.append("byteplus") or "bp")
    monkeypatch.setattr(news, "local_llm_available", lambda _settings: True)
    monkeypatch.setattr(news, "_call_local", lambda *args, **kwargs: calls.append("local") or "local")
    assert news._call_llm_queue_uncached("prompt", settings) == "local"
    assert calls == ["local"]
