from docsifer.core.llm_registry import LLMConfig, LLMRegistry


def test_from_dict_returns_none_when_no_key() -> None:
    assert (
        LLMConfig.from_dict(
            {"api_key": "  "},
            default_base_url="https://api.openai.com/v1",
            default_model="gpt-4o-mini",
        )
        is None
    )
    assert (
        LLMConfig.from_dict(
            None,
            default_base_url="https://api.openai.com/v1",
            default_model="gpt-4o-mini",
        )
        is None
    )


def test_from_dict_applies_defaults() -> None:
    cfg = LLMConfig.from_dict(
        {"api_key": "sk-test"},
        default_base_url="https://api.openai.com/v1",
        default_model="gpt-4o-mini",
    )
    assert cfg is not None
    assert cfg.api_key == "sk-test"
    assert cfg.base_url == "https://api.openai.com/v1"
    assert cfg.model == "gpt-4o-mini"


def test_cache_key_changes_with_model() -> None:
    a = LLMConfig(api_key="sk", base_url="https://x", model="m1")
    b = LLMConfig(api_key="sk", base_url="https://x", model="m2")
    assert a.cache_key != b.cache_key


def test_registry_caches_by_key(monkeypatch) -> None:
    calls = {"n": 0}

    class _DummyMD:
        pass

    def _build(self, config):  # noqa: D401
        calls["n"] += 1
        return _DummyMD()

    monkeypatch.setattr(LLMRegistry, "_build", _build)

    reg = LLMRegistry(max_size=4, ttl=60)
    cfg = LLMConfig(api_key="sk", base_url="https://x", model="m")
    a = reg.get(cfg)
    b = reg.get(cfg)
    assert a is b
    assert calls["n"] == 1
