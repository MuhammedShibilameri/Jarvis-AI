import difflib
import functools
import http.server
import io
import json
import os
import queue
import re
import shutil
import socketserver
import subprocess
import sys
import threading
import time
import wave
import winsound

import numpy as np
import ollama
import pyttsx3
import sounddevice as sd
import vosk
import webview
from dotenv import load_dotenv

import reminders
import memory
import skills
import presence
import guard

vosk.SetLogLevel(-1)

# Windows console/file output may otherwise crash on non-ASCII characters
# (e.g. curly quotes from speech transcription), silently killing features.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))

# Cloud AI key lives in C:\jarvis\.env (locked to this user), never in code.
load_dotenv(os.path.join(HERE, ".env"))

MODEL = "llama3.2:3b"
VOICE_NAME = "Zira"
MODEL_OPTIONS = {"num_ctx": 4096}
# Fast, Siri-like answers via Groq's cloud when the key + internet exist.
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "").strip()
GROQ_MODEL = "openai/gpt-oss-120b"
# Cloud speech recognition on the same key; local Whisper is the offline
# fallback when Groq is unreachable.
GROQ_STT_MODEL = "whisper-large-v3-turbo"
if GROQ_API_KEY:
    print("(Groq cloud AI ready - Ollama stays as the offline fallback)")

facts_n, turns_n = memory.stats()
print(f"(memory: {facts_n} facts, {turns_n} recent turns)")
# Ultron-style 3D orb UI. Switch the fallback by changing this to
# "jarvis_ui.html" (the light blue CSS orb).
UI_HTML = "jarvis_ui.html"
VOSK_MODEL_PATH = os.path.join(HERE, "vosk-model-small-en-us-0.15")
# Siri-level speech recognition. Uses the local faster-whisper engine
# when installed (downloads the model on first run). Set to "small.en"
# for noticeably better accuracy at the cost of more RAM; "base.en" is
# the recommended balance. Falls back to vosk if whisper is missing.
WHISPER_MODEL = "small.en"
SAMPLE_RATE = 16000
WAKE_WORD = "hey jarvis"
# Lower + 2-step confirm: real hits (score ~0.5-0.8 on this mic) are
# caught reliably while random noise needs two hits in a row.
WAKE_THRESHOLD = 0.4
ARMED_SECONDS = 10
# Voice-activity detection for one-shot command capture.
VAD_THRESHOLD = 300        # RMS of int16 audio counts as speech
END_SILENCE_SECONDS = 0.9  # stop recording after this much quiet
MAX_CLIP_SECONDS = 9.0     # hard cap so one utterance can't hang us

# Tune lag: the recorder waits VOICE_END_SILENCE seconds of quiet after you
# stop speaking before sending the clip to Groq, then Groq needs ~0.3-0.7 s.
# Lower it (e.g. 0.5) for snappier replies; raise it if she cuts you off.
VOICE_END_SILENCE = 0.7

# Conversation mode: one "hey jarvis" keeps her listening (no wake word)
# until you are silent for CONVERSATION_TIMEOUT seconds, or an end phrase.
CONVERSATION_TIMEOUT = 10.0
END_CONVERSATION_PHRASES = {"thats all", "stop listening"}

# Phantom-speech guardrails: stop Jarvis "hearing" words invented from
# silence and noise. Every clip needs at least VOICED_REQUIRED_SECONDS of
# real speech, and conversation mode calibrates the speech bar to ~2.5x
# the measured background noise (never below VAD_THRESHOLD). The noise
# measurement is cached so the 1 s sample only happens from time to time.
VOICED_REQUIRED_SECONDS = 0.4
NOISE_SAMPLE_SECONDS = 1.0
NOISE_THRESHOLD_FACTOR = 2.5
NOISE_LEVEL_CAP = 3.0 * 300     # speech bar never above this (3x VAD)
NOISE_CACHE_SECONDS = 600.0     # recalibrate at most every 10 minutes

# Groq verbose_json confidence bar: drop a clip when the audio really
# looks like silence. Reject if (no_speech_prob > NO_SPEECH_PROB_MAX and
# avg_logprob < AVG_LOGPROB_MIN) or avg_logprob < AVG_LOGPROB_HARD_MIN.
NO_SPEECH_PROB_MAX = 0.6
AVG_LOGPROB_MIN = -1.0
AVG_LOGPROB_HARD_MIN = -1.5

# Words the STT engine invents on quiet audio: ignored silently, but
# printed to the terminal as "(ignored: ...)" so you can still see them.
PHANTOM_PHRASES = {
    "thank you", "thanks for watching", "you", "bye", "okay",
    "thanks", "subtitles by",
}

# Also used to remove the wake phrase from heard commands.
WAKE_PATTERN = re.compile(r"\b(hey\s+)?(jarvis|javis|jervis|travis|charvis)\b", re.IGNORECASE)

# Add more apps with one line each.
APPS = {
    "chrome": [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        "chrome",
    ],
    "edge": [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        "msedge",
    ],
    "notepad": [
        "notepad",
    ],
    "calculator": [
        "calc",
    ],
    "vs code": [
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe"),
        r"C:\Program Files\Microsoft VS Code\Code.exe",
        "code",
    ],
    "explorer": [
        "explorer",
    ],
    "android studio": [
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Android Studio\bin\studio64.exe"),
        r"C:\Program Files\Android\Android Studio\bin\studio64.exe",
        "studio64",
    ],
}

messages = [
    {
        "role": "system",
        "content": (
            "You are Jarvis, a friendly and smart female personal assistant. "
            "Keep your answers short and clear."
        ),
    }
]


def build_system():
    """Fresh system prompt: today's date/time plus everything Jarvis
    remembers, so a long-term memory feeds every turn."""
    now = time.strftime("%A, %B %d, %Y - %I:%M %p")
    return (
        "You are Jarvis, a friendly and smart personal assistant. "
        f"Keep your answers short and clear. The current date and time is {now}.\n\n"
        + memory.context()
        + "\n\nUse the memory above when it is relevant, but never invent "
        "memories or interactions that are not listed there.\n\n"
        "You also have guarded local file tools: if I ask you to read or open "
        "a file, tell me you are reading it for me - your Python handler does "
        "it inside the safety rules. I can save notes into your workspace and "
        "list it. You never see or repeat .env or private key files."
    )

window = None
mic_on = True
mic_event = threading.Event()
mic_event.set()
speaking = threading.Event()
speak_lock = threading.Lock()
audio_queue = queue.Queue(maxsize=40)
wake_model = None

# Speech runs on one worker thread so that voice ('stop') or the hotkey
# can cut Jarvis off mid-answer (see speak() and speak_interrupt()).
tts_engine = None
tts_queue = queue.Queue()
utterance_done = threading.Event()
barged_in = False
interrupt_recognizer = None

# Cached ambient-noise calibration for the phantom-speech guardrail.
noise_cached_threshold = VAD_THRESHOLD
noise_cached_until = 0.0

# When the wake word is heard, Jarvis records the command right away and
# sends only that one clip to the fast Groq engine (no continuous audio).
armed_until = 0.0
last_wake_time = 0.0
# Two quick detections inside half a second cut random false fires.
wake_confirm_since = 0.0

# Conversation mode keeps listening after one wake word until quiet for
# CONVERSATION_TIMEOUT seconds.
conversation_active = False
conversation_until = 0.0

# True while the window is hidden in the system tray (close-to-tray).
hidden_to_tray = False


def js(code):
    """Send a command to the HTML page. Never crashes the app."""
    try:
        window.evaluate_js(code)
    except Exception as error:
        print(f"(UI error: {error})")


def orb_msg(text):
    """Show a floating text readout under the 3D orb (avatar HUD)."""
    js(
        "if(window.__orb&&window.__orb.setMessage){"
        f"window.__orb.setMessage({json.dumps(text or '')})" + "}"
    )


def ui_idle():
    """Return the orb to its resting state."""
    js(f"setState('{'listening' if mic_on else 'idle'}')")


def show_window():
    """Bring the Jarvis window back when the wake word is heard."""
    global hidden_to_tray
    hidden_to_tray = False
    try:
        window.restore()
        window.show()
    except Exception:
        pass
    js("window.focus()")


def trigger_listen():
    """Push-to-talk: one fast voice capture immediately (tray/hotkey).
    Same Groq engine as the mic button; only the one command clip goes
    to the cloud, never continuous audio. If she is already talking,
    the press cuts her off instead."""
    if speaking.is_set():
        speak_interrupt()
        return
    show_window()
    js("setState('listening')")
    threading.Thread(target=run_click_stt, daemon=True).start()


def do_exit():
    """Real quit (tray Exit / 'exit' command). Releases the lock and
    closes the window for good."""
    global hidden_to_tray
    presence.exit_requested = True
    hidden_to_tray = False
    try:
        window.destroy()
    except Exception:
        presence.release_single_instance()
        try:
            presence.stop_tray()
        except Exception:
            pass
        os._exit(0)


def armed():
    return time.time() < armed_until


def disarm():
    global armed_until
    armed_until = 0.0


def strip_wake(text):
    """Remove 'hey jarvis' (and then everything before it) from a command."""
    match = WAKE_PATTERN.search(text)
    if match:
        return text[match.end():].strip(" ,.!?")
    return text


def normalize_voice(text):
    """Clean up speech-to-text output before command matching: lowercase,
    trim, drop a leading wake phrase, and remove punctuation (. , ! ? ;
    : and quotes) that Whisper likes to add. Runs ONLY on recognized
    voice text - typed text (and typed file paths) are never touched."""
    t = (text or "").lower().strip()
    t = strip_wake(t)
    return re.sub(r"[.,!?;:\"'`]+", "", t).strip()


def tts_worker():
    """Speaks queued text on its own thread.

    Owning the SAPI engine here (instead of creating one per call in the
    caller's thread) is what allows any other thread to cut speech off:
    speak_interrupt() calls engine.stop() directly, which stops SAPI
    within ~0.1 s and lets runAndWait() return.
    """
    global tts_engine, barged_in

    def ensure_engine():
        global tts_engine
        if tts_engine is not None:
            return
        try:
            engine = pyttsx3.init()
            for voice in engine.getProperty("voices"):
                if VOICE_NAME.lower() in voice.name.lower():
                    engine.setProperty("voice", voice.id)
                    break
            engine.setProperty("rate", 175)
            tts_engine = engine
        except Exception as error:
            print(f"(Voice init error: {error})")

    ensure_engine()

    while True:
        text = tts_queue.get()
        barged_in = False
        if tts_engine is None:
            ensure_engine()
        if tts_engine is not None and text:
            try:
                tts_engine.say(text)
                tts_engine.runAndWait()
            except Exception as error:
                print(f"(Voice error: {error})")
        utterance_done.set()


def speak_interrupt():
    """Cut Jarvis off mid-answer (voice 'stop' or hotkey press).

    Stops the SAPI engine immediately; the worker's runAndWait() then
    returns and the rest of the reply is skipped.
    """
    try:
        if tts_engine is not None:
            tts_engine.stop()
    except Exception as error:
        print(f"(Interrupt error: {error})")


def _check_barge_in(frame_bytes):
    """While she is talking, listen only for interrupt words on the same
    always-open mic (no new audio stream, nothing ever goes to the cloud)."""
    global barged_in, interrupt_recognizer, click_vosk_model
    if barged_in:
        return
    try:
        samples = np.frombuffer(frame_bytes, dtype=np.int16)
        if np.abs(samples).mean() < VAD_THRESHOLD:
            return
        if interrupt_recognizer is None:
            if click_vosk_model is None:
                click_vosk_model = vosk.Model(VOSK_MODEL_PATH)
            interrupt_recognizer = vosk.KaldiRecognizer(
                click_vosk_model,
                SAMPLE_RATE,
                json.dumps(
                    ["stop", "stop talking", "shut up", "be quiet", "quiet", "enough"]
                ),
            )
        if interrupt_recognizer.AcceptWaveform(frame_bytes):
            heard = (json.loads(interrupt_recognizer.Result()).get("text") or "").strip()
            if heard:
                barged_in = True
                print(f"(barge-in: {heard})")
                speak_interrupt()
    except Exception as error:
        print(f"(Barge-in error: {error})")


def speak(text):
    """Speak the text out loud using the Zira (female) voice.

    Runs on the TTS worker thread so speak_interrupt() (voice 'stop' or
    the hotkey) can cut it off. While talking, the orb vibrates so the
    voice appears to come from it ('speaking' class -> orb.js jitters).
    """
    with speak_lock:
        speaking.set()
        js("if(window.setSpeakState){setSpeakState(true)}")
        try:
            if not text:
                return
            utterance_done.clear()
            tts_queue.put(text)
            if not utterance_done.wait(timeout=30):
                print("(TTS worker unresponsive - speaking inline)")
                try:
                    engine = pyttsx3.init()
                    for voice in engine.getProperty("voices"):
                        if VOICE_NAME.lower() in voice.name.lower():
                            engine.setProperty("voice", voice.id)
                            break
                    engine.setProperty("rate", 175)
                    engine.say(text)
                    engine.runAndWait()
                    engine.stop()
                except Exception as error:
                    print(f"(Voice error: {error})")
        finally:
            speaking.clear()
            js("if(window.setSpeakState){setSpeakState(false)}")


def find_app(candidates):
    """Return the full path of the first working app in the list, or None."""
    for candidate in candidates:
        try:
            expanded = os.path.expandvars(os.path.expanduser(candidate))
            if os.path.isabs(expanded) and os.path.isfile(expanded):
                return expanded
            found = shutil.which(expanded)
            if found:
                return found
        except Exception:
            continue
    return None


def open_app(name):
    """Try to open an app. Returns the message Jarvis should show/say."""
    path = find_app(APPS[name])
    if path is None:
        return f"Sorry, I could not open {name}."
    try:
        subprocess.Popen([path], cwd=os.path.dirname(path) or None)
    except Exception as error:
        return f"Sorry, I could not open {name}. ({error})"
    return f"Opening {name}"


def _resolve_file(name):
    """Turn a spoken file name into an absolute path (relative = C:/jarvis)."""
    name = (name or "").strip(" \"'.,!?")
    return os.path.realpath(name) if os.path.isabs(name) else os.path.realpath(os.path.join(HERE, name))


def handle_file_command(user_text):
    """Guarded file tools, run BEFORE the AI. Every read/write goes
    through guard.py (permissions.json + STOP switch + audit log).

    Returns (handled, message). Returns False, "" if not a file command.
    """
    t = (user_text or "").lower().strip()

    # --- read a file --------------------------------
    m = re.search(
        r"\b(?:read|open|show|print)(?:\s+me)?\s+(?:the\s+)?(?:file\s+)?(.+)$",
        t,
    )
    if m and ("file" in t or "." in m.group(1)):
        path = _resolve_file(m.group(1))
        try:
            text = guard.safe_read(path)
        except (PermissionError, FileNotFoundError, RuntimeError) as error:
            return True, str(error)
        if len(text) > 1400:
            text = text[:1400]
            text += ("\n... (file is longer - I read the first part.)")
        return True, text or "(empty file)"

    # --- save / write a note into the workspace -----
    m = re.search(
        r"\b(?:save|write|store)\s+a?\s*note\s+(?:called\s+)?(\S+)\s+(.+)$",
        t,
    )
    if m:
        name = m.group(1).strip(" .!?,'\"")
        content = m.group(2).strip()
        if "." not in os.path.basename(name):
            name += ".md"
        target = os.path.join(guard.WORKSPACE, name)
        result = guard.safe_write(target, content)
        return True, result

    # --- list the workspace -------------------------
    if re.search(r"\b(?:list|show|what)\b.*\bworkspace\b", t) or t in ("workspace", "my workspace"):
        try:
            if guard.is_stopped():
                return True, "STOP is ON - no access right now."
            if not guard.can_read(guard.WORKSPACE):
                return True, "I cannot look at the workspace under the current rules."
            names = sorted(os.listdir(guard.WORKSPACE))
        except OSError:
            names = []
        if not names:
            return True, "My workspace is empty."
        return True, "My workspace contains: " + ", ".join(names) + "."

    return False, ""


READABLE_EXTS = {
    ".md", ".markdown", ".txt", ".rst", ".dart", ".yaml", ".yml", ".csv",
    ".html", ".htm", ".py", ".json",
}
STUDY_MAX_FILES = 40
STUDY_MAX_CHARS = 30000
STUDY_MAX_DEPTH = 2

COMMON_FOLDERS = {
    "documents": os.path.join(r"C:\Users\shibil", "Documents"),
    "downloads": os.path.join(r"C:\Users\shibil", "Downloads"),
    "desktop": os.path.join(r"C:\Users\shibil", "Desktop"),
    "pictures": os.path.join(r"C:\Users\shibil", "Pictures"),
    "videos": os.path.join(r"C:\Users\shibil", "Videos"),
    "music": os.path.join(r"C:\Users\shibil", "Music"),
    "onedrive": os.path.join(r"C:\Users\shibil", "OneDrive"),
    "projects": os.path.join(r"C:\Users\shibil", "AndroidStudioProjects"),
}


def _short_reply(messages):
    """One short AI answer (non-streaming). Groq first, Ollama fallback."""
    if GROQ_API_KEY:
        try:
            from groq import Groq

            client = Groq(api_key=GROQ_API_KEY)
            resp = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=messages,
                temperature=0.4,
                max_tokens=600,
            )
            return (resp.choices[0].message.content or "").strip()
        except Exception as error:
            print(f"(Groq study unavailable, using Ollama: {error})")
    try:
        resp = ollama.chat(model=MODEL, messages=messages)
        return (resp["message"]["content"] or "").strip()
    except Exception as error:
        print(f"(Study AI unavailable: {error})")
        return None


def _collect_readable(folder):
    """Walk a folder through the guard and pull text from readable files.
    Returns (count, text). Bounded so a big folder never floods the reply."""
    pieces = []
    count = 0
    chars = 0

    def visit(directory, depth):
        nonlocal count, chars
        if count >= STUDY_MAX_FILES or chars >= STUDY_MAX_CHARS:
            return
        try:
            entries = sorted(os.scandir(directory), key=lambda e: e.name.lower())
        except OSError:
            return
        for entry in entries:
            if count >= STUDY_MAX_FILES or chars >= STUDY_MAX_CHARS:
                return
            if entry.name.startswith("."):
                continue
            try:
                if entry.is_dir():
                    if depth < STUDY_MAX_DEPTH:
                        visit(entry.path, depth + 1)
                    continue
                if os.path.splitext(entry.name)[1].lower() not in READABLE_EXTS:
                    continue
                if not guard.can_read(entry.path):
                    continue
                if entry.stat().st_size > 1024 * 1024:  # skip huge files
                    continue
                text = guard.safe_read(entry.path)
                if not text or not text.strip():
                    continue
                take = min(len(text), STUDY_MAX_CHARS - chars)
                pieces.append("== " + entry.path + " ==\n" + text[:take])
                chars += take + len(entry.path)
                count += 1
            except Exception:
                continue

    visit(folder, 0)
    return count, "\n\n".join(pieces)


def _resolve_study_target(name):
    """Turn a spoken folder name (or a path) into a real folder path,
    or None. Handles both 'documents' and 'C:/Users/shibil/Documents'."""
    name = (name or "").strip(" \"'.,!?")
    if not name:
        return None
    key = name.lower()
    if os.path.exists(name):
        return os.path.realpath(name)
    if key in COMMON_FOLDERS:
        return COMMON_FOLDERS[key]
    for short, full in COMMON_FOLDERS.items():
        if short in key:
            return full
    if re.fullmatch(r"[a-zA-Z]:\\.*", name):
        return os.path.realpath(name)
    return None


def handle_study_command(user_text):
    """'study my documents' / 'summarize the downloads folder' - Jarvis
    reads readable files through the guard and asks the AI to summarize.

    Returns (handled, message); (False, "") means 'not a study command'.
    """
    t = (user_text or "").lower().strip()
    m = re.search(
        r"\b(?:study|learn|scan|explore|summarize|analyse|analyze)\b"
        r"(?:\s+(?:the|my|this)\s+)?(?:folder\s+)?(.+)$",
        t,
    )
    if not m:
        m = re.search(r"\bwhat(?:'s| is)\s+in\s+(?:the\s+|my\s+)?folder\s+(.+)$", t)
    if not m:
        m = re.search(r"\bwhat(?:'s| is)\s+in\s+(?:my\s+)?(documents|downloads|desktop|onedrive|projects|pictures|videos|music)\b", t)

    if not m:
        return False, ""

    target = _resolve_study_target(m.group(1))
    if not target:
        return False, ""
    if not os.path.isdir(target):
        if guard.can_read(target) and os.path.isfile(target):
            try:
                return True, guard.safe_read(target)
            except Exception as error:
                return True, str(error)
        return True, f"{target} is not a folder I can study."

    if not guard.can_read(target):
        return True, f"The rules do not let me read {target}."

    count, collected = _collect_readable(target)
    if not count:
        return True, (
            "I looked through " + target + " but found no readable text files "
            "I am allowed to read (or it is empty)."
        )

    messages = [
        {"role": "system", "content": (
            "You are Jarvis, a friendly and smart personal assistant. "
            "The user asked you to study files from their computer. "
            "Give a short, friendly summary in under 120 words: what these "
            "files are about and the most useful or interesting points. "
            "Do not mention file paths unless asked. Plain short sentences."
        )},
        {"role": "user", "content": (
            "Files I read from " + target + " (" + str(count) + " readable files):\n\n"
            + collected
        )},
    ]

    summary = _short_reply(messages)
    guard.log_action("study", target, f"{count} files")
    if not summary:
        return True, "I gathered the files but could not reach the AI to summarize them right now."
    return True, summary


def handle_command(user_text):
    """Handle 'open ...', reminders, and the doing-skills (search,
    weather, news, clock, calculator, youtube).

    Returns (handled, message). If handled is False, Jarvis should
    send the text to the AI model instead.
    """
    lowered = user_text.lower().strip()

    # Stage 3: reminders ("remind me to ... at ...", "my reminders", ...).
    handled, note = reminders.handle_reminder(lowered)
    if handled:
        return True, note

    # Doing-skills: search / weather / news / time / date / calc / youtube.
    handled, note = skills.handle(lowered)
    if handled:
        return True, note

    # Guarded file tools: read files, write notes, list the workspace.
    handled, note = handle_file_command(lowered)
    if handled:
        return True, note

    # Study a folder: read readable files through the guard and summarize.
    handled, note = handle_study_command(lowered)
    if handled:
        return True, note

    if not lowered.startswith("open "):
        return False, ""

    wanted = lowered[5:].strip(" ?.!\t")

    if not wanted:
        return True, "What should I open?"

    for app_name in APPS:
        if app_name == wanted:
            return True, open_app(app_name)

    for app_name in sorted(APPS, key=len, reverse=True):
        if app_name in wanted:
            return True, open_app(app_name)

    close = difflib.get_close_matches(wanted, list(APPS), n=1, cutoff=0.6)
    if close:
        return True, open_app(close[0])

    # Fall back to opening a website (or a YouTube search) in the browser.
    if " " not in wanted:
        import webbrowser

        domain = wanted if "." in wanted else wanted + ".com"
        webbrowser.open("https://" + domain)
        return True, f"Opening {wanted}"

    return True, (
        f"Sorry, I do not know how to open {wanted}. "
        f"I can open: {', '.join(APPS)}, or say 'open youtube' or 'open github'."
    )


def stream_reply(messages, on_chunk):
    """Stream Jarvis's reply. Groq (cloud) first, Ollama (local) as the
    offline fallback if Groq is missing, the network is down, or the
    request fails."""
    if GROQ_API_KEY:
        try:
            from groq import Groq

            client = Groq(api_key=GROQ_API_KEY)
            stream = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=messages,
                temperature=0.7,
                max_tokens=512,
                stream=True,
            )
            for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    on_chunk(delta)
            return
        except Exception as error:
            messages.pop()
            print(f"(Groq unavailable, using Ollama instead: {error})")

    for chunk in ollama.chat(
        model=MODEL, messages=messages, stream=True, options=MODEL_OPTIONS
    ):
        on_chunk(chunk["message"]["content"])


def process(text):
    """Handle one user message. Runs in a background thread."""
    js("onStart()")
    orb_msg(text)

    handled, note = handle_command(text)
    if handled:
        js(f"onNote({json.dumps(note)})")
        js("onDone()")
        orb_msg(note)
        speak(note)
        ui_idle()
        return

    remember = re.match(r"\bremember\b(\s+that)?\s+(.+?)[.!?]*$", text, re.IGNORECASE)
    if remember:
        fact = memory.add_fact(remember.group(2).strip())
        note = "Got it, I will remember that." + (
            f" ({fact})" if fact else ""
        )
        js(f"onNote({json.dumps(note)})")
        js("onDone()")
        orb_msg(note)
        speak(note)
        ui_idle()
        return

    messages.append({"role": "user", "content": text})
    messages[0]["content"] = build_system()
    reply_chunks = []

    def on_chunk(part):
        reply_chunks.append(part)
        js(f"onChunk({json.dumps(part)})")

    try:
        stream_reply(messages, on_chunk)
    except Exception as error:
        messages.pop()
        js(f"onError({json.dumps(str(error))})")
        js("onDone()")
        ui_idle()
        return

    reply = "".join(reply_chunks)

    messages.append({"role": "assistant", "content": reply})
    memory.add_exchange(text, reply)
    js("onDone()")

    js("setState('speaking')")
    orb_msg(reply)
    speak(reply)
    ui_idle()


def submit(text):
    """Send a user message to Jarvis (used by typing and by voice)."""
    text = (text or "").strip()
    if not text:
        return

    if text.lower() in ("exit", "quit"):
        js("onNote('Goodbye!')")
        speak("Goodbye!")
        do_exit()
        return

    threading.Thread(target=process, args=(text,), daemon=True).start()


# ------------------------------------------------------------------
# Voice input (Stage 2)
#
# 1. WAKE-WORD loop: a dedicated "hey jarvis" detector that runs all
#    the time. It is designed to hear "hey jarvis" reliably.
# 2. VOICE-COMMAND loop: after the wake word, vosk (the big model)
#    transcribes the next sentence and sends it to Jarvis.
# ------------------------------------------------------------------
def wake_callback(indata, frames, time_info, status):
    """Runs for every 80 ms of local audio. Looks for the wake word.
    No audio is ever sent to the cloud here - only when the wake word
    is actually confirmed does the command clip go to Groq."""
    global last_wake_time, wake_confirm_since

    # While Jarvis talks, only listen for interrupt words ('stop', etc.)
    # so you can cut her off mid-answer. The wake word is paused then.
    if speaking.is_set():
        _check_barge_in(bytes(indata))
        return
    if wake_model is None:
        return

    frame = np.frombuffer(bytes(indata), dtype=np.int16)
    try:
        scores = wake_model.predict(frame)
    except Exception as error:
        print(f"(Wake predict error: {error})")
        return

    score = scores.get("hey_jarvis", 0) or 0
    now = time.time()
    if score < WAKE_THRESHOLD:
        wake_confirm_since = 0.0
        return

    # Two quick hits (~0.6 s apart) confirm the wake word: cuts random
    # false fires, and lowers the threshold so real hits are not missed.
    if now - last_wake_time <= 2.0:
        wake_confirm_since = 0.0
        return
    if wake_confirm_since and now - wake_confirm_since <= 0.6:
        wake_confirm_since = 0.0
        last_wake_time = now
        print(f"(wake word heard - {WAKE_WORD}, score {score:.2f})")
        try:
            winsound.Beep(1200, 80)
            winsound.Beep(1600, 90)
        except Exception:
            pass
        show_window()
        js("setState('listening')")
        # Start (or keep) conversation mode: record ONLY each command and
        # send that one clip to Groq (the same fast engine as the mic
        # button). Continuous audio never leaves the PC.
        if not conversation_active:
            threading.Thread(
                target=run_click_stt, kwargs={"conversation": True}, daemon=True
            ).start()
        return
    if not wake_confirm_since:
        wake_confirm_since = now


def wake_loop():
    """Opens its own microphone stream and hunts for the wake word."""
    global wake_model

    try:
        from openwakeword import Model

        wake_model = Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")
        print("(wake word detector ready - say 'hey jarvis')")
    except Exception as error:
        print(f"(Wake word unavailable: {error})")
        return

    stream = None
    while True:
        if not mic_event.is_set():
            if stream is not None:
                stream.stop()
                stream.close()
                stream = None
            time.sleep(0.3)
            continue

        if stream is None:
            try:
                stream = sd.InputStream(
                    samplerate=SAMPLE_RATE,
                    blocksize=1280,
                    channels=1,
                    dtype="int16",
                    callback=wake_callback,
                )
                stream.start()
            except Exception as error:
                print(f"(Wake mic error: {error})")
                time.sleep(2)
                continue

        if not armed():
            time.sleep(0.2)


def audio_callback(indata, frames, time_info, status):
    try:
        audio_queue.put_nowait(bytes(indata))
    except queue.Full:
        pass


def load_transcriber():
    """Prefer faster-whisper (Siri-like accuracy). Falls back to vosk."""
    try:
        from faster_whisper import WhisperModel

        model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
        print(f"(Whisper ready - model {WHISPER_MODEL})")
        return ("whisper", model)
    except Exception as error:
        print(f"(Whisper unavailable, using vosk: {error})")
    try:
        return ("vosk", vosk.Model(VOSK_MODEL_PATH))
    except Exception as error:
        print(f"(Voice command input unavailable: {error})")
        return (None, None)


def _drain_queue():
    while True:
        try:
            audio_queue.get_nowait()
        except queue.Empty:
            break


def _chunk_rms(chunk):
    samples = np.frombuffer(chunk, dtype=np.int16)
    if samples.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(samples.astype(np.float32) ** 2)))


def _finalize_command(text):
    """Send one captured phrase to Jarvis (or politely prompt)."""
    disarm()
    if text:
        command = strip_wake(text)
        if command:
            js(f"onUserMsg({json.dumps(command)})")
            submit(command)
            return
    js("onNote('Yes?')")
    speak("Yes?")
    ui_idle()


def transcribe(clip, model):
    """Transcribe one captured PCM clip. Groq's whisper-large-v3-turbo
    (cloud, Siri-level accuracy) first; local faster-whisper as the
    offline fallback."""
    if GROQ_API_KEY:
        try:
            from groq import Groq

            wav = io.BytesIO()
            wf = wave.open(wav, "wb")
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(clip)
            wf.close()
            client = Groq(api_key=GROQ_API_KEY)
            resp = client.audio.transcriptions.create(
                model=GROQ_STT_MODEL,
                file=("command.wav", wav.getvalue(), "audio/wav"),
            )
            text = (resp.text or "").strip()
            if text:
                print(f"(heard: {text})")
                return text
        except Exception as error:
            print(f"(Groq STT unavailable, using local whisper: {error})")
    samples = np.frombuffer(clip, dtype=np.int16).astype(np.float32) / 32768.0
    segments, _info = model.transcribe(
        samples, language="en", beam_size=1, vad_filter=False
    )
    text = " ".join(seg.text for seg in segments).strip()
    if text:
        print(f"(heard: {text})")
    return text


def run_whisper(model):
    """One-shot capture: after the wake word Jarvis listens once for a
    phrase (ends on 1.2 s of silence or a hard cap), then transcribes
    the whole clip with faster-whisper. Understands speech like Siri."""
    stream = None
    while True:
        if not mic_event.is_set():
            if stream is not None:
                stream.stop()
                stream.close()
                stream = None
            _drain_queue()
            run_whisper.clip = None
            disarm()
            time.sleep(0.3)
            continue

        if stream is None:
            try:
                stream = sd.InputStream(
                    samplerate=SAMPLE_RATE,
                    blocksize=8000,
                    channels=1,
                    dtype="int16",
                    callback=audio_callback,
                )
                stream.start()
            except Exception as error:
                print(f"(Microphone error: {error})")
                time.sleep(2)
                continue

        try:
            chunk = audio_queue.get(timeout=0.5)
        except queue.Empty:
            continue

        # Never listen to Jarvis's own voice.
        if speaking.is_set():
            run_whisper.clip = None
            run_whisper.silence = 0.0
            _drain_queue()
            continue

        if not armed():
            run_whisper.clip = None
            run_whisper.silence = 0.0
            continue

        if run_whisper.clip is None:
            # Wait for real speech before opening the clip window.
            if _chunk_rms(chunk) < VAD_THRESHOLD:
                continue
            run_whisper.clip = bytearray()
            run_whisper.silence = 0.0

        run_whisper.clip.extend(chunk)
        run_whisper.silence = 0.0 if _chunk_rms(chunk) >= VAD_THRESHOLD else run_whisper.silence + 0.5

        done = (
            run_whisper.silence >= END_SILENCE_SECONDS
            or len(run_whisper.clip) >= MAX_CLIP_SECONDS * SAMPLE_RATE * 2
        )
        if not done:
            continue

        clip = bytes(run_whisper.clip)
        run_whisper.clip = None
        run_whisper.silence = 0.0

        text = transcribe(clip, model)
        _finalize_command(text)


run_whisper.clip = None
run_whisper.silence = 0.0


def run_vosk(model):
    """Fallback transcriber using streaming vosk-small."""
    rec = vosk.KaldiRecognizer(model, SAMPLE_RATE)
    stream = None
    while True:
        if not mic_event.is_set():
            if stream is not None:
                stream.stop()
                stream.close()
                stream = None
            rec = vosk.KaldiRecognizer(model, SAMPLE_RATE)
            _drain_queue()
            disarm()
            time.sleep(0.3)
            continue

        if stream is None:
            try:
                stream = sd.InputStream(
                    samplerate=SAMPLE_RATE,
                    blocksize=8000,
                    channels=1,
                    dtype="int16",
                    callback=audio_callback,
                )
                stream.start()
            except Exception as error:
                print(f"(Microphone error: {error})")
                time.sleep(2)
                continue

        try:
            data = audio_queue.get(timeout=0.5)
        except queue.Empty:
            continue

        # Never listen to Jarvis's own voice.
        if speaking.is_set():
            rec.Reset()
            _drain_queue()
            continue

        if not armed():
            continue

        if rec.AcceptWaveform(data):
            text = json.loads(rec.Result()).get("text", "")
            print(f"(heard: {text})" if text else "")
            _finalize_command(text)


# ------------------------------------------------------------------
# Click-to-talk (Stage 2b): fast Groq speech-to-text on the mic button.
#
# One separate engine (the swap point for voice recognition). Click the
# mic -> "Listening" -> capture (waits up to 5 s for speech, ends ~1 s
# after you stop, hard cap 10 s) -> gently normalize + cut leading
# silence -> "Understanding" -> Groq whisper-large-v3-turbo (cloud,
# same request as mic_test.py, key only from C:\jarvis\.env, never
# printed or logged). If Groq or the internet fails, the existing Vosk
# model transcribes the same clip and Jarvis tells you. The recognized
# text goes through submit() - exactly the same path as typing - so
# "open chrome" and every other command works identically.
# ------------------------------------------------------------------
CLICK_START_TIMEOUT = 5.0
CLICK_END_SILENCE = VOICE_END_SILENCE  # single tunable, see top of file
CLICK_MAX_SECONDS = 10.0
click_vosk_model = None


def _measure_noise():
    """Sample ~1 s of ambient audio to calibrate the speech level bar
    (phantom-speech fix). Frames collected while Jarvis is talking are
    skipped. The result is cached for NOISE_CACHE_SECONDS so the 1 s
    delay only happens every so often. Returns the speech threshold to
    use - at least VAD_THRESHOLD, at most NOISE_LEVEL_CAP."""
    global noise_cached_threshold, noise_cached_until
    now = time.time()
    if now < noise_cached_until:
        return noise_cached_threshold

    chunks = []

    def on_audio(indata, frames, time_info, status):
        # Never calibrate over Jarvis's own voice.
        if not speaking.is_set():
            chunks.append(bytes(indata))

    stream = None
    try:
        stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            blocksize=int(0.2 * SAMPLE_RATE),
            channels=1,
            dtype="int16",
            callback=on_audio,
        )
        stream.start()
    except Exception as error:
        print(f"(Noise sample error: {error})")
        return VAD_THRESHOLD
    try:
        time.sleep(NOISE_SAMPLE_SECONDS)
    finally:
        try:
            if stream is not None:
                stream.stop()
                stream.close()
        except Exception:
            pass

    levels = [_chunk_rms(c) for c in chunks]
    if len(levels) < 2:
        print("(noise sample too short - using VAD_THRESHOLD)")
        return VAD_THRESHOLD  # not cached: let the next wake try again

    noise = float(np.median(levels))
    level = max(VAD_THRESHOLD, NOISE_THRESHOLD_FACTOR * noise)
    if level > NOISE_LEVEL_CAP:
        level = NOISE_LEVEL_CAP
    noise_cached_threshold = level
    noise_cached_until = time.time() + NOISE_CACHE_SECONDS
    print(f"(noise floor median {noise:.0f} -> speech threshold {level:.0f}"
          f" cached {int(NOISE_CACHE_SECONDS)}s)")
    return level


def run_click_stt(conversation=False):
    """Click-to-talk speech recognition (Groq cloud, Vosk offline).

    conversation=True keeps listening after each reply (no wake word)
    until CONVERSATION_TIMEOUT seconds of silence, or an end phrase -
    see END_CONVERSATION_PHRASES. Mic button and Ctrl+Alt+J keep using
    conversation=False (one command per press), exactly as before.
    """
    global click_vosk_model, conversation_active, conversation_until

    disarm()

    # Calibrate the speech bar to ambient noise when a conversation
    # starts (phantom-speech fix). Single-shot keeps plain VAD_THRESHOLD.
    clip_threshold = VAD_THRESHOLD
    if conversation and not conversation_active:
        conversation_active = True
        conversation_until = time.time() + CONVERSATION_TIMEOUT
        clip_threshold = _measure_noise()

    def waver(raw):
        bio = io.BytesIO()
        with wave.open(bio, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SAMPLE_RATE)
            w.writeframes(raw)
        return bio.getvalue()

    def capture_once():
        """Listen for one phrase; return raw int16 bytes, b"" if no speech
        within CLICK_START_TIMEOUT or if too little real voice, or None
        if the mic cannot be opened."""
        chunks = []
        clip = bytearray()
        started_at = time.time()
        captured = 0.0
        silence = 0.0
        voiced = 0.0

        def on_audio(indata, frames, time_info, status):
            chunks.append(bytes(indata))

        stream = None
        try:
            stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                blocksize=int(0.2 * SAMPLE_RATE),
                channels=1,
                dtype="int16",
                callback=on_audio,
            )
            stream.start()
        except Exception as error:
            print(f"(Click mic error: {error})")
            return None

        try:
            while True:
                # Never record Jarvis's own voice.
                if speaking.is_set():
                    clip.clear()
                    silence = 0.0
                    captured = 0.0
                    voiced = 0.0
                    chunks.clear()
                    time.sleep(0.02)
                    continue
                if chunks:
                    chunk = b"".join(chunks)
                    chunks.clear()
                else:
                    time.sleep(0.02)
                    continue
                level = _chunk_rms(chunk)
                if not clip:
                    if level < clip_threshold:
                        if time.time() - started_at >= CLICK_START_TIMEOUT:
                            break
                        continue
                    if time.time() - started_at >= CLICK_START_TIMEOUT:
                        break
                    clip.extend(chunk)
                    captured = len(clip) / (SAMPLE_RATE * 2)
                    voiced = 0.2
                    silence = 0.0
                    continue
                clip.extend(chunk)
                captured += len(chunk) / (SAMPLE_RATE * 2)
                if level >= clip_threshold:
                    voiced += 0.2
                silence = 0.0 if level >= clip_threshold else silence + 0.2
                if silence >= CLICK_END_SILENCE or captured >= CLICK_MAX_SECONDS:
                    break
        finally:
            try:
                if stream is not None:
                    stream.stop()
                    stream.close()
            except Exception:
                pass

        # Phantom-speech guardrail: require real (voiced) audio, not just
        # a couple of noise blips crossing the bar.
        if voiced < VOICED_REQUIRED_SECONDS:
            return b""
        return bytes(clip)

    while True:
        # Conversation mode: wait for her voice to fully finish before
        # listening again, then restart the quiet timer so a long answer
        # does not eat into the 10 seconds.
        if conversation:
            if not conversation_active:
                return
            while speaking.is_set() and conversation_active:
                time.sleep(0.1)
            if not conversation_active:
                return
            conversation_until = time.time() + CONVERSATION_TIMEOUT
            if time.time() >= conversation_until or not mic_on:
                conversation_active = False
                ui_idle()
                return
            js("setState('listening')")

        raw = capture_once()
        if raw is None:
            js("onNote('Microphone error - click the mic and try again.')")
            ui_idle()
            return
        if not raw:
            if conversation and conversation_active:
                if time.time() >= conversation_until:
                    conversation_active = False
                    ui_idle()
                    return
                continue  # nothing said yet - keep listening, quietly
            js("onNote('I did not hear anything. Try again?')")
            ui_idle()
            return

        # Gently normalize (only boost quiet clips) and cut leading silence.
        samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
        win = int(0.04 * SAMPLE_RATE)
        first = None
        for i in range(0, max(1, len(samples) - win + 1), win):
            seg = samples[i:i + win]
            if seg.size and float(np.sqrt(np.mean(seg ** 2))) >= clip_threshold:
                first = i
                break
        samples = samples[first or 0:]
        peak = float(np.abs(samples).max()) if samples.size else 0.0
        if 1.0 < peak < 6000:
            samples = samples * min(4.0, 6000.0 / peak)
        samples = np.clip(samples, -32768, 32767).astype(np.int16)
        wav = waver(samples.tobytes())

        js("setState('understanding')")

        # Groq cloud transcription (same request as mic_test.py).
        text = ""
        used_local = False
        groq_answered = False
        if GROQ_API_KEY:
            try:
                import httpx

                resp = httpx.post(
                    "https://api.groq.com/openai/v1/audio/transcriptions",
                    headers={"Authorization": "Bearer " + GROQ_API_KEY},
                    files={"file": ("speech.wav", wav, "audio/wav")},
                    data={
                        "model": GROQ_STT_MODEL,
                        "language": "en",
                        "response_format": "verbose_json",
                        "temperature": 0,
                        "prompt": "Jarvis, open chrome, open notepad, play a song, remind me",
                    },
                    timeout=30,
                )
                if resp.status_code == 200:
                    groq_answered = True
                    data = resp.json()
                    text = (data.get("text") or "").strip()
                    # Phantom-speech guardrail: drop the clip when Groq's
                    # confidence says it was really silence/noise.
                    for seg in data.get("segments") or []:
                        nsp = seg.get("no_speech_prob", 0.0)
                        alp = seg.get("avg_logprob", 0.0)
                        if (nsp > NO_SPEECH_PROB_MAX and alp < AVG_LOGPROB_MIN) \
                                or alp < AVG_LOGPROB_HARD_MIN:
                            print(f"(ignored: low-confidence speech - {text!r})")
                            text = ""
                            break
                else:
                    print(f"(Groq STT error {resp.status_code})")
            except Exception as error:
                print(f"(Groq STT failed, using Vosk: {error})")

        # Offline fallback runs ONLY when Groq never answered (no key, no
        # internet, or a request error). If Groq heard 'nothing' (silence
        # confidence) or a phantom phrase, Vosk is skipped too - silence
        # stays silence instead of being turned into invented words.
        if not text and not groq_answered:
            used_local = True
            try:
                if click_vosk_model is None:
                    click_vosk_model = vosk.Model(VOSK_MODEL_PATH)
                rec = vosk.KaldiRecognizer(click_vosk_model, SAMPLE_RATE)
                if rec.AcceptWaveform(samples.tobytes()):
                    text = json.loads(rec.Result()).get("text", "").strip()
                else:
                    text = json.loads(rec.FinalResult()).get("text", "").strip()
            except Exception as error:
                print(f"(Vosk fallback failed: {error})")

        text = normalize_voice(text)
        if text in PHANTOM_PHRASES:
            print(f"(ignored: {text})")
            text = ""
        if not text:
            if conversation and conversation_active:
                continue
            js("onNote('I could not understand that. Try again?')")
            ui_idle()
            return

        print(f"(heard: {text})")
        if used_local:
            note = "(Internet unavailable - used offline voice recognition)"
            print(note)
            js(f"onNote({json.dumps(note)})")
            orb_msg(note)

        # End the conversation early with an end phrase.
        if conversation and text in END_CONVERSATION_PHRASES:
            conversation_active = False
            js(f"onUserMsg({json.dumps(text)})")
            js("onNote('Okay, I will listen for \"hey jarvis\" again.')")
            speak("Okay.")
            ui_idle()
            return

        # Same path as typing: 'open chrome' and friends all work here.
        js(f"onUserMsg({json.dumps(text)})")
        submit(text)

        if not conversation:
            return

        # Conversation continues: loop back to the top, wait for her
        # reply to finish, restart the quiet timer, and listen again.


def listener_loop():
    """Transcribes speech after the wake word has been heard."""
    backend, model = load_transcriber()
    if backend is None:
        return
    if backend == "whisper":
        run_whisper(model)
    else:
        run_vosk(model)


def toast(title, message):
    """Show a Windows notification. Best-effort, never crashes."""
    try:
        title = title.replace("'", "''")
        message = message.replace("'", "''")
        app_path = sys.executable.replace("'", "''")
        script = (
            "$ErrorActionPreference='SilentlyContinue';"
            "$lnkPath=Join-Path $env:APPDATA 'Microsoft\\Windows\\Start Menu\\Programs\\Jarvis.lnk';"
            "if(-not(Test-Path $lnkPath)){"
            "$w=New-Object -ComObject WScript.Shell;"
            "$s=$w.CreateShortcut($lnkPath);"
            f"$s.TargetPath='{app_path}';"
            "$s.Save()};"
            "[Windows.UI.Notifications.ToastNotificationManager,Windows.UI.Notifications,ContentType=WindowsRuntime]|Out-Null;"
            "[Windows.Data.Xml.Dom.XmlDocument,Windows.Data.Xml.Dom.XmlDocument,ContentType=WindowsRuntime]|Out-Null;"
            "$t=[Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
            "$ns=$t.GetElementsByTagName('text');"
            f"$ns.Item(0).AppendChild($t.CreateTextNode('{title}'))|Out-Null;"
            f"$ns.Item(1).AppendChild($t.CreateTextNode('{message}'))|Out-Null;"
            "$toast=New-Object Windows.UI.Notifications.ToastNotification $t;"
            "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('Jarvis').Show($toast)"
        )
        subprocess.Popen(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", script],
            creationflags=0x08000000,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as error:
        print(f"(Toast failed: {error})")


def orb_pump():
    """Keep the 3D orb animating.

    requestAnimationFrame and timer callbacks can freeze in this WebView2
    build (black, static orb), so each animation frame is pushed from here
    via evaluate_js(), which always executes.
    """
    while True:
        time.sleep(0.033)
        try:
            window.evaluate_js(
                "window.__orb && window.__orb.step && ((window.__orb.step(), true))"
            )
        except Exception:
            pass


def reminder_loop():
    """Background timer. Fires each reminder as soon as its time comes."""
    while True:
        time.sleep(15)
        for reminder in reminders.due_reminders():
            task = reminder["task"]
            print(f"(reminder due - {task})")
            show_window()
            js("setState('speaking')")
            js(f"onNote({json.dumps('Reminder: ' + task)})")
            speak(task)
            toast("Jarvis Reminder", task)
            ui_idle()


class Api:
    """Methods the HTML page can call."""

    def log(self, text):
        print("PAGE LOG: " + text, flush=True)

    def send_message(self, text):
        submit(text)
        return {"ok": True}

    def get_state(self):
        return {"on": mic_on}

    def toggle_mic(self):
        """Mic button = click-to-talk: one fast voice capture right now
        (no wake word needed). Launched in its own thread so the button
        stays responsive; run_click_stt does Listening -> Understanding
        -> Thinking and puts the words through submit() like typing.
        If Jarvis is already talking, the press cuts her off instead."""
        global mic_on
        if speaking.is_set():
            speak_interrupt()
            return {"on": mic_on, "state": "listening"}
        if not mic_on:
            mic_on = True
            mic_event.set()
        threading.Thread(target=run_click_stt, daemon=True).start()
        return {"on": mic_on, "state": "listening"}


def allow_camera():
    """Tell the WebView2 window to allow webcam requests (hand gestures).

    pywebview's WebView2 backend does not answer permission requests by
    default, so the camera getUserMedia() call would hang forever. This
    attaches a PermissionRequested handler that allows the Camera kind.
    """
    try:
        import webview.platforms.edgechromium as _ec

        from Microsoft.Web.WebView2.Core import (
            CoreWebView2PermissionKind,
            CoreWebView2PermissionState,
        )

        _original = _ec.EdgeChrome.on_webview_ready

        def _on_permission(sender, args):
            try:
                if args.PermissionKind == CoreWebView2PermissionKind.Camera:
                    args.State = CoreWebView2PermissionState.Allow
            except Exception as error:
                print(f"(Permission error: {error})")

        def _patched(self, sender, args):
            _original(self, sender, args)
            try:
                sender.CoreWebView2.PermissionRequested += _on_permission
            except Exception as error:
                print(f"(Camera permission hook failed: {error})")

        _ec.EdgeChrome.on_webview_ready = _patched
        print("(camera permission ready - hand gestures available)")
    except Exception as error:
        print(f"(camera permission unavailable: {error})")


def start_web_server(directory):
    """Serve the UI over http://127.0.0.1 so the webview can use classic
    scripts, ES module imports and the webcam without file:// restrictions.
    """

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=directory, **kwargs)
            # ES modules and WebAssembly need correct MIME types or the
            # browser silently refuses to run them.
            self.extensions_map = self.extensions_map.copy()
            self.extensions_map[".mjs"] = "text/javascript"
            self.extensions_map[".wasm"] = "application/wasm"

        def log_message(self, *args):
            pass

        def _blocked(self):
            path = self.path.split("?", 1)[0].lstrip("/")
            name = os.path.basename(path).lower()
            if name.startswith((".", "~")):
                return True
            return name.endswith(
                (".log", ".py", ".bat", ".json", ".toml", ".ini", ".env")
            )

        def do_GET(self):
            if self._blocked():
                self.send_error(404)
                return
            super().do_GET()

        def do_HEAD(self):
            if self._blocked():
                self.send_error(404)
                return
            super().do_HEAD()

    for _attempt in range(5):
        try:
            httpd = socketserver.TCPServer(("127.0.0.1", 0), Handler)
            break
        except OSError:
            time.sleep(0.2)
    else:
        return None

    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return "http://127.0.0.1:%d" % port


def keep_window_visible():
    """Keep the jarvis window on the desktop.

    If the window gets moved off-screen or minimized (parked windows are a
    known WebView2 trick), nudge it back. Checks are cheap and only act
    when needed, so it never steals focus from a healthy window. While the
    window is hidden away in the tray it only fixes the position.
    """
    while True:
        time.sleep(4)
        try:
            if window.x < -500 or window.y < -500:
                window.move(60, 60)
            if not hidden_to_tray:
                window.restore()
        except Exception:
            pass


def main():
    global window, hidden_to_tray

    # Only one Jarvis may run at a time (fixes duplicate windows).
    if not presence.acquire_single_instance():
        return

    # Started at login via "Start with Windows": hide to the tray.
    if "--tray" in sys.argv:
        hidden_to_tray = True

    def set_hidden(value):
        global hidden_to_tray
        hidden_to_tray = value

    presence.install_close_hook(
        exit_allowed=lambda: presence.exit_requested,
        on_hidden=lambda: set_hidden(True),
    )

    allow_camera()
    greeting = "Hello, I am Jarvis. Say 'hey jarvis' to talk to me."
    base_url = start_web_server(HERE)
    page = "%s/%s" % (base_url, UI_HTML) if base_url else os.path.join(HERE, UI_HTML)

    window = webview.create_window(
        "JARVIS",
        page,
        js_api=Api(),
        width=1150,
        height=760,
        min_size=(900, 600),
        background_color="#040b17",
    )
    if hidden_to_tray:
        try:
            window.hide()
        except Exception:
            pass

    threading.Thread(target=tts_worker, daemon=True).start()
    threading.Thread(target=wake_loop, daemon=True).start()
    threading.Thread(target=reminder_loop, daemon=True).start()
    threading.Thread(target=orb_pump, daemon=True).start()
    threading.Thread(target=keep_window_visible, daemon=True).start()

    presence.start_tray(
        show_fn=show_window,
        listen_fn=trigger_listen,
        exit_fn=do_exit,
    )
    presence.start_hotkey(trigger_listen)

    def greet():
        if hidden_to_tray:
            return
        time.sleep(1.5)
        speak(greeting)

    threading.Thread(target=greet, daemon=True).start()
    try:
        webview.start(debug=False)
    except BaseException:
        import traceback

        with open(os.path.join(HERE, "crash.log"), "a", encoding="utf-8") as log:
            log.write(time.ctime() + "\n")
            traceback.print_exc(file=log)
            log.write("\n")
        raise
    finally:
        presence.release_single_instance()
        presence.stop_tray()


if __name__ == "__main__":
    main()
