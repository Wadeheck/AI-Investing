from types import SimpleNamespace

from ai_investing.data.inference_control import DeferredInference, InferenceControl


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
