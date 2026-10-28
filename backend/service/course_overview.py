"""Course context lifecycle; generated content is weak disambiguation context."""
import asyncio
import hashlib
import json
from backend.domain.models import StudyError,new_id,now
from backend.domain.ports import LibraryRepository
from backend.domain.agent import ProfileRegistry
from backend.domain.text_operations import OverviewStore, OverviewGenerator

class CourseOverviewService:
    def __init__(self,repository: LibraryRepository,registry: ProfileRegistry,store: OverviewStore,generator: OverviewGenerator):
        self.repo,self.registry,self.store,self.generator=repository,registry,store,generator
        self.active={}

    def fingerprint(self,course_id,docs=None):
        docs=self.repo.documents(course_id) if docs is None else docs
        return hashlib.sha256(json.dumps(sorted((d['id'],d['sha256']) for d in docs),sort_keys=True).encode()).hexdigest()

    def get(self,course_id):
        course=self.repo.course(course_id); fingerprint=self.fingerprint(course_id)
        row=self.store.load(course_id) or dict(course_name=course['name'],fields=[],main_content='',supplement='',version='0',origin='missing',coverage={})
        try:
            self.validate(row['course_name'],row['fields'],row['main_content'],row['supplement'])
        except (KeyError,TypeError,StudyError):
            raise StudyError('课程概况文件结构或长度无效，请检查本地概况文件。',503) from None
        return {**row,'stale': bool(row.get('main_content') and row.get('input_fingerprint')!=fingerprint),
                'run':self.store.latest(course_id)}

    @staticmethod
    def validate(course_name,fields,main_content,supplement):
        if not isinstance(main_content,str) or not isinstance(supplement,str) or not isinstance(course_name,str) or not course_name.strip() or len(course_name)>100 or not isinstance(fields,list) or len(fields)>5 or not all(isinstance(f,str) and f.strip() for f in fields):
            raise StudyError('课程名称和领域格式无效。')
        if len(course_name)+sum(len(f) for f in fields)+len(main_content)>600 or len(supplement)>2000:
            raise StudyError('课程概况最多600字符，补充说明最多2000字符。')

    def save(self,course_id,course_name,fields,main_content,supplement,expected_version):
        self.repo.course(course_id); self.validate(course_name,fields,main_content,supplement)
        old=self.store.load(course_id) or {}
        # Supplement-only edits do not claim that stale material was reviewed.
        content_changed=any(old.get(k)!=v for k,v in [('course_name',course_name),('fields',fields),('main_content',main_content)])
        value={**old,'course_name':course_name,'fields':fields,'main_content':main_content,'supplement':supplement,'origin':'manual',
               'input_fingerprint':self.fingerprint(course_id) if content_changed else old.get('input_fingerprint'),
               'coverage':old.get('coverage',{})}
        self.store.save(course_id,value,expected_version)
        return self.get(course_id)

    def context(self,course_id):
        row=self.get(course_id)
        if not row['main_content'].strip():return None
        return {k:row[k] for k in ('course_name','fields','main_content','stale','version')}

    def start(self,course_id,mode=None,initial=False):
        course=self.repo.course(course_id)
        if course_id in self.active:return self.active[course_id][1]
        if initial and (self.store.load(course_id) or self.store.latest(course_id)):
            return self.store.latest(course_id) or {'status':'complete','run_id':None}
        snapshot=self.registry.snapshot(); old=self.get(course_id)
        row=dict(run_id=new_id(),course_id=course_id,status='queued',detail='等待生成',created_at=now(),calls=0,coverage={})
        self.store.run(course_id,row['run_id'],row)
        if (mode or snapshot.mode)!='live':
            row.update(status='pending',detail='演示模式：配置真实模型后可手动生成。')
        elif 'course_overview' not in snapshot.profiles:
            row.update(status='failed',detail='缺少 course_overview 配置，请补充配置后重载。')
        elif not snapshot.models[snapshot.profiles['course_overview']['model']].get('api_key'):
            row.update(status='pending',detail='尚未配置模型密钥，请在设置中保存后重新生成。')
        else:
            docs=self.repo.documents(course_id)
            fingerprint=self.fingerprint(course_id,docs)
            task=asyncio.create_task(self._generate(course_id,course,old,snapshot,row,docs,fingerprint))
            self.active[course_id]=(task,row)
            def finished(done):
                if done.cancelled() and self.active.get(course_id,(None,))[0] is done:
                    row.update(status='cancelled',detail='生成已停止，保留原概况。')
                    self.store.run(course_id,row['run_id'],row);self.active.pop(course_id,None)
            task.add_done_callback(finished)
        self.store.run(course_id,row['run_id'],row)
        return dict(row)

    async def _generate(self,course_id,course,old,snapshot,row,docs,fingerprint):
        def update(detail,calls):
            row.update(status='running',detail=detail,calls=calls)
            self.store.run(course_id,row['run_id'],row)
        try:
            async with asyncio.timeout(snapshot.profiles['course_overview'].get('timeout',300)):
                pages=[]; unread=[];read_pages=0;processed_pages=0
                for doc in docs:
                    for number in range(1,doc['pages']+1):
                        text=self.repo.page_text(doc['id'],number,number)
                        if text.strip():
                            read_pages+=1;pages.append(dict(document_id=doc['id'],name=doc['name'],page=number,text=text))
                        else:unread.append(dict(document_id=doc['id'],name=doc['name'],page=number))
                        processed_pages+=1
                        if processed_pages%20==0:await asyncio.sleep(0)
                row['coverage']={'read_pages':read_pages,'total_pages':sum(d['pages'] for d in docs),'unread_pages':unread,'user_only':not pages}
                if not pages and not old.get('supplement','').strip():
                    raise StudyError('没有可读取正文或补充说明，未调用模型；扫描 PDF 尚不支持 OCR。')
                update('读取资料完成',0)
                result=await self.generator.generate(snapshot,course_id,course['name'],old.get('supplement',''),pages,fingerprint,update)
                self.validate(result['course_name'],result['fields'],result['main_content'],old.get('supplement',''))
                if self.fingerprint(course_id)!=fingerprint:raise StudyError('生成期间资料发生变化，请重新生成。',409)
                self.store.save(course_id,{**result,'supplement':old.get('supplement',''),'origin':'generated','input_fingerprint':fingerprint,
                        'prompt_version':snapshot.version,'coverage':row['coverage']},old['version'])
                row.update(status='complete',detail='课程概况已生成。')
        except asyncio.CancelledError:row.update(status='cancelled',detail='生成已停止，保留原概况。')
        except TimeoutError:row.update(status='failed',detail='生成超时，保留原概况，可重试。')
        except Exception as exc:row.update(status='failed',detail=str(exc) if isinstance(exc,StudyError) else '模型请求失败，请检查接口、网络及模型能力后重试。')
        finally:
            self.store.run(course_id,row['run_id'],row);self.active.pop(course_id,None)

    def run(self,course_id,run_id):
        self.repo.course(course_id)
        row=self.store.run(course_id,run_id)
        if not row:raise StudyError('生成任务不存在。',404)
        return row

    def cancel(self,course_id,run_id):
        self.run(course_id,run_id)
        value=self.active.get(course_id)
        if value and value[1]['run_id']==run_id:value[0].cancel()
        return {'ok':True}

    async def close(self):
        tasks=[t for t,_ in self.active.values()]
        for task in tasks:task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
