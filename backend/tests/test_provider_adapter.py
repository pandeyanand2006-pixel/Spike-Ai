import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

def test_provider_factory_groq_default():
    os.environ.pop("LLM_PROVIDER", None)
    # reload settings
    from importlib import reload
    import app.config as cfg
    # clear cache
    cfg.get_settings.cache_clear()
    from app.services.provider_adapter import get_agent_provider
    provider, model = get_agent_provider()
    assert provider.name in ("groq", "openai_compatible")
    assert isinstance(model, str)

def test_provider_openai_compat():
    os.environ["LLM_PROVIDER"] = "openai_compatible"
    os.environ["OPENAI_COMPATIBLE_BASE_URL"] = "http://localhost:11434/v1"
    os.environ["OPENAI_COMPATIBLE_MODEL"] = "llama3"
    import app.config as cfg
    cfg.get_settings.cache_clear()
    from app.services.provider_adapter import get_agent_provider
    provider, model = get_agent_provider()
    assert provider.name == "openai_compatible"
    assert model == "llama3"
    # cleanup
    os.environ.pop("LLM_PROVIDER", None)
    os.environ.pop("OPENAI_COMPATIBLE_BASE_URL", None)
    cfg.get_settings.cache_clear()

def test_local_not_required():
    from app.services.provider_adapter import is_local_provider_available
    # should return bool without exception
    res = is_local_provider_available(timeout=0.5)
    assert isinstance(res, bool)
