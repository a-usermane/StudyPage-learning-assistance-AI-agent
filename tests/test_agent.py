"""Real runtime tests with deterministic model, SQLite and local MCP; no paid API."""
import asyncio
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from backend.config import ROOT
from backend.domain.agent import AgentRequest
from backend.domain.models import StudyError
from backend.dp.database import initialize, SQLiteLibraryRepository, connection
from backend.dp.files import LocalFileStore
from backend.dp.parsers import LocalDocumentParser
from backend.dp.demo import DemoAnswerProvider
from backend.dp.agent_config import LocalProfileRegistry
from backend.dp.agent_storage import SQLiteSessionStore, AgentRecordStore
from backend.dp.retrieval import SQLiteRetriever
from backend.dp.agent_runtime import LearningRuntime
from backend.dp.mcp_tools import MCPConnections
from backend.service.library import LibraryService
from backend.service.learning import LearningService

class TestModel(BaseChatModel):
    bound: list = []
    slow: bool = False
    @property
    def _llm_type(self): return "study-test"
    def bind_tools(self, tools, **kwargs):
        return self.model_copy(update={"bound":[getattr(t,"name",None) for t in tools]})
    def answer(self, messages):
        user = next((m for m in reversed(messages) if m.type=="human"),None)
        content = str(user.content) if user else ""
        if str(messages[0].content).startswith("压缩为简短会话摘要") or "Context Extraction Assistant" in str(messages[0].content):
            return AIMessage(content="用户正在学习梯度下降，偏好中文解释。")
        after = messages[messages.index(user)+1:] if user else []
        prior_tools = [m for m in after if m.type=="tool"]
        if self.bound and not prior_tools:
            name = "execute" if "bad-tool" in content else "search_documents"
            return AIMessage(content="",tool_calls=[{"name":name,"args":{"query":"gradient descent"},"id":"search1","type":"tool_call"}])
        if "read_file" in self.bound and len(prior_tools)==1 and "skill-test" in content:
            return AIMessage(content="",tool_calls=[{"name":"read_file","args":{"file_path":"/skills/course-concepts/SKILL.md"},"id":"skill1","type":"tool_call"}])
        refs = []
        import re
        for m in prior_tools:
            refs += re.findall(r'"id":\s*"([a-f0-9]{24})"',str(m.content))
        return AIMessage(content="测试模型回答：梯度下降按负梯度更新参数。"+(" [ref:"+refs[0]+"]" if refs else ""))
    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=self.answer(messages))])
    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        if self.slow: await asyncio.sleep(10)
        answer = self.answer(messages)
        if answer.tool_calls:
            call = answer.tool_calls[0]
            yield ChatGenerationChunk(message=AIMessageChunk(content="",tool_call_chunks=[{"name":call["name"],"args":json.dumps(call["args"]),"id":call["id"],"index":0}]))
        else:
            for part in [answer.content[:8],answer.content[8:]]:
                yield ChatGenerationChunk(message=AIMessageChunk(content=part))

class TestGateway:
    def __init__(self): self.slow = False
    def create(self, config): return TestModel(slow=self.slow)

class AgentTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        (ROOT/'.cache/tests').mkdir(parents=True,exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=ROOT/'.cache/tests')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        repo = SQLiteLibraryRepository(initialize(self.root))
        self.library = LibraryService(repo,LocalFileStore(self.root,self.root/'uploads'),LocalDocumentParser(),DemoAnswerProvider(),20*1024*1024)
        self.course = self.library.create_course("学习")['id']
        self.doc = self.library.import_document(self.course,"lesson.txt","other",io.BytesIO(b"Gradient descent updates parameters along the negative gradient."))['id']
        self.other = self.library.create_course("另一课程")['id']
        self.otherdoc = self.library.import_document(self.other,"secret.txt","other",io.BytesIO(b"secret course content"))['id']
        self.addCleanup(patch.stopall)
        patch.dict(os.environ,{"STUDY_API_KEY":"fake-not-a-real-key"}).start()
        self.registry = LocalProfileRegistry(ROOT)
        self.retriever = SQLiteRetriever(repo)
        self.mcp = MCPConnections()
        self.gateway = TestGateway()
        self.runtime = LearningRuntime(self.gateway,self.mcp,self.root/'db/checkpoints.db')
        self.sessions = SQLiteSessionStore(self.root/'db/agent-sessions.db')
        self.learning = LearningService(self.library,self.registry,self.runtime,self.retriever,self.sessions,AgentRecordStore(repo),self.mcp)
        self.addAsyncCleanup(self.learning.close)

    def request(self, **kwargs):
        return AgentRequest(course_id=self.course,document_id=self.doc,question="什么是梯度下降？",mode="live",**kwargs)

    async def collect(self, request):
        context = self.learning.prepare(request)
        queue,task = self.learning.start(context)
        events = [e async for e in self.learning.events(context,queue,task)]
        return context,events

    async def test_deep_agent_tool_search_citation_history(self):
        context,events = await self.collect(self.request())
        errors = [e.data for e in events if e.type=='error']
        self.assertFalse(errors,errors)
        done = next(e.data for e in events if e.type=='done')
        self.assertEqual(done['mode'],'live')
        self.assertEqual(done['citations'][0]['document_id'],self.doc)
        self.assertTrue(any(e.type=='tool' for e in events))
        self.assertEqual(len(self.library.history(self.course)),2)
        self.assertTrue(self.sessions.load(context.thread_id)['messages'])
        self.assertFalse(set(context.metadata['exposed_tools']) & {'execute','task','write_file','delete'})

    async def test_translation_explanation_isolated_and_transfer_idempotent(self):
        translated,events = await self.collect(self.request(action='translate',selected_text='Gradient descent',session_id='selection',persist=False))
        self.assertTrue(any(e.type=='done' for e in events),events)
        explained,events = await self.collect(self.request(action='explain',selected_text='Gradient descent',session_id='selection',persist=False))
        self.assertTrue(any(e.type=='done' for e in events),events)
        self.assertNotEqual(translated.thread_id,explained.thread_id)
        self.assertEqual(self.library.history(self.course),[])
        await self.learning.transfer(self.course,translated.run_id)
        await self.learning.transfer(self.course,translated.run_id)
        self.assertEqual(len(self.library.history(self.course)),2)
        resumed = SQLiteSessionStore(self.sessions.path).load(translated.thread_id)
        self.assertEqual(len(resumed['messages']),2)

    async def test_detailed_explanation_uses_own_prompt_thread_and_scope(self):
        args=dict(selected_text='Gradient descent',session_id='details',persist=False)
        brief,_ = await self.collect(self.request(action='explain',**args))
        request=AgentRequest(self.course,action='explain_detail',document_id=self.doc,mode='live',**args)
        context,events = await self.collect(request)
        self.assertTrue(any(e.type=='done' for e in events),events)
        self.assertNotEqual(brief.thread_id,context.thread_id)
        self.assertIn('详细解释',context.prompt)
        self.assertIn('小例子',context.prompt)
        self.assertNotEqual(context.prompt,brief.prompt)
        self.assertTrue(self.sessions.load(context.thread_id)['messages'])
        resumed=self.learning.prepare(request)
        self.assertEqual(resumed.thread_id,context.thread_id)
        with self.assertRaises(StudyError):context.tools.read_pages(self.otherdoc,1)
        extra=self.library.import_document(self.course,'second.txt','other',io.BytesIO(b'Another file.'))['id']
        with self.assertRaises(StudyError):context.tools.search_documents('another',extra,'course')
        with self.assertRaises(StudyError):self.learning.prepare(self.request(action='explain_detail',selected_text=''))
        self.assertEqual(self.library.history(self.course),[])
        await self.learning.transfer(self.course,context.run_id)
        self.assertEqual(self.library.history(self.course)[0]['content'],'详细解释选区')
        _,demo=await self.collect(AgentRequest(self.course,action='explain_detail',document_id=self.doc,selected_text='Gradient descent',mode='demo',persist=False))
        self.assertTrue(any(e.type=='done' and '详细解释需连接真实 AI' in e.data['content'] for e in demo),demo)

    async def test_scope_citation_and_deletion(self):
        with self.assertRaises(StudyError): self.learning.prepare(AgentRequest(self.course,document_id=self.otherdoc,question='x'))
        context = self.learning.prepare(self.request())
        with self.assertRaises(StudyError): context.tools.read_pages(self.otherdoc,1)
        self.assertEqual(context.tools.citations('[ref:fake]'),[])
        rows = context.tools.current()
        self.assertTrue(rows)
        self.library.delete_document(self.doc)
        self.assertEqual(self.retriever.search(self.course,'Gradient'),[])
        self.assertEqual(context.tools.citations('[ref:'+rows[0]['id']+']'),[])

    async def test_cancel_does_not_commit_partial_session(self):
        self.gateway.slow = True
        context = self.learning.prepare(self.request(action='translate',selected_text='Gradient'))
        queue,task = self.learning.start(context)
        await asyncio.sleep(.05)
        self.learning.cancel(self.course,context.run_id)
        events = [e async for e in self.learning.events(context,queue,task)]
        self.assertTrue(any(e.type=='cancelled' for e in events))
        self.assertEqual(self.library.history(self.course),[])
        self.assertEqual(self.sessions.load(context.thread_id)['messages'],[])

    async def test_skill_loaded_and_mcp_is_real_offline_tool(self):
        context,events = await self.collect(AgentRequest(self.course,question='skill-test',document_id=self.doc,mode='live'))
        self.assertFalse([e.data for e in events if e.type=='error'],events)
        self.assertTrue(any(e.type=='tool' and e.data['name']=='read_file' for e in events))
        tools = await self.mcp.tools(self.registry.snapshot(),['terminology'])
        self.assertTrue(tools)
        result = await self.mcp.call(tools[0][1],{'term':'gradient descent'})
        self.assertIn('梯度下降',str(result))

    async def test_config_reload_atomic_plugin_switch_and_secret_hidden(self):
        for name in ('config','prompts','skills','plugins'):
            shutil.copytree(ROOT/name,self.root/name)
        registry = LocalProfileRegistry(self.root)
        version = registry.snapshot().version
        (self.root/'config/agents.yaml').write_text('invalid: true',encoding='utf-8')
        with self.assertRaises(StudyError): registry.reload()
        self.assertEqual(registry.snapshot().version,version)
        self.assertNotIn('fake-not-a-real-key',json.dumps(registry.status()))
        shutil.copyfile(ROOT/'config/agents.yaml',self.root/'config/agents.yaml')
        file = self.root/'plugins/academic-helper/plugin.yaml'
        file.write_text(file.read_text(encoding='utf-8').replace('enabled: true','enabled: false'),encoding='utf-8')
        registry.reload()
        self.assertEqual(registry.snapshot().profiles['ask']['skills'],[])
        self.assertFalse(registry.snapshot().mcp['terminology']['enabled'])

    async def test_demo_explicit_and_live_failure_never_demo(self):
        _,events = await self.collect(AgentRequest(self.course,question='x',document_id=self.doc,mode='demo'))
        self.assertTrue(any(e.type=='done' and e.data['mode']=='demo' for e in events))
        class Failing:
            async def stream(self,*args):
                raise RuntimeError('secret key and provider body should not leak')
                yield
        self.learning.runner = Failing()
        _,events = await self.collect(self.request())
        self.assertTrue(any(e.type=='error' for e in events))
        self.assertFalse(any(e.type=='done' for e in events))
        self.assertNotIn('secret key',str(events))

    async def test_forbidden_tool_is_rejected(self):
        _,events = await self.collect(AgentRequest(self.course,question='bad-tool',document_id=self.doc,mode='live'))
        self.assertTrue(any(e.type=='error' for e in events),events)

    async def test_long_context_compression_and_serial_runs(self):
        from langchain_core.messages import HumanMessage, messages_to_dict
        context = self.learning.prepare(self.request(action='translate',selected_text='Gradient',session_id='long',persist=False))
        history = []
        for number in range(12):
            history.extend([HumanMessage(content='旧问题'+str(number)+'x'*1400),AIMessage(content='旧回答'+'y'*1400)])
        self.sessions.save(context.thread_id,self.course,'translate',messages_to_dict(history),'')
        queue,task = self.learning.start(context)
        events = [e async for e in self.learning.events(context,queue,task)]
        self.assertFalse([e.data for e in events if e.type=='error'],events)
        stored = self.sessions.load(context.thread_id)
        self.assertTrue(stored['summary'])
        self.assertLess(len(stored['messages']),len(history))
        requests = [self.request(action='translate',selected_text='Gradient',session_id='serial',persist=False) for _ in range(2)]
        await asyncio.gather(*(self.collect(r) for r in requests))
        serial = self.learning.prepare(requests[0])
        self.assertEqual(len(self.sessions.load(serial.thread_id)['messages']),4)

    async def test_no_file_chat_and_deleted_history_sources(self):
        _,events = await self.collect(AgentRequest(self.course,question='gradient',mode='live'))
        self.assertTrue(any(e.type=='done' for e in events),events)
        self.library.delete_document(self.doc)
        messages = self.library.history(self.course)
        self.assertIsNone(messages[-1]['citations'][0]['document_id'])

    async def test_http_sse_routes_and_missing_key(self):
        import httpx
        from backend.app import create_app
        application = create_app(self.root,service=self.library,learning=self.learning)
        async with application.router.lifespan_context(application):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application),base_url='http://testserver') as client:
                status = await client.get('/api/agent/status')
                self.assertEqual(status.status_code,200)
                self.assertNotIn('fake-not-a-real-key',status.text)
                response = await client.post('/api/courses/'+self.course+'/agent/runs',json={'question':'gradient','document_id':self.doc,'mode':'live'})
                self.assertEqual(response.status_code,200)
                self.assertIn('text/event-stream',response.headers['content-type'])
                self.assertIn('event: done',response.text)
                self.assertIn('event: tool',response.text)
                bad = await client.post('/api/courses/'+self.course+'/agent/runs',json={'question':'x','document_id':self.otherdoc})
                self.assertEqual(bad.status_code,400)
                unknown = await client.post('/api/courses/'+self.other+'/agent/runs/unknown/transfer',json={})
                self.assertEqual(unknown.status_code,404)

    async def test_generic_sources_http_context_notes_and_transfer(self):
        import httpx
        from backend.app import create_app
        from backend.domain.models import Message,new_id,now
        from types import SimpleNamespace
        message_id=new_id();text='🙂 The PDF integrates to one. '+('unrelated history '*300)
        self.library.repository.add_messages([Message(message_id,self.course,None,'课程问答','assistant',text,1,1,'','ask',now())])
        source=dict(kind='message',id=message_id,start=text.index('PDF'),end=text.index('PDF')+3)
        seen=[]
        class CapturingModel:
            async def astream(self,messages):
                seen.append(messages)
                yield AIMessageChunk(content='概率密度函数')
        self.runtime.gateway=SimpleNamespace(create=lambda cfg:CapturingModel())
        app=create_app(self.root,service=self.library,learning=self.learning)
        async with app.router.lifespan_context(app):
            overview=app.state.overview
            overview.save(self.course,'学习',['概率论'],'连续随机变量与密度','不要发送此补充说明','0')
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://testserver') as client:
                cp='/api/courses/'+self.course
                payload=dict(action='translate',source=source,selected_text='PDF',persist=False,session_id='same',mode='live')
                response=await client.post(cp+'/agent/runs',json=payload)
                self.assertEqual(response.status_code,200,response.text);self.assertIn('event: done',response.text)
                final=json.loads(next(block.split('data: ')[1] for block in response.text.split('\n\n') if block.startswith('event: done')))
                self.assertEqual(final['citation']['kind'],'message');self.assertIsNone(final['citation']['document_id'])
                self.assertEqual(seen[-1][-1].content.count('<course_context>'),1)
                self.assertNotIn('不要发送此补充说明',seen[-1][-1].content)
                self.assertNotIn(text,seen[-1][-1].content)
                overview.save(self.course,'学习',['概率论'],'更新后的概况','',overview.get(self.course)['version'])
                await client.post(cp+'/agent/runs',json=payload)
                human=[m.content for m in seen[-1] if m.type=='human']
                self.assertEqual(sum(h.count('<course_context>') for h in human),1)
                self.assertIn('更新后的概况',human[-1])
                wrong=await client.post('/api/courses/'+self.other+'/agent/runs',json=payload)
                self.assertEqual(wrong.status_code,404)
                bad=await client.post(cp+'/agent/runs',json={**payload,'document_id':self.doc})
                self.assertEqual(bad.status_code,400)
                note=await client.post(cp+'/notes',json={'source':source,'selected_text':'PDF','body':'自己的理解','demo':False,'run_id':final['run_id']})
                self.assertEqual(note.status_code,201,note.text)
                notes=(await client.get(cp+'/notes')).json();self.assertEqual(notes[0]['source']['id'],message_id)
                mismatch=await client.post(cp+'/notes',json={'document_id':self.doc,'selected_text':'PDF','body':'note','run_id':final['run_id']})
                self.assertEqual(mismatch.status_code,400)
                transfer=await client.post(cp+'/agent/runs/'+final['run_id']+'/transfer')
                self.assertEqual(transfer.status_code,200,transfer.text)
                history=(await client.get(cp+'/messages')).json()
                self.assertEqual(history[-1]['source']['id'],message_id)
                self.assertIsNone(history[-1]['document_id'])

    async def test_overview_http_generation_status_conflict_and_pending(self):
        import httpx
        from backend.app import create_app
        app=create_app(self.root,service=self.library,learning=self.learning)
        class Generator:
            async def generate(self,snapshot,cid,name,supplement,pages,manifest,progress):
                progress('读取全部资料',1)
                return dict(course_name=name,fields=['计算机科学'],main_content='学习优化算法。')
        async with app.router.lifespan_context(app):
            app.state.overview.generator=Generator()
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://testserver') as client:
                path='/api/courses/'+self.course+'/overview'
                value=(await client.get(path)).json();self.assertEqual(value['version'],'0')
                pending=(await client.post(path+'/runs',json={'mode':'demo','initial':True})).json()
                self.assertEqual(pending['status'],'pending')
                payload=dict(course_name='学习',fields=['算法'],main_content='原概况',supplement='说明',expected_version='0')
                saved=await client.put(path,json=payload);self.assertEqual(saved.status_code,200,saved.text)
                self.assertEqual((await client.put(path,json=payload)).status_code,409)
                run=(await client.post(path+'/runs',json={'mode':'live'})).json()
                task=app.state.overview.active.get(self.course)
                if task:await task[0]
                status=(await client.get(path+'/runs/'+run['run_id'])).json()
                self.assertEqual(status['status'],'complete',status)
                self.assertEqual((await client.get(path)).json()['main_content'],'学习优化算法。')
                self.assertEqual((await client.get('/api/courses/'+self.other+'/overview/runs/'+run['run_id'])).status_code,404)
                self.assertEqual((await client.post(path+'/runs/'+run['run_id']+'/cancel')).status_code,200)

    async def test_deep_history_compaction_persists_internal_artifacts(self):
        from langchain_core.messages import HumanMessage, messages_to_dict
        context = self.learning.prepare(self.request())
        history = []
        for number in range(12):
            history.extend([HumanMessage(content='prior question '+str(number)+'x'*600),AIMessage(content='prior answer '+'y'*600)])
        self.sessions.save(context.thread_id,self.course,'ask',messages_to_dict(history),'')
        queue,task = self.learning.start(context)
        events = [e async for e in self.learning.events(context,queue,task)]
        self.assertFalse([e.data for e in events if e.type=='error'],events)
        stored = self.sessions.load(context.thread_id)
        self.assertLess(len(stored['messages']),len(history))
        self.assertTrue(any(p.startswith('/conversation_history/') for p in stored['artifacts']))
        _,resumed = await self.collect(self.request())
        self.assertFalse([e.data for e in resumed if e.type=='error'],resumed)

    async def test_blank_summary_and_timeout(self):
        with connection(self.library.repository.path) as db:
            db.execute('UPDATE pages SET text=? WHERE document_id=?',('',self.doc))
        with self.assertRaisesRegex(StudyError,'OCR'):
            self.learning.prepare(self.request(action='summary'))
        context = self.learning.prepare(self.request(action='translate',selected_text='Gradient'))
        context.profile['timeout'] = .02
        self.gateway.slow = True
        queue,task = self.learning.start(context)
        events = [e async for e in self.learning.events(context,queue,task)]
        self.assertTrue(any(e.type=='error' and '超时' in e.data['detail'] for e in events))
        self.assertEqual(self.library.history(self.course),[])

    async def test_cancel_before_task_starts_and_subsequent_request(self):
        context = self.learning.prepare(self.request(action='translate',selected_text='Gradient'))
        queue,task = self.learning.start(context)
        self.learning.cancel(self.course,context.run_id)
        async with asyncio.timeout(3):
            events = [e async for e in self.learning.events(context,queue,task)]
        self.assertTrue(any(e.type=='cancelled' for e in events))
        _,resumed = await self.collect(self.request(action='translate',selected_text='Gradient'))
        self.assertTrue(any(e.type=='done' for e in resumed))

if __name__=='__main__': unittest.main()
