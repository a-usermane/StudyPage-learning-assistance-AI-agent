"""Local credential persistence and HTTP response tests; no model calls."""
import json
import os
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import httpx
from dotenv import dotenv_values
from backend.config import ROOT
from backend.dp.agent_config import LocalProfileRegistry
from backend.domain.models import StudyError
from backend.service.learning import LearningService
from backend.app import create_app

class CredentialTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        (ROOT / ".cache/tests").mkdir(parents=True, exist_ok=True)
        temp = tempfile.TemporaryDirectory(dir=ROOT / ".cache/tests")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        for folder in ("config", "prompts", "skills", "plugins"):
            shutil.copytree(ROOT / folder, self.root / folder)
        self.environment = patch.dict(os.environ)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        os.environ.pop("STUDY_API_KEY", None)
        self.registry = LocalProfileRegistry(self.root)

    def test_save_preserves_other_values_and_round_trips(self):
        file = self.root / ".env.local"
        file.write_text("# local settings\nOTHER=value\nSTUDY_API_KEY=old\n", encoding="utf-8")
        key = "test-$dollar-quote'slash\\end"
        result = self.registry.save_api_key("study_model", key)
        self.assertEqual(dotenv_values(file)["STUDY_API_KEY"], key)
        self.assertEqual(dotenv_values(file)["OTHER"], "value")
        self.assertIn("# local settings", file.read_text(encoding="utf-8"))
        self.assertNotIn(key, json.dumps(result))
        self.assertEqual(result["models"]["study_model"]["key_source"], "local")
        self.assertEqual(LocalProfileRegistry(self.root).snapshot().models["study_model"]["api_key"], key)

    def test_rejected_save_keeps_file_and_snapshot(self):
        self.registry.save_api_key("study_model", "previous-key")
        file = self.root / ".env.local"
        previous = file.read_bytes()
        for model, key in (("missing", "new-key"), ("study_model", ""), ("study_model", "bad\nkey")):
            with self.assertRaises(StudyError):
                self.registry.save_api_key(model, key)
            self.assertEqual(file.read_bytes(), previous)
        (self.root / "config/agents.yaml").write_text("invalid: true", encoding="utf-8")
        with self.assertRaises(Exception):
            self.registry.save_api_key("study_model", "new-key")
        self.assertEqual(file.read_bytes(), previous)
        self.assertEqual(self.registry.snapshot().models["study_model"]["api_key"], "previous-key")

    def test_environment_precedence_and_write_failure(self):
        os.environ["STUDY_API_KEY"] = "environment-key"
        with self.assertRaisesRegex(StudyError, "环境变量"):
            self.registry.save_api_key("study_model", "new-key")
        os.environ.pop("STUDY_API_KEY")
        with patch("backend.dp.agent_config.os.replace", side_effect=OSError("failure")):
            with self.assertRaisesRegex(StudyError, "保存失败"):
                self.registry.save_api_key("study_model", "new-key")
        self.assertFalse((self.root / ".env.local").exists())
        self.assertEqual(list(self.root.glob(".env.*.tmp")), [])

    async def test_http_save_no_secret_and_origin_guard(self):
        learning = LearningService(None, self.registry, None, None, None, None, SimpleNamespace(states={}))
        app = create_app(data_dir=self.root / "data", service=object(), learning=learning)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
                payload = {"model_id": "study_model", "api_key": "test-private-key"}
                response = await client.post("/api/agent/credentials", json=payload)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertNotIn(payload["api_key"], response.text)
                self.assertTrue(response.json()["models"]["study_model"]["configured"])
                response = await client.post("/api/agent/credentials", json=payload, headers={"Origin": "https://untrusted.example"})
                self.assertEqual(response.status_code, 403)
                response = await client.get("/api/agent/status")
                self.assertNotIn(payload["api_key"], response.text)
