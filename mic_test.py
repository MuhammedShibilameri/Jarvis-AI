import time, wave, io
import numpy as np
import sounddevice as sd
import httpx

def load_key():
    for line in open(r"C:\jarvis\.env", encoding="utf-8-sig"):
        line = line.strip()
        if line.startswith("GROQ_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None

key = load_key()
if not key:
    raise SystemExit("No GROQ_API_KEY found in C:\\jarvis\\.env")

RATE = 16000
SECONDS = 5

print("Microphone:", sd.query_devices(sd.default.device[0])["name"])
print("Recording starts in 2 seconds...")
time.sleep(2)
print(">>> SPEAK NOW: say 'open chrome'")
audio = sd.rec(int(SECONDS * RATE), samplerate=RATE, channels=1, dtype="int16")
sd.wait()
print("Done recording.")

peak = int(np.abs(audio).max())
print("Loudness peak (0 to 32767):", peak)
if peak < 1500:
    print("WARNING: your voice is very quiet. The microphone level or device may be wrong.")

buf = io.BytesIO()
with wave.open(buf, "wb") as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(RATE)
    w.writeframes(audio.tobytes())

start = time.time()
response = httpx.post(
    "https://api.groq.com/openai/v1/audio/transcriptions",
    headers={"Authorization": "Bearer " + key},
    files={"file": ("speech.wav", buf.getvalue(), "audio/wav")},
    data={
        "model": "whisper-large-v3-turbo",
        "language": "en",
        "response_format": "json",
        "prompt": "Jarvis, open chrome, open notepad, play a song, remind me",
    },
    timeout=30,
)
seconds = round(time.time() - start, 2)

if response.status_code == 200:
    print("She heard:", response.json().get("text", ""))
    print("Time taken:", seconds, "seconds")
else:
    print("Error", response.status_code, response.text[:300])
