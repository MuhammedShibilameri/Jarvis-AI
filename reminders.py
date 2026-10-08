"""Stage 3: reminders and notifications for Jarvis.

Everything is stored in C:\\jarvis\\reminders.json so it survives restarts.

Each reminder looks like:
    {"id": 1, "task": "call mom", "due": "2026-10-08T18:00:00"}

Two files use this module:
  - jarvis_ui.py (the Orb window with the voice)
  - jarvis.py    (the simple terminal version)
"""

import json
import os
import re
import threading
from datetime import datetime, timedelta

FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reminders.json")
_lock = threading.Lock()


def _load():
    """Read the reminder file. Never crashes. Returns a list of dicts."""
    try:
        with open(FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        items = data.get("items", [])
    except Exception:
        items = []
    return [r for r in items if isinstance(r, dict) and r.get("task")]


def _save(items):
    with open(FILE, "w", encoding="utf-8") as f:
        json.dump({"items": items}, f, ensure_ascii=False, indent=2)


def parse_time(phrase):
    """Turn '6 pm', '18:30', 'noon', or 'in 10 minutes' into a datetime.

    Returns None if the time could not be understood.
    """
    p = (phrase or "").lower().strip()
    if not p:
        return None

    now = datetime.now()

    m = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)?", p)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2) or 0)
        ampm = m.group(3)
        if minute > 59:
            return None
        if ampm:
            ampm = ampm.replace(".", "").lower()
            if hour > 12:
                return None
            if ampm == "am" and hour == 12:
                hour = 0
            if ampm == "pm" and hour != 12:
                hour += 12
        elif hour > 23:
            return None
        due = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if due <= now:
            due += timedelta(days=1)
        return due

    if re.search(r"\bnoon\b", p):
        due = now.replace(hour=12, minute=0, second=0, microsecond=0)
        if due <= now:
            due += timedelta(days=1)
        return due

    if re.search(r"\bmidnight\b", p):
        due = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if due <= now:
            due += timedelta(days=1)
        return due

    m = re.search(r"in\s+(\d+)\s*(h|hr|hrs|hour|hours|m|min|mins|minute|minutes)\b", p)
    if m:
        count = int(m.group(1))
        unit = m.group(2).lower()
        seconds = count * 3600 if unit.startswith("h") else count * 60
        return now + timedelta(seconds=seconds)

    return None


def fmt_due(due_iso):
    """'2026-10-08T18:00:00' -> '6:00 pm'"""
    try:
        dt = datetime.fromisoformat(due_iso)
    except Exception:
        return due_iso
    hour = dt.hour
    minute = dt.minute
    ampm = "am" if hour < 12 else "pm"
    hour12 = hour % 12 or 12
    return f"{hour12}:{minute:02d} {ampm}"


def add(task, due):
    """Save a new reminder and return it."""
    with _lock:
        items = _load()
        rid = max([r["id"] for r in items], default=0) + 1
        reminder = {"id": rid, "task": task, "due": due.isoformat(timespec="seconds")}
        items.append(reminder)
        items.sort(key=lambda r: r["due"])
        _save(items)
    return reminder


def list_reminders_text():
    """A human-friendly summary of all saved reminders."""
    with _lock:
        items = _load()
    if not items:
        return "You have no reminders."
    head = f"You have {len(items)} reminder{'s' if len(items) > 1 else ''}."
    lines = [head]
    for r in items:
        lines.append(f"{r['id']}. {r['task']} at {fmt_due(r['due'])}")
    return "\n".join(lines)


def remove_index(number):
    """Remove reminder number 'number'. Returns it, or None if missing."""
    with _lock:
        items = _load()
        for r in items:
            if r["id"] == number:
                items.remove(r)
                _save(items)
                return r
    return None


def clear():
    """Delete every reminder. Returns the number of removed items."""
    with _lock:
        count = len(_load())
        _save([])
    return count


def due_reminders():
    """Return and remove the reminders whose time has come."""
    now = datetime.now()
    with _lock:
        items = _load()
        due = [r for r in items if r["due"] <= now.isoformat(timespec="seconds")]
        left = [r for r in items if r["due"] > now.isoformat(timespec="seconds")]
        if due:
            _save(left)
    return due


def _is_list_command(t):
    if "reminder" not in t:
        return False
    if t in ("reminder", "reminders", "list reminders", "show reminders",
             "my reminders", "reminder list", "list my reminders", "all reminders"):
        return True
    return re.search(r"\b(list|show|view|all|what|which|have|my)\b", t) is not None


_CANCEL_ALL_PHRASES = (
    "cancel all reminders", "clear all reminders", "remove all reminders",
    "delete all reminders", "cancel my reminders", "clear my reminders",
    "remove my reminders", "delete my reminders", "cancel reminders",
    "clear reminders", "remove reminders", "delete reminders",
)


def handle_reminder(text):
    """Look for a reminder command in the text.

    Returns (handled, reply). If handled is False, the caller should
    send the text to the AI model normally.
    """
    t = (text or "").lower().strip().strip("!.?")

    if "remind" not in t and "reminder" not in t:
        return False, ""

    # Add: "remind me to <task> at <time>" or "... in <time>".
    m = re.search(r"remind me to (.+?)\s+(?:at|in)\s+(.+)$", t)
    if m:
        task = m.group(1).strip(" .!?,")
        due = parse_time(m.group(2))
        if due:
            reminder = add(task, due)
            return True, f"Got it. I will remind you to {task} at {fmt_due(reminder['due'])}."
        return True, "I did not catch the time. Try 'remind me to water the plants at 6 pm' or 'in 10 minutes'."

    # "remind me to <task>" with no time at all.
    m = re.search(r"remind me to (.+)$", t)
    if m:
        nested = m.group(1).strip(" .!?,")
        if nested in _CANCEL_ALL_PHRASES or nested == "cancel reminders":
            count = clear()
            return True, "I removed all your reminders." if count else "You have no reminders to remove."
        if _is_list_command(nested):
            return True, list_reminders_text()
        return True, "When should I remind you? Say 'in 10 minutes' or 'at 6 pm'."

    # Remove one: "cancel reminder 2" or "remove reminder number 2".
    m = re.search(r"(?:cancel|remove|delete)\s+(?:reminders?\s+)?(?:number\s*)?(\d+)", t)
    if m:
        removed = remove_index(int(m.group(1)))
        if removed:
            return True, f"Removed reminder {removed['id']}: {removed['task']}."
        return True, f"I could not find reminder number {m.group(1)}."

    # Remove all.
    if any(phrase in t for phrase in _CANCEL_ALL_PHRASES):
        count = clear()
        return True, "I removed all your reminders." if count else "You have no reminders to remove."

    # Show the list.
    if _is_list_command(t):
        return True, list_reminders_text()

    return False, ""