"""Generic sources: ownership, Unicode offsets, persistence and bounded contexts."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from backend.config import ROOT
from backend.domain.agent import AgentRequest
from backend.domain.models import Message, StudyError, new_id, now
from backend.dp.database import initialize, connection, SQLiteLibraryRepository, create_schema
from backend.dp.agent_storage import migrate_agent_schema
from backend.dp.files import LocalFileStore
from backend.dp.parsers import LocalDocumentParser
from backend.dp.demo import DemoAnswerProvider
from backend.dp.agent_config import LocalProfileRegistry
from backend.dp.agent_runtime import LearningRuntime
from backend.dp.retrieval import SQLiteRetriever
from backend.service.library import LibraryService
from backend.service.text_sources import SourceResolver, nearby
from backend.service.learning import LearningService

class TextSourceTests(unittest.TestCase):
    def setUp(self):
        (ROOT/'.cache/tests').mkdir(parents=True,exist_ok=True)
        tmp=tempfile.TemporaryDirectory(dir=ROOT/'.cache/tests');self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        self.repo=SQLiteLibraryRepository(initialize(self.root))
        self.lib=LibraryService(self.repo,LocalFileStore(self.root,self.root/'uploads'),LocalDocumentParser(),DemoAnswerProvider(),20000000)
        self.course=self.lib.create_course('概率论')['id']
        self.doc=self.lib.import_document(self.course,'lesson.txt','other',io.BytesIO(b'The PDF integrates to one.'))['id']
        self.other=self.lib.create_course('其他')['id']
        self.text='🙂 局部上下文 PDF integrates to one. ' + 'history excluded '*300
        self.message=new_id()
        self.repo.add_messages([Message(self.message,self.course,None,'课程问答','assistant',self.text,1,1,'','ask',now())])
        self.start=self.text.index('PDF')
        self.source=dict(kind='message',id=self.message,start=self.start,end=self.start+3)
        self.resolve=SourceResolver(self.lib).resolve

    def test_message_offsets_course_and_legacy_conflicts(self):
        row=self.resolve(self.course,'PDF',self.source)
        self.assertEqual(row['kind'],'message');self.assertIsNone(row['document_id'])
        self.assertLessEqual(len(row['local_context']),2000)
        self.assertNotIn(self.text,row['local_context'])
        for source,course,selected,legacy in [
            (self.source,self.other,'PDF',None),
            ({**self.source,'start':self.start+1},self.course,'PDF',None),
            (self.source,self.course,'wrong',None),
            (self.source,self.course,'PDF',self.doc),
            ({**self.source,'text_field':'invalid'},self.course,'PDF',self.doc),
            ({**self.source,'id':'missing'},self.course,'PDF',None)]:
            with self.assertRaises(StudyError):self.resolve(course,selected,source,legacy)
        doc=self.resolve(self.course,'PDF',dict(kind='document',id=self.doc,page_start=1),self.doc,1,1)
        self.assertEqual(doc['document_id'],self.doc)
        with self.assertRaises(StudyError):self.resolve(self.course,'PDF',dict(kind='document',id=self.doc,page_start=1),self.doc,2,2)

    def test_notes_roundtrip_nonrecursive_snapshots_and_deleted_original(self):
        saved=self.lib.save_note(self.course,source=self.source,selected_text='PDF',body='概率密度函数')
        notes=self.lib.notes(self.course)
        self.assertIsNone(notes[0]['document_id']);self.assertEqual(notes[0]['source']['id'],self.message)
        ref=dict(kind='note',id=saved['id'],text_field='body',start=0,end=6)
        value=self.resolve(self.course,'概率密度函数',ref)
        self.assertNotIn('history excluded',value['local_context'])
        second=self.lib.save_note(self.course,source=ref,selected_text='概率密度函数',body='我的理解')
        self.assertEqual(self.repo.note(second['id'])['name'],'笔记')
        self.lib.remove_note(saved['id'])
        snapshot=next(n['source'] for n in self.lib.notes(self.course) if n['id']==second['id'])
        self.assertEqual(snapshot['selected_text'],'概率密度函数')
        document_note=self.lib.save_note(self.course,self.doc,1,'PDF','a note')
        self.lib.delete_document(self.doc)
        note=next(n for n in self.lib.notes(self.course) if n['id']==document_note['id'])
        self.assertIsNone(note['source']['document_id']);self.assertTrue(note['source']['deleted'])
        self.assertEqual(note['source']['name'],'lesson.txt')

    def test_empty_selection_can_save_a_completed_message(self):
        self.lib.save_note(self.course,source={**self.source,'start':0,'end':0},body='整条回复')
        with self.assertRaises(StudyError):self.lib.save_note(self.course,source={**self.source,'start':0,'end':0},selected_text='  ')

    def test_background_bound_and_source_fingerprint_context(self):
        self.assertLessEqual(len(nearby('a'*10000,4000,5000)),2000)
        registry=LocalProfileRegistry(ROOT)
        runtime=LearningRuntime(None,None,self.root/'checkpoints.db')
        retriever=SQLiteRetriever(self.repo)
        learning=LearningService(self.lib,registry,runtime,retriever,SimpleNamespace(run=lambda *a:None),None,None)
        learning.overview=SimpleNamespace(context=lambda cid:dict(course_name='概率论',fields=['数学'],main_content='连续随机变量',version='v1',stale=False))
        request=AgentRequest(course_id=self.course,source=self.source,selected_text='PDF',action='translate',persist=False,session_id='fixed',mode='demo')
        context=learning.prepare(request)
        self.assertIsNone(context.request.document_id)
        self.assertEqual(context.tools.allowed,set())
        payload=runtime.input_message(context).content
        self.assertEqual(payload.count('<course_context>'),1)
        self.assertNotIn(self.text,payload)
        self.assertIn('概率论',payload)
        context.history=[{'type':'human','data':{'content':payload}}]
        history=runtime.history(context)
        self.assertNotIn('<course_context>',history[0].content)
        explain=learning.prepare(AgentRequest(course_id=self.course,source=self.source,selected_text='PDF',action='explain',persist=False,mode='demo'))
        self.assertTrue(explain.tools.search_documents('PDF',self.doc))
        other_source={**self.source,'start':self.start+4,'end':self.start+14}
        other=learning.prepare(AgentRequest(course_id=self.course,source=other_source,selected_text='integrates',action='translate',persist=False,session_id='fixed',mode='demo'))
        self.assertNotEqual(context.thread_id,other.thread_id)

    def test_v2_migration_is_backed_up_idempotent_and_preserves_ids(self):
        folder=self.root/'legacy';(folder/'db').mkdir(parents=True)
        dbpath=folder/'db/library.db';create_schema(dbpath)
        with connection(dbpath) as db:
            db.execute("INSERT INTO courses VALUES ('c','旧课程','ready','date')")
            db.execute("INSERT INTO documents VALUES ('d','c','old.txt','.txt','other',3,'sha',1,'','date')")
            db.execute("INSERT INTO messages VALUES ('m','c','d','old.txt','assistant','old',1,1,'old','ask','date')")
            db.execute('PRAGMA user_version=1')
        migrate_agent_schema(dbpath,folder)
        initialize(folder);initialize(folder)
        with connection(dbpath) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],3)
            row=db.execute('SELECT * FROM messages').fetchone()
            self.assertEqual(row['id'],'m');self.assertEqual(json.loads(row['source_json'])['kind'],'document')
        self.assertTrue((folder/'backups/text-sources-v3/library.db').exists())
