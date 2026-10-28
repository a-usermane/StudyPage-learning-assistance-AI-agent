"""Bounded map/reduce summaries via the registered model gateway."""
import hashlib
import json
from langchain_core.messages import SystemMessage, HumanMessage
from backend.domain.models import StudyError
from backend.dp.agent_runtime import text_of, conservative_tokens

class OverviewModelGenerator:
    def __init__(self,gateway,store):
        self.gateway,self.store=gateway,store

    async def generate(self,snapshot,course_id,name,supplement,pages,manifest,progress):
        profile=snapshot.profiles['course_overview']; config=snapshot.models[profile['model']]
        model=self.gateway.create(config)
        prompt=snapshot.prompts['course_overview']
        # Count UTF-8 bytes conservatively, including all message serialization.
        limit=(config['context_budget']-config['output_tokens'])//2
        calls=0
        async def call(stage,rows):
            nonlocal calls
            payload={'stage':stage,'course_name':name,'supplement':supplement,'sources':rows}
            encoded=json.dumps(payload,ensure_ascii=False)
            key=hashlib.sha256((snapshot.version+manifest+encoded).encode()).hexdigest()
            cached=self.store.cached(course_id,key)
            if cached is not None:return cached
            system=SystemMessage(content=prompt)
            user=HumanMessage(content=encoded)
            if conservative_tokens([system,user])>limit:
                raise StudyError('课程概况提示词或批次超过输入预算，请提高预算或精简提示词。')
            parsed=None
            for attempt in range(2):
                calls+=1
                if calls>int(profile.get('max_model_calls',30)):
                    raise StudyError('课程概况达到模型调用上限，未发布不完整结果。')
                progress('正在归纳课程资料',calls)
                try:
                    if config.get('structured_output')=='json_schema':
                        schema={'title':'CourseOverview','type':'object','properties':{'course_name':{'type':'string'},'fields':{'type':'array','items':{'type':'string'}},'main_content':{'type':'string'}},'required':['course_name','fields','main_content'],'additionalProperties':False}
                        parsed=await model.with_structured_output(schema,method='json_schema').ainvoke([system,user])
                    else:
                        response=await model.ainvoke([system,user])
                        parsed=json.loads(text_of(response))
                    if not isinstance(parsed,dict) or set(parsed)!={'course_name','fields','main_content'}:
                        raise ValueError()
                    if parsed['course_name']!=name or not isinstance(parsed['fields'],list) or len(parsed['fields'])>5:
                        raise ValueError()
                    if not all(isinstance(x,str) and x.strip() for x in parsed['fields']) or not isinstance(parsed['main_content'],str) or not parsed['main_content'].strip():
                        raise ValueError()
                    if sum(len(x) for x in [name,parsed['main_content'],*parsed['fields']])>600:
                        raise ValueError()
                    break
                except (ValueError,TypeError,KeyError):
                    if attempt: raise StudyError('课程概况输出结构或长度无效，未保存。') from None
                    user=HumanMessage(content=encoded+'\n上次输出不符合结构，请重新返回恰好三个字段的 JSON，总计最多600字符，不加代码围栏。')
                    if conservative_tokens([system,user])>limit:raise StudyError('修复请求超过预算。')
            self.store.cached(course_id,key,parsed)
            return parsed
        # Reserve more than half of the request for prompt, escaping and supplement.
        fixed=conservative_tokens([SystemMessage(content=prompt),HumanMessage(content=json.dumps({'course_name':name,'supplement':supplement},ensure_ascii=False))])+1000
        capacity=limit-fixed
        if capacity<512:raise StudyError('模型上下文预算不足以生成课程概况。')
        batches=[]; batch=[]; size=0
        for page in pages:
            text=page['text']
            # Character splitting bounded further by actual UTF-8 size.
            pos=0
            while pos<len(text):
                step=max(1,capacity//8)
                part=text[pos:pos+step];pos+=len(part)
                row={k:v for k,v in page.items() if k!='text'};row['text']=part
                cost=len(json.dumps(row,ensure_ascii=False).encode())+4
                if batch and size+cost>capacity:
                    batches.append(batch);batch=[];size=0
                batch.append(row);size+=cost
        if batch:batches.append(batch)
        if not batches:
            return await call('final',[])
        if len(batches)==1:return await call('final',batches[0])
        summaries=[]
        for batch in batches:
            result=await call('extract',batch)
            summaries.append({'document_ids':sorted({p['document_id'] for p in batch}),'overview':result})
        while len(json.dumps(summaries,ensure_ascii=False).encode())>capacity:
            groups=[];group=[];used=0
            for item in summaries:
                cost=len(json.dumps(item,ensure_ascii=False).encode())+4
                if group and used+cost>capacity:groups.append(group);group=[];used=0
                if cost>capacity:raise StudyError('中间概况超过上下文预算。')
                group.append(item);used+=cost
            if group:groups.append(group)
            if len(groups)>=len(summaries):raise StudyError('上下文过小，无法合并课程概况。')
            merged=[]
            for group in groups:
                merged.append({'document_ids':sorted({i for r in group for i in r['document_ids']}),'overview':await call('merge',group)})
            summaries=merged
        return await call('final',summaries)
