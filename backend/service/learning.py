"""Learning orchestration: validation, isolation, cancellation and result commits."""
import asyncio
import json
import re
from backend.domain.agent import RunContext, RunEvent
from backend.domain.models import Message, StudyError, new_id, now
from backend.service.agent_tools import CourseTools

class LearningService:
    def __init__(self, library, registry, runner, retriever, sessions, records, mcp):
        self.library, self.registry, self.runner = library, registry, runner
        self.retriever, self.sessions, self.records, self.mcp = retriever, sessions, records, mcp
        self.active, self.locks = {}, {}
        self.closed = False

    def status(self):
        result = self.registry.status()
        result["mcp_connections"] = dict(self.mcp.states)
        result["active_runs"] = len(self.active)
        return result

    def save_api_key(self, model_id, api_key):
        self.registry.save_api_key(model_id, api_key)
        return self.status()

    def prepare(self, request):
        if self.closed:
            raise StudyError("服务正在关闭。",503)
        self.library.get_course(request.course_id)
        if request.action not in {"ask","translate","explain","summary"}:
            raise StudyError("学习功能无效。")
        if len(request.selected_text)>5000 or len(request.question)>2000:
            raise StudyError("选区或问题超过字符上限。")
        if request.action=="ask" and not request.question.strip():
            raise StudyError("请输入问题。")
        if request.action in {"translate","explain"} and not request.selected_text.strip():
            raise StudyError("请先选择文字。")
        if request.action!="ask" and not request.document_id:
            raise StudyError("此功能需要当前资料。")
        source = None
        if request.document_id:
            doc, location = self.library.source(request.course_id,request.document_id,request.page_start,request.page_end)
            source = {**location.snapshot(doc),"selected_text":request.selected_text}
        snapshot = self.registry.snapshot()
        mode = request.mode or snapshot.mode
        if mode not in {"demo","live"}:
            raise StudyError("运行模式无效。")
        profile = snapshot.profiles[request.action]
        if mode=='live' and request.action=='summary' and not self.library.repository.page_text(request.document_id,request.page_start,request.page_start).strip():
            raise StudyError("本页没有可提取正文，无法总结；扫描 PDF 首版不支持 OCR。")
        if mode=="live":
            model = snapshot.models[profile["model"]]
            if not model.get("api_key"):
                raise StudyError("未配置模型密钥，请在设置中保存 API Key，或选择演示模式。",503)
        if request.session_id and not re.fullmatch(r"[A-Za-z0-9_-]{1,64}",request.session_id):
            raise StudyError("会话 ID 无效。")
        if request.persist:
            thread = f"course:{request.course_id}:chat:{mode}"
        else:
            # Include immutable source in the key; client ids cannot mix different files/selections.
            import hashlib
            fingerprint = hashlib.sha256(json.dumps(source,sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:16]
            thread = f"selection:{request.course_id}:{request.session_id or new_id()}:{fingerprint}:{request.action}:{mode}"
        run_id = new_id()
        tools = CourseTools(self.library.repository,self.retriever,request,profile.get("tools",[]),profile["max_tool_calls"])
        context = RunContext(run_id,thread,request,snapshot,profile,mode,tools,source=source,
                             prompt=snapshot.prompts["base"]+'\n\n'+snapshot.prompts[request.action])
        self.sessions.run(run_id,request.course_id,thread,"queued",snapshot.version)
        return context

    def start(self, context):
        queue = asyncio.Queue(maxsize=128)
        async def produce():
            status, content = "error", ""
            try:
                async with asyncio.timeout(context.profile["timeout"]):
                    lock = self.locks.setdefault(context.thread_id,asyncio.Lock())
                    async with lock:
                        stored = self.sessions.load(context.thread_id)
                        context.history = stored["messages"]
                        context.metadata["summary"] = stored["summary"]
                        context.metadata["artifacts"] = stored.get("artifacts",{})
                        self.sessions.run(context.run_id,context.request.course_id,context.thread_id,"running",context.snapshot.version)
                        if context.mode=="demo":
                            request = context.request
                            if request.document_id:
                                result = self.library.answer(request.course_id,request.document_id,request.page_start,request.action,
                                          request.selected_text,request.question,request.page_end,persist=False)
                                content = result["content"]
                            else:
                                content = "演示模式，未连接 AI\n问题："+request.question+"\n请配置模型以使用课程检索问答。"
                            await queue.put(RunEvent("delta",{"text":content}))
                        else:
                            async for event in self.runner.stream(context.request,context):
                                if event.type=="delta":
                                    content += event.data.get("text","")
                                    await queue.put(event)
                                elif event.type=="answer":
                                    content = event.data["content"]
                                else:
                                    await queue.put(event)
                        if not content.strip():
                            raise StudyError("模型未返回答案。")
                        citations = context.tools.citations(content) if context.mode=="live" else []
                        valid = {c["id"] for c in citations}
                        content = re.sub(r"\[ref:([A-Za-z0-9_-]+)\]",lambda m: f"[{next(i+1 for i,c in enumerate(citations) if c['id']==m[1])}]" if m[1] in valid else "[来源未验证]",content)
                        messages = self._messages(context.request.course_id,context.request.action,context.request.question,
                                                  content,context.source,citations) if context.request.persist else []
                        self.records.save(context,content,citations,messages)
                        if context.mode=="live":
                            self.sessions.save(context.thread_id,context.request.course_id,context.request.action,
                                               context.metadata.get("messages",[]),context.metadata.get("summary",""),context.metadata.get("artifacts",{}))
                        await queue.put(RunEvent("citations",{"items":citations}))
                        await queue.put(RunEvent("done",{"run_id":context.run_id,"session_id":context.request.session_id,
                          "mode":context.mode,"content":content,"citations":citations,
                          "citation":citations[0] if citations else context.source,"version":context.snapshot.version}))
                        status = "complete"
            except asyncio.CancelledError:
                status = "cancelled"
                # An abandoned reader must not block cancellation on a full queue.
                while queue.full(): queue.get_nowait()
                queue.put_nowait(RunEvent("cancelled",{"detail":"生成已停止。"}))
            except TimeoutError:
                await queue.put(RunEvent("error",{"detail":"生成超时，请重试或缩小问题范围。"}))
            except Exception as error:
                detail = str(error) if isinstance(error,StudyError) else "模型或工具请求失败，请检查接口、模型能力及网络后重试。"
                await queue.put(RunEvent("error",{"detail":detail}))
            finally:
                self.sessions.run(context.run_id,context.request.course_id,context.thread_id,status,context.snapshot.version)
                self.active.pop(context.run_id,None)
                # Release unused per-thread locks, including short-lived selection threads.
                if not any(c.thread_id==context.thread_id for _,c in self.active.values()):
                    self.locks.pop(context.thread_id,None)
                while queue.full(): queue.get_nowait()
                queue.put_nowait(None)
        task = asyncio.create_task(produce())
        self.active[context.run_id] = (task,context)
        def finished(value):
            # A task cancelled before its first execution never reaches produce's finally.
            if value.cancelled() and context.run_id in self.active:
                self.active.pop(context.run_id,None)
                self.sessions.run(context.run_id,context.request.course_id,context.thread_id,'cancelled',context.snapshot.version)
                while queue.full(): queue.get_nowait()
                queue.put_nowait(RunEvent('cancelled',{'detail':'生成已停止。'}))
                while queue.full(): queue.get_nowait()
                queue.put_nowait(None)
        task.add_done_callback(finished)
        return queue,task

    async def events(self, context, queue, task):
        try:
            yield RunEvent("start",{"run_id":context.run_id,"mode":context.mode,"version":context.snapshot.version})
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield event
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task,return_exceptions=True)

    def cancel(self, course_id, run_id):
        value = self.active.get(run_id)
        if value:
            task,context = value
            if context.request.course_id != course_id:
                raise StudyError("运行不属于当前课程。",404)
            task.cancel()
        return {"ok":True}

    async def close(self):
        self.closed = True
        tasks = [task for task,_ in self.active.values()]
        for task in tasks: task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)

    def _messages(self, course_id, action, question, content, source, citations):
        source = source or (citations[0] if citations else None)
        if source and source.get("document_id"):
            try:
                self.library.source(course_id,source["document_id"],source["page_start"],source["page_end"])
            except StudyError:
                source = {**source,"document_id":None}
        source = source or {"document_id":None,"name":"课程问答","page_start":1,"page_end":1}
        common = dict(course_id=course_id,document_id=source["document_id"],name=source["name"],
                      page_start=source["page_start"],page_end=source["page_end"],selected_text=source.get("selected_text",""),action=action)
        label = question or {"translate":"翻译选区","explain":"解释选区","summary":"总结当前页"}.get(action,"课程问题")
        return [Message(new_id(),role="user",content=label,created_at=now(),**common),
                Message(new_id(),role="assistant",content=content,created_at=now(),**common)]

    async def transfer(self, course_id, run_id):
        self.library.get_course(course_id)
        # Lock both possible main modes: transfers never overwrite an in-flight main conversation.
        threads = [f"course:{course_id}:chat:{mode}" for mode in ('demo','live')]
        from contextlib import AsyncExitStack
        async with AsyncExitStack() as stack:
            for thread in threads:
                await stack.enter_async_context(self.locks.setdefault(thread,asyncio.Lock()))
            row = self.records.transfer(course_id,run_id,lambda r:self._messages(course_id,r["action"],r["question"],r["content"],json.loads(r["source"]),json.loads(r["citations"])))
            if not row:
                raise StudyError("回复不存在或不属于此课程。",404)
            if not row['transferred'] and row['mode']=='live':
                thread = f"course:{course_id}:chat:live"
                stored = self.sessions.load(thread)
                source = json.loads(row['source'])
                user = row['question'] or {'translate':'翻译选区','explain':'解释选区'}.get(row['action'],'选区问题')
                pair = [{'type':'human','data':{'content':user+'\n选区来源：'+json.dumps(source,ensure_ascii=False)}},
                        {'type':'ai','data':{'content':row['content']}}]
                self.sessions.save(thread,course_id,'ask',stored['messages']+pair,stored['summary'],stored.get('artifacts',{}))
            return {"ok":True}
