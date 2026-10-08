"""Lightweight long-term memory for Jarvis.

Stores durable facts about the user (name, preferences, things they asked
Jarvis to remember) plus a short rolling transcript so Jarvis can pick up
mid-conversation across restarts. Data lives in C:\\jarvis\\memory.json,
outside the web root so it is never served to the browser.
"""

import json
import os
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "memory.json")

# How many past exchanges feed back into the context window.
MAX_HISTORY = 6
MAX_FACTS = 60


def _blank():
    return {"facts": [], "history": []}


def load():
    try:
        with open(PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("facts", [])
        data.setdefault("history", [])
        return data
    except Exception:
        return _blank()


def save(data):
    try:
        with open(PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as error:
        print(f"(Memory save error: {error})")


def add_fact(text):
    """Remember one durable, one-line fact about the user (deduped)."""
    data = load()
    text = " ".join(text.split())
    if not text:
        return None
    existing = [f.lower() for f in data["facts"]]
    if text.lower() in existing:
        return text
    data["facts"].append(text)
    data["facts"] = data["facts"][-MAX_FACTS:]
    save(data)
    return text


def add_exchange(user_text, reply_text):
    """Append one user->assistant exchange to the rolling history."""
    data = load()
    data["history"].append(
        {
            "t": int(time.time()),
            "u": user_text,
            "a": reply_text,
        }
    )
    data["history"] = data["history"][-MAX_HISTORY:]
    save(data)


def context():
    """Build the memory block injected into Jarvis's system prompt."""
    data = load()
    parts = []
    if data["facts"]:
        lines = "\n".join("    - " + f for f in data["facts"])
        parts.append("Things you remember about the user:\n" + lines)
    if data["history"]:
        turns = "\n".join(
            "    User: {u}\n    Jarvis: {a}".format(u=h["u"], a=h["a"])
            for h in data["history"]
        )
        parts.append("Very recent conversation (use it for continuity):\n" + turns)
    if parts:
        return "\n".join(parts)
    return "You have not learned anything about the user yet."


def stats():
    data = load()
    return len(data["facts"]), len(data["history"])