"""Prompt persistence, snapshot isolation, conflicts and HTTP tests; no model API."""
import json
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import httpx
from backend.config import ROOT
from backend.domain.models import StudyError
from backend.dp.agent_config import LocalProfileRegistry
from backend.service.learning import LearningService
from backend.app import create_app

class PromptSettingsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        (ROOT/'.cache/tests').mkdir(parents=True,exist_ok=True)
        temp=tempfile.TemporaryDirectory(dir=ROOT/'.cache/tests')
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        for name in ('config','prompts','skills','plugins'):
            shutil.copytree(ROOT/name,self.root/name)
        self.registry=LocalProfileRegistry(self.root)

    def test_all_prompts_roundtrip_version_and_inflight_snapshot(self):
        old=self.registry.snapshot()
        view=self.registry.prompt_settings()
        self.assertEqual(set(view['prompts']),{'base','ask','translate','explain','explain_detail','summary','course_overview'})
        original={p.name:p.read_bytes() for p in (self.root/'prompts').glob('*.md')}
        body='翻译为中文，保留术语。\n<script>alert("test")</script>\n'
        result=self.registry.save_prompt('translate',body,view['version'])
        self.assertNotEqual(result['version'],old.version)
        self.assertEqual(result['prompts']['translate'],body)
        self.assertEqual((self.root/'prompts/translate.md').read_text(encoding='utf-8'),body)
        self.assertNotEqual(old.prompts['translate'],body)
        restarted=LocalProfileRegistry(self.root)
        self.assertEqual(restarted.prompt_settings(),result)
        for name, contents in original.items():
            if name!='translate.md':self.assertEqual((self.root/'prompts'/name).read_bytes(),contents)
        for prompt_id in ('base','ask','explain','explain_detail','summary','course_overview'):
            result=self.registry.save_prompt(prompt_id,'测试规则：'+prompt_id,result['version'])
        self.assertEqual(LocalProfileRegistry(self.root).prompt_settings(),result)
        import yaml
        models_path=self.root/'config/models.yaml'
        models=yaml.safe_load(models_path.read_text(encoding='utf-8'))
        models['models']['qa_model']=dict(models['models']['study_model'])
        models_path.write_text(yaml.safe_dump(models,allow_unicode=True),encoding='utf-8')
        agents_path=self.root/'config/agents.yaml'
        agents=yaml.safe_load(agents_path.read_text(encoding='utf-8'))
        agents['profiles']['ask']['model']='qa_model'
        agents_path.write_text(yaml.safe_dump(agents,allow_unicode=True),encoding='utf-8')
        self.assertEqual(LocalProfileRegistry(self.root).snapshot().profiles['course_overview']['model'],'qa_model')

    def test_invalid_input_and_stale_version_do_not_write(self):
        before=self.registry.prompt_settings()
        file=self.root/'prompts/base.md'; raw=file.read_bytes()
        for pid,body,version in [('unknown','text',before['version']),('base','  ',before['version']),('base','x'*20001,before['version']),('base','x\x00',before['version']),('base','text','stale')]:
            with self.assertRaises(StudyError):self.registry.save_prompt(pid,body,version)
            self.assertEqual(file.read_bytes(),raw)
        self.assertEqual(self.registry.prompt_settings(),before)

    def test_file_failure_and_bad_configuration_keep_original(self):
        view=self.registry.prompt_settings(); file=self.root/'prompts/base.md'; raw=file.read_bytes()
        with patch('backend.dp.agent_config.os.replace',side_effect=OSError('failed')):
            with self.assertRaisesRegex(StudyError,'保存失败'):
                self.registry.save_prompt('base','new rules',view['version'])
        self.assertEqual(file.read_bytes(),raw)
        self.assertEqual(list((self.root/'prompts').glob('.prompt-*.tmp')),[])
        (self.root/'config/agents.yaml').write_text('invalid: true',encoding='utf-8')
        with self.assertRaises(StudyError):self.registry.save_prompt('base','new rules',view['version'])
        self.assertEqual(file.read_bytes(),raw)
        self.assertEqual(self.registry.prompt_settings(),view)

    def test_external_edit_and_reconfigured_path_are_conflicts(self):
        view=self.registry.prompt_settings(); file=self.root/'prompts/explain.md'
        file.write_text('external edit',encoding='utf-8')
        with self.assertRaises(StudyError) as error:self.registry.save_prompt('explain','new rules',view['version'])
        self.assertEqual(error.exception.status,409)
        self.assertEqual(file.read_text(encoding='utf-8'),'external edit')
        config=self.root/'config/agents.yaml'
        config.write_text(config.read_text(encoding='utf-8').replace('prompts/translate.md','prompts/summary.md'),encoding='utf-8')
        with self.assertRaises(StudyError) as error:self.registry.save_prompt('translate','new rules',view['version'])
        self.assertEqual(error.exception.status,409)

    async def test_api_fetch_save_no_secrets_and_origin_guard(self):
        self.registry.current.models['study_model']['api_key']='test-private-key'
        learning=LearningService(None,self.registry,None,None,None,None,SimpleNamespace(states={}))
        app=create_app(data_dir=self.root/'data',service=object(),learning=learning,overview=SimpleNamespace(close=learning.close))
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://testserver') as client:
                response=await client.get('/api/agent/prompts'); self.assertEqual(response.status_code,200)
                self.assertNotIn('test-private-key',response.text)
                payload={'prompt_id':'explain_detail','content':'详细解释并提供一个小例子。','expected_version':response.json()['version']}
                response=await client.post('/api/agent/prompts',json=payload)
                self.assertEqual(response.status_code,200,response.text)
                self.assertEqual(response.json()['prompts']['explain_detail'],payload['content'])
                self.assertNotIn('api_key',response.text)
                response=await client.post('/api/agent/prompts',json=payload)
                self.assertEqual(response.status_code,409)
                response=await client.post('/api/agent/prompts',json=payload,headers={'Origin':'https://untrusted.example'})
                self.assertEqual(response.status_code,403)
                payload['prompt_id']='../../.env.local'
                self.assertEqual((await client.post('/api/agent/prompts',json=payload)).status_code,422)
