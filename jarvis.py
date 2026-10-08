import difflib
import os
import shutil
import subprocess
import threading
import time

import ollama
import pyttsx3

import reminders

MODEL = "llama3.2:3b"
VOICE_NAME = "Zira"

# Keeps Ollama's memory needs small so it does not run out of RAM.
MODEL_OPTIONS = {"num_ctx": 4096}

# Stage 1: apps Jarvis can open.
# To add a new app, just add one line, for example:
#     "notepad++": ["notepad++"],
# Each entry is a list of places to look for the app. Jarvis tries
# them one by one and never crashes if one is missing.
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


def speak(text):
    """Speak the text out loud using the Zira (female) voice."""
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


def handle_command(user_text):
    """Handle 'open ...' and reminder commands before talking to the AI model.

    Returns True if the command was handled, False otherwise.
    """
    lowered = user_text.lower().strip()

    # Stage 3: reminders ("remind me to ... at ...", "my reminders", ...).
    handled, note = reminders.handle_reminder(lowered)
    if handled:
        print(f"Jarvis: {note}")
        speak(note)
        return True

    if not lowered.startswith("open "):
        return False

    wanted = lowered[5:].strip(" ?.!\t")

    if not wanted:
        print("Jarvis: What should I open?")
        speak("What should I open?")
        return True

    for app_name in APPS:
        if app_name == wanted:
            open_app(app_name)
            return True

    for app_name in sorted(APPS, key=len, reverse=True):
        if app_name in wanted:
            open_app(app_name)
            return True

    close = difflib.get_close_matches(wanted, list(APPS), n=1, cutoff=0.6)
    if close:
        open_app(close[0])
        return True

    message = (
        f"Sorry, I do not know how to open {wanted}. "
        f"I can open: {', '.join(APPS)}."
    )
    print(f"Jarvis: {message}")
    speak(message)
    return True


def reminder_loop():
    """Background timer: speaks each reminder when its time comes."""
    while True:
        time.sleep(15)
        for reminder in reminders.due_reminders():
            task = reminder["task"]
            print(f"(reminder due - {task})")
            speak(f"Reminder: {task}")


print("Jarvis is ready. Type 'exit' to quit.")
speak("Hello, I am Jarvis. How can I help you?")

threading.Thread(target=reminder_loop, daemon=True).start()

while True:
    user_text = input("You: ").strip()

    if not user_text:
        continue

    if user_text.lower() in ("exit", "quit"):
        print("Jarvis: Goodbye!")
        speak("Goodbye!")
        break

    if handle_command(user_text):
        continue

    messages.append({"role": "user", "content": user_text})

    try:
        reply = ""
        print("Jarvis: ", end="", flush=True)
        for chunk in ollama.chat(model=MODEL, messages=messages, stream=True, options=MODEL_OPTIONS):
            part = chunk["message"]["content"]
            print(part, end="", flush=True)
            reply += part
        print()
    except Exception as error:
        print(f"\nError: {error}")
        messages.pop()
        continue

    messages.append({"role": "assistant", "content": reply})
    speak(reply)