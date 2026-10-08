# JARVIS PROJECT BRIEF (FULL VERSION)

## Progress
- DONE: Stage 1 (open apps) and Stage 2 (voice input, wake word "hey jarvis") — in jarvis_ui.py (Orb UI + voice + typing) and jarvis.py (terminal).
- DONE (preview): Stage 8 desktop Orb UI (pywebview) is already built and is the main app.
- DONE: Ultron-style 3D orb (ported from SAGAR-TAMANG/ultron-by-sagar-builds, MIT) is now the default UI — jarvis_ultron.html + C:\jarvis\ultron\ (Three.js files + orb.js). Light blue fallback stays in jarvis_ui.html (switch by editing UI_HTML in jarvis_ui.py). No Node/webcam used; original amber colors kept.
- IN PROGRESS: Stage 3 (reminders & notifications). Reminder file: C:\jarvis\reminders.json (module C:\jarvis\reminders.py).
- NOTE: The assistant no longer says she was created by Shibil (rule removed 2026-10-08).

I am a beginner (junior Flutter developer). Help me build "Jarvis", a personal AI assistant that runs on my own Windows computer. It should become my personal assistant for every kind of work an AI can realistically help with.

## My setup
- Windows with PowerShell. Project folder: C:\jarvis
- Python 3.12 with a virtual environment at C:\jarvis\venv (already active when I work)
- Ollama runs locally at http://localhost:11434
- Models: llama3.2:3b (chat) and qwen2.5-coder:7b (code)
- Installed Python libraries: ollama, pyttsx3
- Node.js is installed only because OpenCode needs it. Do NOT use it for Jarvis.

## What already works (DO NOT BREAK)
jarvis.py is a terminal chat: I type, Jarvis answers using llama3.2:3b through Ollama, prints the reply, and speaks it with the female Microsoft Zira voice using pyttsx3. If anyone asks who created her, she answers: "Shibil". A working backup is in jarvis_backup.py (if it exists).

## Personality
- Jarvis has a FEMALE voice and a friendly, smart, short-answer style.
- She is my personal assistant, and always says she was created by Shibil.

## Features to build, ONE STAGE AT A TIME
Stage 1: Open apps. When I say or type "open chrome", "open notepad", "open vs code", Jarvis opens it and says "Opening chrome". Use a simple dictionary of app names so I can add more. These commands are handled in Python BEFORE calling the AI model.
Stage 2: Voice input. I speak, Jarvis listens through the microphone and understands, then replies by voice. Keep typing as a fallback. Suggest a wake word such as "Jarvis".
Stage 3: Reminders and notifications. I say "remind me to ... at ...". Jarvis keeps a to-do and reminder list saved in a file, shows Windows notifications, and speaks them at the right time.
Stage 4: Messaging. I say "message [name]". Jarvis asks what to say, helps me write it, shows it to me, and only sends after I confirm. Use the safest realistic method (for example opening WhatsApp Web or the email app with the message prefilled, or sending email with smtplib).
Stage 5: Job helper. I am looking for fresher Flutter developer jobs in Kozhikode, Kochi and Kannur. Jarvis should open job search pages for me, write cover letters and application emails with the AI model, keep a job tracker file (company, role, date applied, status), and remind me to follow up.
Stage 6: Memory. Jarvis saves my preferences and important facts in a local file and remembers them next time.
Stage 7: Extra daily helper features: summaries, answering questions, simple calculations, time and date, and quick notes.

## Honest limits (please tell me the truth about these)
- Reading ALL my Windows notifications is very hard. A realistic version is Jarvis's own reminders and notifications.
- Fully automatic job applying and bulk messaging are risky and often break website rules. Do the safe version: Jarvis prepares everything and I confirm and submit.
- A 3B and 7B local model is limited. Keep tasks simple and tell me when something will not work well.

## Safety rules
- Jarvis must ALWAYS ask me to confirm before sending any message, email, or job application.
- NEVER put passwords or API keys in code files. Use a .env file and tell me how to keep it private.
- Keep everything local and offline where possible.

## Rules for you (OpenCode)
1. Work on ONE stage at a time. Start with Stage 1 only.
2. For each stage: first give a short plan (3 to 5 lines), then ask my permission before creating or editing any file.
3. Never break the features that already work. Make a backup before big changes.
4. Always give COMPLETE files that I can run directly, not partial snippets.
5. Give me only ONE PowerShell command at a time, and tell me what I should see when it works.
6. List any new libraries I need to install with pip, one command at a time.
7. Explain everything in simple words, because I am a beginner.
8. After each stage, tell me how to test it, and wait for me to say it works before starting the next stage.

## FINAL STAGE (Stage 8): Jarvis desktop UI (build ONLY after Stages 1 to 7 work)
- I do not want to use Jarvis from the terminal. It should feel like the Iron Man Jarvis or Siri.
- Jarvis runs in the background with no terminal window (a startup shortcut and a system tray icon).
- When I say the wake word "Jarvis", a window opens with a futuristic blue theme: an animated glowing orb that reacts while she listens and speaks, a chat area, and a microphone button.
- Build the face as a local HTML/CSS/JavaScript page shown in a desktop window with pywebview, and keep the Python code as the brain.
- Keep typing as a fallback. She can hide the window when I say "Jarvis, close".
- Keep RAM use low. Tell me honestly if something is too heavy for my PC (15.7 GB RAM).

## Personal memory file
- Jarvis must read C:\jarvis\about_me.md every time she starts and include it in her system prompt, so she knows who I am. Use it when writing job applications, cover letters, emails and messages. If the file is missing, she should still work normally.
- When I say "remember [fact]", add it to a section called "Things Jarvis remembered" in about_me.md.
- Never store passwords, OTPs, bank details or ID numbers in this file.

## Personal memory file
- Jarvis must read C:\jarvis\about_me.md every time she starts and include it in her system prompt, so she knows who I am. Use it when writing job applications, cover letters, emails and messages. If the file is missing, she should still work normally.
- When I say "remember [fact]", add it to a section called "Things Jarvis remembered" in about_me.md.
- Never store passwords, OTPs, bank details or ID numbers in this file.

## Online accounts and overnight work (safe version only)
- Gmail and Google Calendar: use the official Google APIs with OAuth. Request the smallest permissions (Gmail read-only plus create drafts, no send, no delete). Keep credentials and tokens in a private folder and never in code.
- WhatsApp, LinkedIn, Indeed, Naukri: do NOT automate logins, clicking, applying or messaging, because it breaks their rules and risks account bans. Instead open the right page or search, with the text prepared, and let me press the final button.
- Overnight mode: Windows Task Scheduler runs Jarvis at a set time. She does read-only work (search new Flutter jobs in Kozhikode, Kochi and Kannur, summarize emails, draft cover letters and replies) and saves a morning report file. She never sends, applies or posts anything on her own.
- Build these as separate modules, after Stages 1 to 7 work.

## Clap wake-up
- Add an optional "double clap" wake-up as a light background listener using sounddevice (volume spike detection, two claps within about 1 second). It opens the Jarvis UI window, she says "Yes?", and then listens for my command.
- Make the loudness threshold and timing easy to adjust in a settings variable at the top of the file, and include a small test mode that prints the volume so I can tune it.
- Add an on/off switch for the clap listener (tray menu or UI toggle). It can work together with the "Jarvis" wake word.
- Build it after the mic-button voice input (Stage 2) works.

## Instagram and social media (safe version only)
- Do NOT automate logging in, posting, following, liking or sending DMs on Instagram or any social account, and never store my passwords. It breaks their rules and risks account bans.
- Jarvis can: open Instagram pages on command, write captions, hashtags, post ideas, reel scripts and reply drafts, and set posting reminders. I copy and post them myself.
- Optional later bonus: official Instagram Graph API posting, only if I switch to a Business or Creator account.

## Social profile shortcuts
- When I say "follow [username]" or "open [username] on instagram", open https://www.instagram.com/[username]/ in my browser and say "Opened [username]'s profile, tap Follow." Do not click Follow, log in, or control my account automatically.
- Support several usernames in one command (open each in its own tab).
- Put this in the apps/websites module, handled before the AI call, like "open chrome".

## Music: YouTube and Spotify
- When I say "play [song] on youtube" (or just "play [song]"), search YouTube, find the first matching video, and open it in my browser so it plays. Use a small free library (pywhatkit or yt-dlp). Say "Playing [song] on YouTube".
- When I say "play [song] on spotify", open the Spotify desktop app search using the spotify:search: link for that song, and say "Opened [song] in Spotify, press play." Do not log in for me or store my password.
- Optional later bonus: Spotify Web API auto-play (needs Spotify Premium, a developer app, OAuth, token in a private file).
- Handle these in the apps/websites module before the AI call, like "open chrome". If a song cannot be found, say so instead of crashing.

## Stage 9 (bonus): Spotify auto-play
- Build this only after Stages 1 to 8 work and the simple "open Spotify search" version works.
- Use the official Spotify Web API with the spotipy library and OAuth. I will create a free app on the Spotify developer dashboard and give the client ID and secret through a .env file. Never put them in code, and never ask me to paste them in a chat.
- This needs Spotify Premium and an open Spotify app on my PC. If I do not have Premium, tell me and keep the simple version.
- Commands: "play [song] on spotify" starts it automatically, plus "pause", "resume", "next song", "previous song" and "volume up/down".
- Keep the tokens in a private file that is never shared or uploaded.
- If Spotify is not open or the API fails, fall back to opening the Spotify search link and say so.
