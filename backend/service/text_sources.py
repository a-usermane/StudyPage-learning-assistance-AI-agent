"""Resolve bounded source context and enforce course ownership."""
import json
from backend.domain.models import StudyError
from backend.domain.text_operations import TextOperationSource

def nearby(text, start, end, limit=2000):
    # Selection is sent separately, so do not repeat a large selection in context.
    marker = '\n[当前选区]\n'
    available = max(0,limit-len(marker))
    before = min(start,available//2)
    after = min(len(text)-end,available-before)
    before = min(start,available-after)
    return (text[start-before:start] + marker + text[end:end+after])[:limit]

class SourceResolver:
    def __init__(self, library):
        self.library = library

    def resolve(self, course_id, selected, source=None, document_id=None, page_start=1, page_end=None):
        if source is None:
            if not document_id:
                return None
            source = dict(kind='document',id=document_id,page_start=page_start,page_end=page_end or page_start)
        try:
            ref = TextOperationSource(**source)
        except (TypeError, ValueError):
            raise StudyError('选区来源格式无效。') from None
        if ref.kind not in {'document','message','note'}:
            raise StudyError('选区来源类型无效。')
        if document_id and (ref.kind != 'document' or ref.id != document_id or ref.page_start != page_start or (ref.page_end or ref.page_start) != (page_end or page_start)):
            raise StudyError('新旧来源信息不一致。')
        if ref.kind == 'document':
            doc, loc = self.library.source(course_id,ref.id,ref.page_start,ref.page_end)
            text = self.library.repository.page_text(ref.id,ref.page_start,ref.page_start)
            start = text.find(selected) if selected else 0
            local = nearby(text,start,start+len(selected)) if start >= 0 else text[:2000]
            return dict(kind='document',id=ref.id,**loc.snapshot(doc),selected_text=selected,local_context=local)
        repo = self.library.repository
        row = repo.message(ref.id) if ref.kind == 'message' else repo.note(ref.id)
        if row['course_id'] != course_id:
            raise StudyError('选区来源不属于当前课程。',404)
        field = 'content' if ref.kind == 'message' else ref.text_field
        if field not in ({'content'} if ref.kind == 'message' else {'body','selected_text'}):
            raise StudyError('选区字段无效。')
        text = row[field]
        if (type(ref.start) is not int or type(ref.end) is not int or not 0 <= ref.start <= ref.end <= len(text)
            or text[ref.start:ref.end] != selected):
            raise StudyError('选区位置或文字与来源不一致，请重新选择。')
        return dict(kind=ref.kind,id=ref.id,start=ref.start,end=ref.end,text_field=field,
                    document_id=None,page_start=1,page_end=1,name='对话消息' if ref.kind=='message' else '笔记',
                    selected_text=selected,local_context=nearby(text,ref.start,ref.end),
                    related_document_id=row.get('document_id'),
                    citations=row.get('citations',[]) if ref.kind=='message' else (json.loads(row.get('source_json','null')) or {}).get('citations',[]))
