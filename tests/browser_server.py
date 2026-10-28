"""Isolated UI fixture. Deterministic model only; never use for normal start."""
from contextlib import asynccontextmanager
from dataclasses import replace
import io
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.app import create_app
from backend.config import ROOT
from test_agent import TestGateway

application = create_app(ROOT/'.cache/browser-test-data')
original = application.router.lifespan_context

@asynccontextmanager
async def fixture(app):
    async with original(app):
        app.state.learning.runner.gateway = TestGateway()
        class OverviewFixture:
            async def generate(self,snapshot,course_id,name,supplement,pages,manifest,progress):
                progress('测试模型正在读取全部资料',1)
                return dict(course_name=name,fields=['计算机科学'],main_content='学习梯度下降、递归与相关算法。')
        app.state.overview.generator = OverviewFixture()
        registry = app.state.learning.registry
        snapshot = registry.snapshot()
        for model in snapshot.models.values(): model['api_key'] = 'test-only'
        registry.current = replace(snapshot,mode='live')
        library = app.state.library
        courses = library.list_courses()
        if not courses:
            course = library.create_course('Agent 界面验证')
            library.import_document(course['id'],'lesson.txt','other',io.BytesIO(b'Gradient descent updates parameters. Recursion is a function calling itself.'))
        yield

application.router.lifespan_context = fixture
if __name__=='__main__':
    import uvicorn
    uvicorn.run(application,host='127.0.0.1',port=8002,access_log=False)
