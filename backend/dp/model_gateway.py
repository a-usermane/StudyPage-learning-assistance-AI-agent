"""Provider registration. Credentials and transport never reach domain or UI."""
from backend.domain.models import StudyError

class RegisteredModelGateway:
    def __init__(self):
        self.adapters = {"openai_compatible": self._openai}

    def register(self, name, factory):
        self.adapters[name] = factory

    def create(self, model):
        if not model.get("api_key"):
            raise StudyError("未配置模型密钥。请填写 .env.local 并重载配置，或选择演示模式。", 503)
        factory = self.adapters.get(model.get("adapter"))
        if not factory:
            raise StudyError("模型适配器未注册。", 503)
        return factory(model)

    @staticmethod
    def _openai(config):
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=config["model"], base_url=config["base_url"], api_key=config["api_key"],
                          temperature=float(config.get("temperature", .2)), max_tokens=config["output_tokens"],
                          timeout=30, max_retries=0, use_responses_api=False, stream_usage=False,
                          profile={"max_input_tokens": config["context_window"], "tool_calling": True},
                          custom_get_token_ids=lambda text: list(range(len(text.encode("utf-8")))))
