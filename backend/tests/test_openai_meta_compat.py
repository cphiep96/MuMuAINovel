"""Meta Model API (Muse Spark) payload compatibility."""
from app.services.ai_clients.openai_client import OpenAIClient, is_meta_model_api


def test_detects_meta_host_and_muse_spark_model():
    assert is_meta_model_api("https://api.meta.ai/v1", "gpt-4")
    assert is_meta_model_api("https://example.com/v1", "muse-spark-1.3-contributor")
    assert not is_meta_model_api("https://api.openai.com/v1", "gpt-4o-mini")
    assert not is_meta_model_api("https://ollama.com/v1", "deepseek-v4.1-flash")
    assert not is_meta_model_api("https://ollama.com/v1", "deepseek-v4-flash")
    assert not is_meta_model_api("http://127.0.0.1:11434/v1", "qwen2.5:7b")


def test_meta_payload_uses_reasoning_effort_and_strips_vllm_thinking_flag():
    client = OpenAIClient(
        api_key="test",
        base_url="https://api.meta.ai/v1",
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )
    payload = client._build_payload(
        messages=[{"role": "user", "content": "hi"}],
        model="muse-spark-1.3-contributor",
        temperature=1.0,
        max_tokens=2048,
        tools=[{"type": "function", "function": {"name": "get_weather", "parameters": {"type": "object"}}}],
        tool_choice="auto",
    )
    assert payload["reasoning_effort"] == "minimal"
    assert "chat_template_kwargs" not in payload
    assert payload["max_tokens"] == 4096
    assert payload["tool_choice"] == "auto"


def test_meta_payload_coerces_required_tool_choice_to_auto():
    client = OpenAIClient(api_key="test", base_url="https://api.meta.ai/v1")
    payload = client._build_payload(
        messages=[{"role": "user", "content": "hi"}],
        model="muse-spark-1.3-contributor",
        temperature=1.0,
        max_tokens=4096,
        tools=[{"type": "function", "function": {"name": "web_search", "parameters": {"type": "object"}}}],
        tool_choice="required",
    )
    assert payload["tool_choice"] == "auto"


def test_meta_payload_without_tools_floors_max_tokens_at_1024():
    client = OpenAIClient(api_key="test", base_url="https://api.meta.ai/v1")
    payload = client._build_payload(
        messages=[{"role": "user", "content": "hi"}],
        model="muse-spark-1.3-contributor",
        temperature=1.0,
        max_tokens=200,
    )
    assert payload["max_tokens"] == 1024
    assert payload["reasoning_effort"] == "low"


def test_openai_payload_keeps_vllm_thinking_flag():
    client = OpenAIClient(
        api_key="test",
        base_url="https://api.openai.com/v1",
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )
    payload = client._build_payload(
        messages=[{"role": "user", "content": "hi"}],
        model="gpt-4o-mini",
        temperature=0.3,
        max_tokens=200,
    )
    assert payload["chat_template_kwargs"]["enable_thinking"] is False
    assert "reasoning_effort" not in payload


def test_ollama_openai_compatible_payload_is_unchanged_by_meta_special_case():
    client = OpenAIClient(
        api_key="test",
        base_url="https://ollama.com/v1",
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )
    payload = client._build_payload(
        messages=[{"role": "user", "content": "hi"}],
        model="deepseek-v4.1-flash",
        temperature=0.3,
        max_tokens=200,
        tools=[{"type": "function", "function": {"name": "get_weather", "parameters": {"type": "object"}}}],
        tool_choice="auto",
    )
    assert payload["model"] == "deepseek-v4.1-flash"
    assert payload["max_tokens"] == 200
    assert payload["temperature"] == 0.3
    assert payload["chat_template_kwargs"]["enable_thinking"] is False
    assert "reasoning_effort" not in payload
    assert payload["tool_choice"] == "auto"
