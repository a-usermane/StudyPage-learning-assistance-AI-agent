"""Overview lifecycle and map/reduce model contracts, with no external API calls."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from langchain_core.messages import AIMessage
from backend.config import ROOT
from backend.domain.models import StudyError
from backend.dp.overview_store import LocalOverviewStore
from backend.dp.overview_model import OverviewModelGenerator
from backend.service.course_overview import CourseOverviewService

class Repository:
    def __init__(self):
        self.docs=[dict(id='d1',name='first.txt',sha256='a',pages=2)]
        self.texts={('d1',1):'The PDF integrates to one.',('d1',2):''}
        self.read=[]
    def course(self,cid):
        if cid!='course':raise StudyError('课程不存在',404)
        return dict(id=cid,name='Probability')
    def documents(self,cid):self.course(cid);return deepcopy(self.docs)
    def page_text(self,did,start,end):self.read.append((did,start));return self.texts.get((did,start),'')

class Registry:
    def __init__(self):
        self.value=SimpleNamespace(mode='live',version='prompt-v1',profiles={'course_overview':{'model':'test','timeout':300,'max_model_calls':30}},
            models={'test':dict(api_key='fake',context_budget=16384,output_tokens=2048)},prompts={'course_overview':(ROOT/'prompts/course-overview.md').read_text(encoding='utf-8')})
    def snapshot(self):return deepcopy(self.value)

class Generator:
    def __init__(self):self.seen=[];self.gate=None;self.error=None
    async def generate(self,snapshot,cid,name,supplement,pages,manifest,progress):
        self.seen.append(deepcopy(pages));progress('已读取资料',1)
        if self.gate:await self.gate.wait()
        if self.error:raise self.error
        return dict(course_name=name,fields=['概率论'],main_content='学习连续随机变量与概率密度函数。')

class Model:
    def __init__(self):self.messages=[];self.bad=0;self.fail_at=None
    async def ainvoke(self,messages):
        self.messages.append(messages)
        if self.fail_at==len(self.messages):raise RuntimeError('simulated model failure')
        if self.bad:self.bad-=1;return AIMessage(content='invalid output')
        payload=json.loads(messages[1].content.split('\n上次输出')[0])
        return AIMessage(content=json.dumps(dict(course_name=payload['course_name'],fields=['概率论'],main_content='学习概率密度和连续随机变量。'),ensure_ascii=False))

class OverviewTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        (ROOT/'.cache/tests').mkdir(parents=True,exist_ok=True)
        tmp=tempfile.TemporaryDirectory(dir=ROOT/'.cache/tests');self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name);self.store=LocalOverviewStore(self.root,self.root/'cache')
        self.repo=Repository();self.registry=Registry();self.generator=Generator()
        self.service=CourseOverviewService(self.repo,self.registry,self.store,self.generator)
        self.addAsyncCleanup(self.service.close)
    async def finish(self,row):
        if 'course' in self.service.active:
            await asyncio.gather(self.service.active['course'][0],return_exceptions=True)
        await asyncio.sleep(0)
        return self.service.run('course',row['run_id'])
    def save(self,**changes):
        value=self.service.get('course')
        payload={k:value[k] for k in ('course_name','fields','main_content','supplement')}
        payload.update(changes)
        return self.service.save('course',**payload,expected_version=value['version'])

    async def test_all_documents_coverage_initial_once_and_staleness(self):
        self.repo.docs.append(dict(id='d2',name='second.txt',sha256='b',pages=1))
        self.repo.texts['d2',1]='conditional density'
        row=self.service.start('course',initial=True)
        self.assertEqual(self.service.start('course',initial=True)['run_id'],row['run_id'])
        result=await self.finish(row)
        self.assertEqual(result['status'],'complete')
        self.assertEqual(set(self.repo.read),{('d1',1),('d1',2),('d2',1)})
        self.assertEqual(result['coverage']['read_pages'],2)
        self.assertEqual(len(result['coverage']['unread_pages']),1)
        self.assertEqual(self.service.start('course',initial=True)['run_id'],row['run_id'])
        self.assertTrue(self.store.path('course').is_file())
        self.assertFalse(self.service.get('course')['stale'])
        self.repo.docs[0]['sha256']='changed'
        self.assertTrue(self.service.context('course')['stale'])
        self.save(supplement='my private supplement')
        self.assertTrue(self.service.context('course')['stale'])
        self.assertNotIn('supplement',self.service.context('course'))

    async def test_demo_missing_key_empty_text_and_supplement_only(self):
        pending=self.service.start('course',mode='demo',initial=True)
        self.assertEqual(pending['status'],'pending');self.assertFalse(self.generator.seen)
        self.registry.value.models['test']['api_key']=''
        self.assertEqual(self.service.start('course')['status'],'pending')
        self.registry.value.models['test']['api_key']='fake'
        self.repo.texts={}
        failed=await self.finish(self.service.start('course'))
        self.assertEqual(failed['status'],'failed');self.assertFalse(self.generator.seen)
        self.save(supplement='本课程学习概率分布。')
        done=await self.finish(self.service.start('course'))
        self.assertEqual(done['status'],'complete');self.assertTrue(done['coverage']['user_only'])

    async def test_user_edit_wins_over_an_older_generation(self):
        self.save(main_content='旧概况')
        self.generator.gate=asyncio.Event()
        run=self.service.start('course');await asyncio.sleep(0)
        self.save(main_content='用户刚刚修改的概况')
        self.generator.gate.set()
        done=await self.finish(run)
        self.assertEqual(done['status'],'failed');self.assertIn('已被修改',done['detail'])
        self.assertEqual(self.service.get('course')['main_content'],'用户刚刚修改的概况')

    async def test_material_change_cancel_timeout_and_failure_preserve_previous(self):
        self.save(main_content='原有概况')
        self.generator.gate=asyncio.Event()
        row=self.service.start('course');await asyncio.sleep(0)
        self.repo.docs[0]['sha256']='new';self.generator.gate.set()
        self.assertEqual((await self.finish(row))['status'],'failed')
        self.generator.gate=asyncio.Event()
        row=self.service.start('course');await asyncio.sleep(0);self.service.cancel('course',row['run_id'])
        self.assertEqual((await self.finish(row))['status'],'cancelled')
        row=self.service.start('course');self.service.cancel('course',row['run_id'])
        self.assertEqual((await self.finish(row))['status'],'cancelled')
        self.registry.value.profiles['course_overview']['timeout']=.01
        self.assertEqual((await self.finish(self.service.start('course')))['status'],'failed')
        self.generator.gate=None;self.generator.error=RuntimeError('failure')
        self.assertEqual((await self.finish(self.service.start('course')))['status'],'failed')
        self.assertEqual(self.service.get('course')['main_content'],'原有概况')

    def test_atomic_write_conflict_restart_and_limits(self):
        saved=self.save(main_content='原内容')
        raw=self.store.path('course').read_bytes()
        with self.assertRaises(StudyError):self.store.save('course',{},'0')
        with patch('backend.dp.overview_store.os.replace',side_effect=OSError('disk failure')):
            with self.assertRaises(StudyError):self.save(main_content='new')
        self.assertEqual(self.store.path('course').read_bytes(),raw)
        self.assertEqual(len(list(self.store.path('course').parent.iterdir())),1)
        self.store.run('course','run',dict(run_id='run',status='running'))
        restarted=LocalOverviewStore(self.root,self.root/'cache')
        self.assertEqual(restarted.run('course','run')['status'],'interrupted')
        with self.assertRaises(StudyError):self.save(main_content='x'*601)
        with self.assertRaises(StudyError):self.save(supplement='x'*2001)
        self.assertEqual(self.service.get('course')['version'],saved['version'])
        isolated=LocalOverviewStore(self.root/'other-data',self.root/'cache')
        self.assertNotEqual(isolated.cache,self.store.cache)
        self.assertIsNone(isolated.latest('course'))
        self.store.path('course').write_text('[]',encoding='utf-8')
        with self.assertRaises(StudyError):self.service.get('course')

    async def test_map_reduce_batches_cache_repair_and_call_limit(self):
        model=Model();gateway=SimpleNamespace(create=lambda cfg:model)
        generator=OverviewModelGenerator(gateway,self.store)
        snap=self.registry.snapshot();pages=[dict(document_id='d'+str(i),name='f.txt',page=1,text=('主题 PDF density. '*400)+f' end{i}') for i in range(3)]
        result=await generator.generate(snap,'course','Probability','',pages,'manifest',lambda *args:None)
        self.assertEqual(result['course_name'],'Probability')
        payloads=[json.loads(m[1].content) for m in model.messages]
        originals=[row['text'] for payload in payloads for row in payload['sources'] if 'text' in row]
        for i in range(3):self.assertIn(f'end{i}',''.join(originals))
        self.assertGreater(len(model.messages),3)
        before=len(model.messages)
        await generator.generate(snap,'course','Probability','',pages,'manifest',lambda *args:None)
        self.assertEqual(len(model.messages),before)
        snap.version='changed';model.bad=1
        await generator.generate(snap,'course','Probability','',[], 'different',lambda *args:None)
        self.assertEqual(len(model.messages),before+2)
        model.bad=2;snap.version='broken'
        with self.assertRaisesRegex(StudyError,'输出结构'):await generator.generate(snap,'course','Probability','',[],'m',lambda *args:None)
        snap.version='limited';snap.profiles['course_overview']['max_model_calls']=1
        with self.assertRaisesRegex(StudyError,'调用上限'):await generator.generate(snap,'course','Probability','',pages,'m',lambda *args:None)

    async def test_completed_batches_reused_after_interrupted_model_call(self):
        model=Model();model.fail_at=2
        generator=OverviewModelGenerator(SimpleNamespace(create=lambda cfg:model),self.store)
        snap=self.registry.snapshot()
        pages=[dict(document_id='d',name='f.txt',page=1,text='density '*3000)]
        with self.assertRaises(RuntimeError):await generator.generate(snap,'course','Probability','',pages,'same',lambda *a:None)
        first_payload=model.messages[0][1].content
        model.fail_at=None
        await generator.generate(snap,'course','Probability','',pages,'same',lambda *a:None)
        self.assertEqual(sum(m[1].content==first_payload for m in model.messages),1)
