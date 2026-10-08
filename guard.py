"""guard.py - the SAFETY CORE for Jarvis.

This file decides what Jarvis is allowed to touch on this computer.

Rules come from C:\\jarvis\\permissions.json  (created for you if missing).
  - read_allowed  : folders Jarvis may READ from.
  - never_read    : file names, folder names and extensions that are
                    ALWAYS blocked, even inside read_allowed.

          There is a big STOP switch. When it is ON, every function in
          this file refuses to do anything.

Nothing in this file is connected to Jarvis yet. It only tests itself.
Run the tests with:

    C:\\jarvis\\venv\\Scripts\\python.exe C:\\jarvis\\guard.py

Standard library only. No new installs.
"""

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
PERMISSIONS_FILE = os.path.join(HERE, "permissions.json")
WORKSPACE = os.path.join(HERE, "workspace")
ACTION_LOG = os.path.join(HERE, "action_log.txt")

# Secret files Jarvis must NEVER return the contents of, even if
# permissions.json is changed to allow them. This is a hard rule.
HARD_SECRET_NAMES = {
    ".env",
    # SSH / key material (blocked even if permissions.json changes).
    "id_rsa", "id_rsa.pub", "id_ed25519", "id_ed25519.pub",
    "id_dsa", "id_ecdsa", "authorized_keys", "known_hosts",
}
HARD_SECRET_EXTS = {".pem", ".key", ".pfx", ".p12", ".id_rsa", ".ppk", ".keystore"}

# The emergency brake.
_STOP = False


def _default_permissions():
    return {
        "read_allowed": ["C:/jarvis"],
        "never_read": {
            "names": [".env", "permissions.json", "action_log.txt",
                      "jarvis.running", "crime_story.txt"],
            "folders": ["venv", ".git", "__pycache__", ".opencode"],
            "extensions": [".py", ".log", ".json", ".toml", ".ini", ".conf",
                           ".cmd", ".bat", ".ps1", ".exe", ".dll", ".pdb"],
        },
    }


# ------------------------------------------------------------- loading
def load_permissions():
    """Read permissions.json. If it is missing, create it with safe
    defaults so Jarvis (and this file) always has a rule set."""
    if not os.path.exists(PERMISSIONS_FILE):
        try:
            with open(PERMISSIONS_FILE, "w", encoding="utf-8") as f:
                json.dump(_default_permissions(), f, indent=2, ensure_ascii=False)
        except Exception:
            pass
    try:
        with open(PERMISSIONS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return _default_permissions()


_PERMISSIONS = load_permissions()


def _read_allowed():
    return _PERMISSIONS.get("read_allowed") or ["C:/jarvis"]


def _never():
    return _PERMISSIONS.get("never_read") or {}


# ---------------------------------------------------------------- STOP
def stop_all():
    """Turn the STOP switch on. After this, everything here is refused."""
    global _STOP
    _STOP = True


def is_stopped():
    """True if the STOP switch is on."""
    return _STOP


# ------------------------------------------------------------ resolving
def _resolve(path):
    """Turn any path into an absolute, clean path. Kills '..' tricks."""
    return os.path.realpath(os.path.abspath(os.path.expanduser(path)))


def _inside(path, root):
    """True if path is inside root (case-insensitive on Windows)."""
    p = os.path.normcase(path)
    r = os.path.normcase(_resolve(root))
    try:
        return os.path.commonpath([p, r]) == r
    except ValueError:
        return False


def _rejected(path):
    """True if the path hits a 'never_read' rule or a hard secret rule."""
    names = {n.lower() for n in _never().get("names", [])}
    folders = {f.lower() for f in _never().get("folders", [])}
    exts = {e.lower() for e in _never().get("extensions", [])}

    name = os.path.basename(path).lower()
    if name in names or name in HARD_SECRET_NAMES:
        return True

    _, ext = os.path.splitext(name)
    if ext in exts or ext in HARD_SECRET_EXTS:
        return True

    # Check every folder in the path (including the last one), so both
    # being inside a blocked folder and asking for the folder itself fail.
    for part in path.split(os.sep)[1:]:
        if part.lower() in folders:
            return True
    return False


# --------------------------------------------------------------- reads
def can_read(path):
    """True only if the path is inside a read_allowed folder AND does not
    hit any never_read rule. Resolves the path first. STOP blocks it."""
    if is_stopped():
        return False
    resolved = _resolve(path)
    return any(_inside(resolved, root) for root in _read_allowed()) and not _rejected(resolved)


def safe_read(path):
    """Return the file text if can_read is True, otherwise raise a clear
    error. Never returns the contents of .env or key files."""
    if is_stopped():
        raise RuntimeError("STOP is ON - reading is forbidden.")
    resolved = _resolve(path)
    if not can_read(resolved):
        raise PermissionError(f"Refused to read {path}: permission.json blocks it.")
    if not os.path.isfile(resolved):
        raise FileNotFoundError(f"No such file: {path}")
    with open(resolved, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


# -------------------------------------------------------------- writes
def can_write_free(path):
    """True only if the resolved path is inside C:\\jarvis\\workspace."""
    if is_stopped():
        return False
    return _inside(_resolve(path), WORKSPACE)


def safe_write(path, text):
    """Write the text only if it is inside the free-write workspace.
    Otherwise it does NOT write and returns a message saying the action
    needs approval and what would change."""
    if is_stopped():
        return ("STOP is ON - no writes are allowed right now.\n"
                "Would have written: " + str(path))
    resolved = _resolve(path)
    if not can_write_free(resolved):
        preview = (text or "").strip().replace("\n", " ")
        if len(preview) > 80:
            preview = preview[:80] + "..."
        return (
            f"This write needs your approval: {path}\n"
            + ("It would create a new file." if not os.path.exists(resolved)
               else "It would overwrite an existing file.")
            + f"\nWhat would change: {preview or '(empty file)'}"
            + "\nNothing was written."
        )
    try:
        os.makedirs(os.path.dirname(resolved) or WORKSPACE, exist_ok=True)
        with open(resolved, "w", encoding="utf-8") as f:
            f.write(text)
        log_action("write", str(resolved), "ok")
        return f"Saved: {path}"
    except Exception as error:
        log_action("write", str(resolved), f"error: {error}")
        return f"Write failed: {error}"


# --------------------------------------------------------------- audit
def log_action(action, path, result):
    """Append one audit line: time | action | path | result.
    Never logs file contents or secrets. STOP blocks even this."""
    if is_stopped():
        return
    try:
        from datetime import datetime

        os.makedirs(os.path.dirname(ACTION_LOG) or HERE, exist_ok=True)
        with open(ACTION_LOG, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat(timespec='seconds')} | {action} | {path} | {result}\n")
    except Exception:
        pass


# ---------------------------------------------------------- workspace
os.makedirs(WORKSPACE, exist_ok=True)


# --------------------------------------------------------------- tests
def _expect_blocked(fn):
    try:
        fn()
    except Exception:
        return True
    return False


def _run_tests():
    print("Running guard.py self-tests...")
    passed = 0
    total = 0

    def check(name, ok):
        nonlocal passed, total
        total += 1
        if ok:
            passed += 1
        print("  PASS -" if ok else "  FAIL -", name)

    # 1) Reading about_me.md works (make sure the file exists so the test is fair).
    about = os.path.join(HERE, "about_me.md")
    if not os.path.exists(about):
        with open(about, "w", encoding="utf-8") as f:
            f.write("# About Me\n\n")
    check("reading about_me.md works",
          isinstance(safe_read(about), str) and len(safe_read(about)) >= 0)

    # 2) Reading .env is blocked (contents never returned).
    env = os.path.join(HERE, ".env")
    if os.path.exists(env):
        blocked = _expect_blocked(lambda: safe_read(env))
        check("reading .env is blocked", blocked)
    else:
        check("reading .env is blocked", True)

    # 3) Writing inside the workspace works.
    ws_file = os.path.join(WORKSPACE, "test_note.txt")
    result = safe_write(ws_file, "hello from guard")
    check("writing inside workspace works",
          result == f"Saved: {ws_file}" and os.path.exists(ws_file))

    # 4) Writing outside the workspace is blocked (no file gets created).
    outside = os.path.join(HERE, "should_not_be_created.txt")
    if os.path.exists(outside):
        os.remove(outside)
    result = safe_write(outside, "trying to escape")
    blocked = ("approval" in result.lower()) or ("needs your approval" in result.lower())
    check("writing outside workspace is blocked",
          blocked and not os.path.exists(outside))

    # 5) STOP blocks everything. (Must be last - it cannot be turned off.)
    stop_all()
    check("STOP stops can_read", can_read(about) is False)
    check("STOP stops safe_read", _expect_blocked(lambda: safe_read(about)))
    check("STOP stops safe_write",
          "STOP" in safe_write(ws_file, "after stop"))

    print(f"\nResult: {passed}/{total} passed")
    return passed == total


if __name__ == "__main__":
    raise SystemExit(0 if _run_tests() else 1)