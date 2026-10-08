"""Doing-skills for Jarvis: real-time information without an API key.

  - "search the web for X" / "google X"      -> DuckDuckGo + Wikipedia
  - "weather" / "weather in <place>"          -> wttr.in
  - "news" / "headlines"                        -> Google News RSS
  - "calculate <expr>" / "what is 12 times 8" -> safe calculator
  - "what time is it" / "what is the date"    -> clock & calendar
  - "search on youtube for X"                 -> opens YouTube results

All replies are kept short (they are spoken out loud). Offline or a
failed request returns a clear, friendly message instead of crashing.
"""

import json
import math
import re
import time
import urllib.parse
import urllib.request
import webbrowser
import xml.etree.ElementTree as ET
from datetime import datetime

TIMEOUT = 8
USER_AGENT = "Mozilla/5.0 (JARVIS desktop assistant; Windows NT 10.0; Win64; x64)"
SHORT_MAX = 380  # keep spoken answers snappy


def _fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read()


def _trim(text, limit=SHORT_MAX):
    text = re.sub(r"\s+", " ", text or "")
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


# ---------------------------------------------------------------- search
def _web_search(query):
    q = urllib.parse.quote(query)
    data = json.loads(
        _fetch(
            "https://api.duckduckgo.com/"
            f"?q={q}&format=json&no_html=1&skip_disambig=1"
        ).decode("utf-8", "replace")
    )
    answer = (data.get("abstract_text") or "").strip()
    if not answer and data.get("url"):
        answer = data["url"]  # Wikipedia-style direct hit without abstract
    if not answer:
        for topic in data.get("RelatedTopics") or []:
            if isinstance(topic, dict) and topic.get("Text"):
                answer = topic["Text"].strip()
                break
    if not answer or len(answer) < 20 or answer.lower().endswith(" category") \
        or answer.lower().endswith("(category)"):
        try:
            wiki = json.loads(
                _fetch(
                    "https://en.wikipedia.org/w/api.php?action=query"
                    f"&list=search&srsearch={q}&format=json&srlimit=2"
                ).decode("utf-8", "replace")
            )
            hits = wiki.get("query", {}).get("search") or []
            if hits:
                answer = "From Wikipedia: " + re.sub(
                    r"<[^>]+>", "", hits[0].get("snippet", "")
                ).strip()
        except Exception:
            answer = ""
    if not answer:
        raise ValueError("no result")
    return _trim(answer)


# ---------------------------------------------------------------- weather
def _weather(place=""):
    enc = urllib.parse.quote(place or "")
    data = json.loads(
        _fetch(f"https://wttr.in/{enc}?format=j1").decode("utf-8", "replace")
    )
    area = (data.get("nearest_area") or [{}])[0]
    name = (area.get("areaName") or [{"value": "your area"}])[0]["value"]
    region = (area.get("region") or [{"value": ""}])[0]["value"]
    cc = (data.get("current_condition") or [{}])[0]
    desc = (cc.get("weatherDesc") or [{"value": "clear"}])[0]["value"]
    temp = cc.get("temp_C", "?")
    feels = cc.get("FeelsLikeC", temp)
    hum = cc.get("humidity", "?")
    wind = cc.get("windspeedKmph", "?")
    when = "now" if not place else f"now in {name} ({region})"
    return (
        f"It is {desc.lower()} {when} at {temp} degrees, "
        f"feels like {feels}. Humidity {hum} percent, "
        f"wind {wind} kilometres per hour."
    )


# ---------------------------------------------------------------- news
def _news():
    raw = _fetch("https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en")
    root = ET.fromstring(raw)
    titles = [t.text.strip() for t in root.iter("title") if t.text and t.text.strip()][1:6]
    if not titles:
        raise ValueError("no headlines")
    return "Top headlines: " + " ... ".join(f"{i + 1}. {_trim(t, 90)}" for i, t in enumerate(titles))


# ---------------------------------------------------------------- calc
_WORD_OPS = [
    ("divided by", "/"),
    ("times", "*"),
    ("multiplied by", "*"),
    ("plus", "+"),
    ("minus", "-"),
    ("over", "/"),
    ("to the power of", "**"),
    ("squared", "**2"),
    ("percent of", "% of"),
]
_MATH = {"sqrt": math.sqrt, "sin": math.sin, "cos": math.cos, "tan": math.tan,
         "log": math.log, "pi": math.pi, "e": math.e, "pow": pow}


def _calc(expr):
    e = expr.strip()
    for word, op in _WORD_OPS:
        e = re.sub(re.escape(word), op, e)
    if "%" in e:  # "50% of 200" or a plain percentage
        e = re.sub(r"(\d+)\s*%\s*of\s+(\d+)", r"((\1/100.0)*\2)", e)
        e = e.replace("%", "/100")
    if not re.fullmatch(r"[\d\s()+\-*/.%a-z]+", e):
        raise ValueError("unsafe expression")
    result = eval(e, {"__builtins__": {}}, _MATH)  # noqa: S307 - chars whitelisted above
    if isinstance(result, float):
        result = round(result, 4)
    return f"The answer is {result}."


# ---------------------------------------------------------------- intents
def handle(user_text):
    """Match a doing-skill in the text. Returns (handled, spoken reply).

    If handled is False, the caller should send the text to the AI.
    """
    t = (user_text or "").lower().strip()

    # --- time
    if re.search(r"\b(what|tell)\b.*\btime\b", t) or t in ("time", "time now"):
        now = datetime.now()
        return True, f"It is {now:%I:%M %p} on {now:%A}, {now:%B} {now:%d}, {now:%Y}."

    # --- date / day
    if re.search(r"\bdate\b", t) or re.search(r"\btoday", t):
        now = datetime.now()
        return True, f"Today is {now:%A}, {now:%B} {now:%d}, {now:%Y}."

    # --- weather
    if re.search(r"\bweather\b|\btemperature\b|\bhow (cold|hot)\b", t):
        city = ""
        m = re.search(r"\bin\s+([a-z][a-z ;,.'-]*)$", t)
        if m:
            city = m.group(1).strip(" .;,")
        try:
            return True, _weather(city)
        except Exception:
            return True, "I could not reach the weather service. Check the internet."

    # --- news
    if re.search(r"\b(news|headlines)\b", t):
        try:
            return True, _news()
        except Exception:
            return True, "I could not reach the news service. Check the internet."

    # --- web search
    m = re.search(r"\b(?:search(?:\s+the\s+web)?(?:\s+for)?|google)\s+(.+)$", t)
    if m:
        query = m.group(1).strip(" .!?").strip()
        if query:
            try:
                return True, "According to the web, " + _web_search(query)
            except Exception:
                return True, f"I could not find information about '{query}'. Check the internet."

    # --- youtube search (opens the browser)
    m = re.search(r"\b(?:search|play|find)\s+(?:on\s+)?youtube(?:\s+for)?\s+(.+)$", t)
    if m:
        query = m.group(1).strip(" .!?")
        if query:
            url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote(query)
            webbrowser.open(url)
            return True, f"Opening YouTube results for {query}."

    # --- calculator
    m = re.search(r"\bcalculate\s+(.+)$", t)
    if m:
        try:
            return True, _calc(m.group(1))
        except Exception:
            return True, "I could not work that out. Try something like: calculate 12 times 8."
    if t.startswith("what is "):
        rest = t[8:].strip().rstrip("? .")
        if re.search(r"\d", rest) and re.search(
            r"[+\-*/%×÷]|\b(plus|minus|times|divided|over|percent|sqrt|half|quarter|squared)\b",
            rest,
        ):
            try:
                return True, _calc(rest)
            except Exception:
                return True, "I could not work that out. Try: calculate 12 times 8."

    return False, ""


if __name__ == "__main__":
    import sys

    for sample in sys.argv[1:] or [
        "what time is it", "what is the date", "weather in london",
        "news", "search the web for python", "calculate 12 times 8",
        "what is 4 plus 5", "search on youtube for lofi",
    ]:
        print(f"{sample!r:45} -> {handle(sample)[1]}")