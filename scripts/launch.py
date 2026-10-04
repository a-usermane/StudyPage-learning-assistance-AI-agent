import argparse
import importlib.util
import json
import os
from pathlib import Path
import socket
import sys
import threading
import time
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parents[1]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    for module in ("fastapi", "uvicorn", "multipart", "pypdf", "pptx", "deepagents", "langchain_openai", "yaml", "mcp"):
        if importlib.util.find_spec(module) is None:
            raise RuntimeError(f"Missing {module}. Run setup.cmd first.")
    for asset in ("build/pdf.mjs", "build/pdf.worker.mjs", "web/pdf_viewer.mjs", "web/pdf_viewer.css"):
        if not (ROOT / "frontend/vendor/pdfjs" / asset).exists():
            raise RuntimeError("PDF.js incomplete. Run setup.cmd first.")
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", 8000))
        except OSError as error:
            raise RuntimeError("Port 8000 is occupied. Close the application using it or an earlier Study Local window. No process was stopped.") from error
    temporary = ROOT / ".cache/tmp"
    temporary.mkdir(parents=True, exist_ok=True)
    os.environ.update(TEMP=str(temporary), TMP=str(temporary))
    log_folder = ROOT / ".cache/logs"
    log_folder.mkdir(parents=True, exist_ok=True)
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    def open_when_ready():
        for _ in range(100):
            try:
                with urllib.request.urlopen("http://127.0.0.1:8000/api/health", timeout=1) as response:
                    if json.load(response).get("app") == "study-local":
                        webbrowser.open("http://127.0.0.1:8000")
                        return
            except Exception:
                time.sleep(0.2)
        print("Browser not opened: health check timed out. Inspect the log.")
    if not args.no_browser:
        threading.Thread(target=open_when_ready, daemon=True).start()
    print("StudyPage: http://127.0.0.1:8000 | Agent mode follows local configuration | Ctrl+C to stop", flush=True)
    import uvicorn
    from copy import deepcopy
    from uvicorn.config import LOGGING_CONFIG
    log_config = deepcopy(LOGGING_CONFIG)
    log_config["handlers"]["file"] = {"class": "logging.handlers.RotatingFileHandler",
        "filename": str(log_folder / "app.log"), "maxBytes": 2 * 1024 * 1024,
        "backupCount": 2, "encoding": "utf-8", "formatter": "default"}
    log_config["loggers"]["uvicorn"]["handlers"].append("file")
    log_config["loggers"]["uvicorn.access"]["handlers"].append("file")
    uvicorn.run("backend.app:app", host="127.0.0.1", port=8000, access_log=True, log_config=log_config)

if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Startup error: {error}", file=sys.stderr)
        sys.exit(1)
