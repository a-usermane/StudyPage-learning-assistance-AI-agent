"""Transport for course context and bounded background generation."""
from fastapi import APIRouter,Request
from pydantic import BaseModel,Field
from typing import Literal

router=APIRouter(prefix='/api/courses/{course_id}/overview')
class OverviewSave(BaseModel):
    course_name: str = Field(min_length=1,max_length=100)
    fields: list[str] = Field(max_length=5)
    main_content: str = Field(max_length=600)
    supplement: str = Field(default='',max_length=2000)
    expected_version: str = Field(max_length=64)
class GenerateRequest(BaseModel):
    mode: Literal['demo','live'] | None = None
    initial: bool = False

def service(request):return request.app.state.overview
@router.get('')
def get(course_id:str,request:Request):return service(request).get(course_id)
@router.put('')
def save(course_id:str,payload:OverviewSave,request:Request):return service(request).save(course_id,**payload.model_dump())
@router.post('/runs')
async def generate(course_id:str,payload:GenerateRequest,request:Request):return service(request).start(course_id,**payload.model_dump())
@router.get('/runs/{run_id}')
def run(course_id:str,run_id:str,request:Request):return service(request).run(course_id,run_id)
@router.post('/runs/{run_id}/cancel')
async def cancel(course_id:str,run_id:str,request:Request):return service(request).cancel(course_id,run_id)
