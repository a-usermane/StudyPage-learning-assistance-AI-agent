"""Project-local, repeatable installation; no global packages or environment edits."""
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import urllib.request
import venv

ROOT = Path(__file__).resolve().parents[1]
VERSION = "6.3.289"
INTEGRITY = "ZHjSVpDa3D6izMq8/04lvkhkATUmL9px6ChPaXc1k6nU2Mrhlg1/7F0bdUqCwUjw3NsPTfPZsMDUU6ZIcRaeQw=="

def main():
    if sys.version_info < (3, 11):
        raise RuntimeError("Python 3.11 or later is required.")
    for name in ("tmp", "pip", "npm", "wheels"):
        (ROOT / ".cache" / name).mkdir(parents=True, exist_ok=True)
    os.environ.update(TEMP=str(ROOT / ".cache/tmp"), TMP=str(ROOT / ".cache/tmp"),
                      PIP_CACHE_DIR=str(ROOT / ".cache/pip"),
                      npm_config_cache=str(ROOT / ".cache/npm"), PYTHONUTF8="1")
    python = ROOT / ".venv/Scripts/python.exe"
    if not python.exists():
        print("Creating virtual environment on D: ...", flush=True)
        venv.EnvBuilder(with_pip=True).create(ROOT / ".venv")
    requirement = ROOT / "requirements.lock.txt"
    if not requirement.exists():
        requirement = ROOT / "requirements.txt"
    wheels = ROOT / ".cache/wheels"
    pip = [str(python), "-m", "pip", "--disable-pip-version-check"]
    # Resolve locally first. A completed setup can run again without internet.
    installed = subprocess.run(pip + ["install", "--no-index", "--find-links", str(wheels),
                                     "-r", str(requirement)], cwd=ROOT).returncode == 0
    if not installed:
        subprocess.run(pip + ["download", "--only-binary=:all:", "-d", str(wheels),
                              "-r", str(requirement)], cwd=ROOT, check=True)
        subprocess.run(pip + ["install", "--no-index", "--find-links", str(wheels),
                              "-r", str(requirement)], cwd=ROOT, check=True)
    locked = subprocess.check_output(pip + ["freeze"], cwd=ROOT, text=True)
    (ROOT / "requirements.lock.txt").write_text(locked, encoding="utf-8")
    archive = ROOT / f".cache/pdfjs-dist-{VERSION}.tgz"
    if not archive.exists() or base64.b64encode(hashlib.sha512(archive.read_bytes()).digest()).decode() != INTEGRITY:
        print(f"Downloading PDF.js {VERSION} ...", flush=True)
        temporary = archive.with_suffix(".download")
        with urllib.request.urlopen(f"https://registry.npmjs.org/pdfjs-dist/-/pdfjs-dist-{VERSION}.tgz", timeout=120) as response:
            with temporary.open("wb") as target:
                while chunk := response.read(1024 * 1024):
                    target.write(chunk)
        if base64.b64encode(hashlib.sha512(temporary.read_bytes()).digest()).decode() != INTEGRITY:
            temporary.unlink(missing_ok=True)
            raise RuntimeError("PDF.js checksum did not match. Please retry.")
        temporary.replace(archive)
    destination = ROOT / "frontend/vendor/pdfjs"
    marker = destination / "package.json"
    complete = marker.exists() and json.loads(marker.read_text(encoding="utf-8")).get("version") == VERSION
    if not complete or not (destination / "build/pdf.worker.mjs").exists():
        destination.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive, "r:gz") as package:
            for member in package.getmembers():
                parts = Path(member.name).parts
                if not parts or parts[0] != "package" or member.issym() or member.islnk():
                    raise RuntimeError("Unexpected PDF.js archive entry.")
                target = destination.joinpath(*parts[1:]).resolve()
                if not target.is_relative_to(destination.resolve()):
                    raise RuntimeError("Unsafe archive path.")
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                elif member.isfile():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with package.extractfile(member) as source, target.open("wb") as output:
                        output.write(source.read())
    print("Setup complete. Packages, caches and PDF.js are inside the project.", flush=True)

if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Setup error: {error}", file=sys.stderr)
        sys.exit(1)
