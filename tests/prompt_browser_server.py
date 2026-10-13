"""Isolated prompt-editor browser fixture; no credentials or paid API calls."""
from pathlib import Path
import shutil
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.config import ROOT
from backend.app import create_app

fixture=ROOT/'.cache/prompt-ui-test'
fixture.mkdir(parents=True,exist_ok=True)
for name in ('config','prompts','skills','plugins'):
    shutil.copytree(ROOT/name,fixture/name,dirs_exist_ok=True)
application=create_app(data_dir=fixture/'data',config_root=fixture)
if __name__=='__main__':
    import uvicorn
    uvicorn.run(application,host='127.0.0.1',port=8003,access_log=False)
