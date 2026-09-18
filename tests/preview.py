"""Local UI preview only. Run from the repository root; never used by Docker."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app
from support import MemoryRuns, config
import uvicorn

cfg=config()
uvicorn.run(create_app(cfg, MemoryRuns(cfg)),host='127.0.0.1',port=8095)
