"""Validated immutable-per-run configuration and declarative plugin discovery."""
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from threading import RLock
import yaml
from dotenv import dotenv_values
from backend.domain.models import StudyError

WORKFLOWS = {"course_qa", "direct_translation", "contextual_explanation", "page_summary"}
TOOLS = {"list_documents", "search_documents", "read_pages", "search_notes"}

@dataclass(frozen=True)
class ConfigSnapshot:
    version: str
    mode: str
    models: dict
    profiles: dict
    prompts: dict
    skills: dict
    mcp: dict
    plugins: tuple

class LocalProfileRegistry:
    def __init__(self, root, workflows=None, tools=None, adapters=None):
        self.root = Path(root).resolve()
        self.workflows = set(workflows or WORKFLOWS)
        self.tools = TOOLS | set(tools or ())
        self.adapters = set(adapters or {"openai_compatible"})
        self.current = None
        self.last_error = None
        self._lock = RLock()
        self.reload()

    def path(self, relative):
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root):
            raise StudyError("配置引用的路径必须位于项目目录内。")
        return path

    def read(self, relative):
        return self.path(relative).read_text(encoding="utf-8")

    def snapshot(self):
        # Do not expose a live mutable configuration to callers.
        return deepcopy(self.current)

    def reload(self):
        with self._lock:
            return self._reload()

    def _reload(self):
        try:
            candidate = self._load()
        except Exception as exc:
            self.last_error = "配置无效，请检查 YAML、路径、模型预算和工具名称。"
            if isinstance(exc, StudyError):
                raise
            raise StudyError(self.last_error) from exc
        self.current = candidate
        self.last_error = None
        return self.status()

    def save_api_key(self, model_id, api_key):
        """Validate before atomically updating only the selected local credential."""
        with self._lock:
            model = self.current.models.get(model_id)
            if model is None:
                raise StudyError("请选择有效的模型配置。")
            env_name = model.get("api_key_env", "STUDY_API_KEY")
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", env_name):
                raise StudyError("密钥环境变量名称无效，请检查模型配置。")
            if os.environ.get(env_name):
                raise StudyError("该模型正在使用系统环境变量中的密钥，请先移除该环境变量再通过页面保存。")
            api_key = api_key.strip()
            if not api_key or len(api_key) > 4096 or any(ord(c) < 33 or ord(c) > 126 for c in api_key):
                raise StudyError("请输入有效的 API Key，不包含空格或换行。")
            target = self.path(".env.local")
            previous = target.read_text(encoding="utf-8") if target.exists() else ""
            secrets = dict(dotenv_values(target))
            secrets[env_name] = api_key
            try:
                candidate = self._load(secrets)
            except StudyError:
                raise
            except Exception:
                raise StudyError("本地配置无效，请修复配置后再保存密钥；原密钥未更改。") from None
            # Single-quoted dotenv values preserve dollar signs and other key characters.
            quoted = api_key.replace("\\", "\\\\").replace("'", "\\'")
            entry = env_name + "='" + quoted + "'"
            pattern = re.compile(r"^\s*(?:export\s+)?" + re.escape(env_name) + r"\s*=.*$")
            lines = [line for line in previous.splitlines() if not pattern.match(line)]
            content = "\n".join([*lines, entry]) + "\n"
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.root, prefix=".env.", suffix=".tmp", delete=False) as handle:
                    temporary = Path(handle.name)
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, target)
            except OSError:
                raise StudyError("密钥保存失败，请检查项目目录的写入权限。") from None
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
            self.current = candidate
            self.last_error = None
            return self.status()

    def _load(self, local_secrets=None):
        model_config = yaml.safe_load(self.read("config/models.yaml"))
        agents = yaml.safe_load(self.read("config/agents.yaml"))
        mcp = json.loads(self.read("config/mcp.json")).get("servers", {})
        mode = model_config.get("mode", "demo")
        if mode not in {"demo", "live"}:
            raise StudyError("mode 必须为 demo 或 live。")
        secrets = dotenv_values(self.path(".env.local")) if local_secrets is None else local_secrets
        models = deepcopy(model_config["models"])
        for key, model in models.items():
            if model.get('adapter') not in self.adapters or not model.get('model'):
                raise StudyError("模型名称为空或引用未注册的适配器。")
            if not re.fullmatch(r"[A-Za-z0-9_-]+", key):
                raise StudyError("模型配置名称无效。")
            budget, window = int(model.get("context_budget", 16384)), int(model.get("context_window", 16384))
            output = int(model.get("output_tokens", 2048))
            if not 1024 <= budget <= window or not 128 <= output < budget // 2:
                raise StudyError("上下文预算必须在模型窗口内，且输出预算小于总预算的一半。")
            model.update(context_budget=budget, context_window=window, output_tokens=output)
            if not model.get("base_url", "").startswith(("http://", "https://")):
                raise StudyError("模型 base_url 必须是 HTTP 或 HTTPS 地址。")
            env_name = model.get("api_key_env", "STUDY_API_KEY")
            model["api_key"] = os.environ.get(env_name) or secrets.get(env_name) or ""
            model["key_source"] = "environment" if os.environ.get(env_name) else "local" if secrets.get(env_name) else "none"
        skills = {}
        for file in sorted(self.path("skills").glob("*/SKILL.md")):
            body = file.read_text(encoding="utf-8")
            parts = body.split("---", 2)
            metadata = yaml.safe_load(parts[1]) if len(parts) == 3 else {}
            name = metadata.get("name")
            if not name or name in skills or not re.fullmatch(r"[a-z0-9-]+", name):
                raise StudyError("Skill 名称无效或重复。")
            files = {}
            for resource in file.parent.rglob("*"):
                if resource.is_file() and resource.suffix == ".md":
                    safe = self.path(str(resource.relative_to(self.root)))
                    files[str(safe.relative_to(file.parent)).replace("\\", "/")] = safe.read_text(encoding="utf-8")
            skills[name] = {"description": metadata.get("description", ""), "files": files}
        defaults = agents.get("defaults", {})
        profiles = {name: {**defaults, **value} for name, value in agents["profiles"].items()}
        plugins, claimed = [], set()
        declared_skills, declared_mcp, active_skills, active_mcp = set(), set(), set(), set()
        for manifest in sorted(self.path("plugins").glob("*/plugin.yaml")):
            entry = {"id": manifest.parent.name, "enabled": False}
            try:
                plugin = yaml.safe_load(manifest.read_text(encoding="utf-8"))
                self.path(str(manifest.relative_to(self.root)))
                entry.update(id=plugin["id"], version=plugin["version"])
                declared_skills.update(plugin.get('skills',[]))
                declared_mcp.update(plugin.get('mcp',[]))
                if not plugin.get("enabled", False):
                    plugins.append(entry); continue
                if not re.fullmatch(r"\d+\.\d+\.\d+", str(plugin["version"])):
                    raise ValueError("插件版本必须采用 x.y.z 格式。")
                if not re.fullmatch(r'[a-z0-9-]+',entry['id']) or entry["id"] in claimed or set(plugin.get("skills", [])) - set(skills) or set(plugin.get("mcp", [])) - set(mcp):
                    raise ValueError("插件名称冲突或引用不存在。")
                overrides = plugin.get("profiles", {})
                trial = deepcopy(profiles)
                for name, profile in overrides.items():
                    if name not in trial or ("profile:" + name) in claimed:
                        raise ValueError("插件功能配置冲突。")
                    trial[name].update(profile)
                self._validate_profiles(trial, models, skills, mcp)
                for profile in trial.values():
                    self.read(profile['prompt'])
                profiles = trial
                claimed.update({entry["id"], *("profile:" + n for n in overrides)})
                entry["enabled"] = True
                active_skills.update(plugin.get('skills',[]))
                active_mcp.update(plugin.get('mcp',[]))
            except Exception:
                entry["error"] = "插件配置无效、版本错误或存在名称冲突，已单独禁用。"
            plugins.append(entry)
        # Standalone resources stay enabled; a shared resource remains enabled
        # while at least one successfully loaded owning plugin uses it.
        enabled_skills = (set(skills) - declared_skills) | active_skills
        enabled_mcp = (set(mcp) - declared_mcp) | active_mcp
        self._validate_profiles(profiles, models, skills, mcp)
        prompts = {"base": self.read("prompts/base.md")}
        for name, profile in profiles.items():
            prompts[name] = self.read(profile["prompt"])
            profile["skills"] = [n for n in profile.get("skills", []) if n in enabled_skills]
        for name, server in mcp.items():
            server["enabled"] = bool(server.get("enabled", False) and name in enabled_mcp)
            if server.get("transport") not in {"stdio", "http"}:
                raise StudyError("MCP transport 只能为 stdio 或 http。")
            if server["transport"] == "http" and not server.get("url", "").startswith(("https://", "http://")):
                raise StudyError("MCP URL 无效。")
            if server["transport"] == "stdio":
                server["command"] = server["command"].replace("{python}", sys.executable).replace("{root}", str(self.root))
                server["args"] = [a.replace("{root}", str(self.root)) for a in server.get("args", [])]
            if not isinstance(server.get("tools"), list) or not server["tools"]:
                raise StudyError("MCP 必须配置明确的只读工具白名单。")
        payload = {"models": model_config, "profiles": profiles, "prompts": prompts, "skills": skills, "mcp": mcp, "plugins": plugins}
        version = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
        return ConfigSnapshot(version, mode, models, profiles, prompts, skills, mcp, tuple(plugins))

    def _validate_profiles(self, profiles, models, skills, mcp):
        if set(profiles) != {"ask", "translate", "explain", "summary"}:
            raise StudyError("需要 ask、translate、explain、summary 四个功能配置。")
        for profile in profiles.values():
            if profile.get("model") not in models or profile.get("workflow") not in self.workflows:
                raise StudyError("功能引用了未注册的模型或工作流。")
            if set(profile.get("tools", [])) - self.tools - set(mcp) or set(profile.get("skills", [])) - set(skills):
                raise StudyError("功能引用了不存在的工具或 Skill。")
            for key, maximum in (("timeout", 300), ("max_tool_calls", 20), ("max_steps", 60)):
                if not 1 <= int(profile.get(key, 0)) <= maximum:
                    raise StudyError("运行超时、工具次数或步数限制无效。")

    def status(self):
        value = self.current
        return {"mode": value.mode, "version": value.version, "config_error": self.last_error,
                "profiles": {n: {"workflow": p["workflow"], "model": p["model"], "tools": p.get("tools", []), "skills": p.get("skills", [])} for n,p in value.profiles.items()},
                "models": {n: {"model": m["model"], "configured": bool(m["api_key"]), "key_source": m["key_source"]} for n,m in value.models.items()},
                "plugins": list(value.plugins),
                "mcp": {n: {"enabled": m["enabled"], "tools": m["tools"]} for n,m in value.mcp.items()}}
