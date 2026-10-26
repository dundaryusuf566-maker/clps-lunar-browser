"""Before pushing to a public repository: is there anything in it that should not be?

    python scripts/prepush_check.py

Looks at every file git would publish (tracked, plus new files that .gitignore does not
exclude) and reports:

  * secrets: private keys, GitHub / AWS / Google / OpenAI-style tokens, .env files,
    "password = ..." lines;
  * personal traces: absolute paths of this computer (C:\\Users\\<name>\\..., /home/<name>/...)
    and e-mail addresses (the git author e-mail is shown separately);
  * size: files over 50 MB (GitHub warns) or 100 MB (GitHub refuses), and the total;
  * the site: web/dist older than the code in web/src (rebuild with npm run build);
  * the forecast: verify_forecast.py, and whether the forecast names a clean commit.

Exit code 1 if something must be fixed before pushing, 0 otherwise (warnings only).
Nothing is changed; this script only reads.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEXT_EXT = {".py", ".ts", ".tsx", ".js", ".mjs", ".json", ".md", ".txt", ".yml", ".yaml", ".toml", ".cfg", ".ini",
            ".html", ".css", ".csv", ".svg", ".bat", ".sh", ".ps1", ".env"}
SECRETS = [
    ("private key", re.compile(r"-----BEGIN (RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY")),
    ("GitHub token", re.compile(r"\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}|\bgithub_pat_[A-Za-z0-9_]{40,}")),
    ("AWS key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("API secret key", re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}")),
    ("password assignment", re.compile(r"(?i)\b(password|passwd|secret|api_key|apikey)\s*[:=]\s*['\"][^'\"]{6,}['\"]")),
]
ABS_PATH = re.compile(r"(?i)\b[A-Z]:\\{1,2}Users\\{1,2}[A-Za-z0-9][^\\\"'\s]*|/home/[a-z_][a-z0-9_\-]*/|/Users/[A-Za-z0-9_\-]+/")
EMAIL = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
# e-mail addresses that are fine in a public repository
EMAIL_OK = re.compile(r"(?i)noreply|example\.(com|org)|@users\.noreply\.github\.com")
WARN_MB, MAX_MB = 50, 100


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True).stdout


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    try:
        files = sorted(set(git("ls-files", "-co", "--exclude-standard", "-z").split("\0")) - {""})
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("Not a git repository yet (or git is not installed): run  git init -b main  first.")
        return 1
    must, warn = [], []
    total = 0
    for rel in files:
        p = ROOT / rel
        if not p.is_file():
            continue
        size = p.stat().st_size
        total += size
        if size > MAX_MB * 1e6:
            must.append(f"{rel}: {size / 1e6:.0f} MB, GitHub refuses files over {MAX_MB} MB")
        elif size > WARN_MB * 1e6:
            warn.append(f"{rel}: {size / 1e6:.0f} MB (GitHub warns over {WARN_MB} MB)")
        name = p.name.lower()
        if name == ".env" or name.startswith(".env.") or p.suffix.lower() in {".pem", ".key", ".p12", ".pfx"}:
            must.append(f"{rel}: looks like a secrets file; add it to .gitignore")
            continue
        if p.suffix.lower() not in TEXT_EXT or size > 20e6:
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        for what, rx in SECRETS:
            if rx.search(text):
                must.append(f"{rel}: {what}")
        m = ABS_PATH.search(text) if rel != "scripts/prepush_check.py" else None
        if m:
            warn.append(f"{rel}: a path of this computer ({m.group(0)[:40]}...)")
        for e in sorted(set(EMAIL.findall(text))):
            if not EMAIL_OK.search(e):
                warn.append(f"{rel}: e-mail address {e}")

    try:
        author = (git("config", "user.email") or "").strip()
    except subprocess.CalledProcessError:
        author = ""
    if author and not re.fullmatch(r"[\x21-\x7e]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", author):
        must.append(f"git user.email is not a real address ({author!r}): set it with  git config user.email \"...\"")
    elif "KOPYALADI" in author.upper() or "KULLANICI" in author.upper():
        must.append("git user.email is still the placeholder from the guide: put your own noreply address there")
    dist, src = ROOT / "web" / "dist" / "index.html", ROOT / "web" / "src"
    if dist.exists() and src.exists():
        newest = max(f.stat().st_mtime for f in src.rglob("*") if f.is_file())
        if dist.stat().st_mtime < newest:
            must.append("web/dist is older than web/src: the site would show old code. Run  cd web && npm run build")
    elif not dist.exists():
        must.append("web/dist is missing: the site workflow publishes it. Run  cd web && npm run build")

    fc = ROOT / "web" / "public" / "data" / "forecast.json"
    if fc.exists():
        ok = subprocess.run([sys.executable, str(ROOT / "scripts" / "verify_forecast.py")], cwd=ROOT,
                            capture_output=True, text=True, encoding="utf-8", errors="replace").returncode == 0
        if not ok:
            must.append("forecast.json does not match its registered sha256 (python scripts/verify_forecast.py)")
        import json
        meta = json.loads(fc.read_text()).get("meta", {})
        if not meta.get("git_commit"):
            warn.append("forecast.json names no git commit: regenerate it after the first commit (docs/KAYIT.md, step 2)")
        elif meta.get("git_code_dirty"):
            warn.append("forecast.json was made with uncommitted code changes (git_code_dirty): regenerate after committing")

    print(f"{len(files)} files would be published, {total / 1e6:.0f} MB in all")
    print(f"git author e-mail: {author or '(not set)'}"
          + ("" if not author or "noreply" in author else
             "  <- public in every commit; GitHub's private address is safer (docs/KAYIT.md, step 1)"))
    for w in warn:
        print(f"  warning  {w}")
    for x in must:
        print(f"  FIX      {x}")
    print("nothing to fix" if not must else f"{len(must)} thing(s) to fix before pushing")
    return 1 if must else 0


if __name__ == "__main__":
    sys.exit(main())
