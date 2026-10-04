"""Developer extension point: factories receive only the scoped run context."""
from backend.domain.models import StudyError

class ToolRegistry:
    def __init__(self):
        self.factories = {}

    def register(self, name, factory):
        if name in self.factories:
            raise StudyError("工具名称已注册。")
        self.factories[name] = factory

    def create(self, context, exclude=()):
        result = []
        for name in context.profile.get('tools',[]):
            if name in self.factories and name not in exclude:
                result.append(self.factories[name](context))
        return result
