from queue import Queue
import time
import keyboard
import itertools
import sys
from contextlib import contextmanager
import threading
import os
from datetime import datetime
import re
import platform
import subprocess

from Push2Type.audio_capture import (
    initialize_microphone,
    start_audio_capture,
    stop_and_flush_audio_capture,
    shutdown_audio,
)

from Push2Type.transcription import (
    load_model,
    process_audio_data,
    transcribe_audio,
)

@contextmanager
def spinner(message="Processing", status_getter=None):
    done = False
    max_length = 100
    result_status = {"symbol": "✅"}

    def spin():
        truncated = (message[:max_length] + '...') if len(message) > max_length else message
        padding = ' ' * 20
        for symbol in itertools.cycle(['|', '/', '-', '\\']):
            if done:
                break
            sys.stdout.write(f'\r{truncated} {symbol}{padding}')
            sys.stdout.flush()
            time.sleep(0.1)

        if status_getter:
            status = status_getter()
            if isinstance(status, str) and "error occurred" in status.lower():
                result_status["symbol"] = "❌"
        sys.stdout.write(f'\r{truncated} {result_status["symbol"]}{padding}\n')
        sys.stdout.flush()

    thread = threading.Thread(target=spin)
    thread.daemon = True
    thread.start()

    try:
        yield
    finally:
        done = True
        thread.join()

class AudioHandler:
    def __init__(self, task_queue: Queue):
        self.task_queue = task_queue
        self.is_recording = False
        self.logging_active = False
        self.log_file = None
        self.log_file_name = ""
        self.log_count = 0

        self.model = load_model("small.en", use_gpu=False)
        initialize_microphone()

        # Sound effects
        self.start_sound = "./sound effects/start.wav"
        self.stop_sound = "./sound effects/stop.wav"
        self.error_sound = "./sound effects/error.wav"
        self.sucess_sound = "./sound effects/success.wav"
        self.step_sucess_sound = "./sound effects/step_success.wav"

    def _play_sound(self, sound_file):
        if platform.system() == "Windows":
            subprocess.Popen(['ffplay', '-nodisp', '-autoexit', '-loglevel', 'quiet', sound_file])
        else:
            subprocess.Popen(['afplay', sound_file])  # macOS

    def _toggle_recording(self):
        if not self.is_recording:
            with spinner("🎧  Recording started..."):
                self._play_sound(self.start_sound)
                start_audio_capture()
                self.is_recording = True
        else:
            print("🛑  Recording stopped. Processing...")
            self._play_sound(self.stop_sound)
            audio_bytes = stop_and_flush_audio_capture()
            self.is_recording = False
            self._process_audio(audio_bytes)

    def _process_audio(self, audio_bytes):
        with spinner("Transcribing audio.. "):
            audio_array = process_audio_data(audio_bytes)
            text = transcribe_audio(audio_array, self.model)

        cleaned = re.sub(r'[^A-Za-z0-9]', '', text).lower().strip()

        if cleaned == "exit":
            self.task_queue.put("exit")
            self._exit_program()

        if not text.strip():
            print("No speech detected.\n")
            return

        print("📝 Transcribed:", text, "\n")
        self.task_queue.put(text)

    def _toggle_logging(self):
        if not self.logging_active:
            os.makedirs("./logs", exist_ok=True)
            if not self.log_file_name:
                timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                self.log_file_name = f"./logs/{timestamp}.txt"

            self.log_file = open(self.log_file_name, "a", encoding="utf-8")
            self.logging_active = True
            self.log_count = 0
            if os.path.exists(self.log_file_name):
                with open(self.log_file_name, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.strip() and line[0].isdigit():
                            try:
                                num = int(line.split()[0])
                                self.log_count = max(self.log_count, num)
                            except:
                                continue

            print(f"🟢 Logging started. Speak your log now.")
            self._play_sound(self.start_sound)
            start_audio_capture()
        else:
            print("🛑 Logging stopped. Transcribing and saving log...")
            self._play_sound(self.stop_sound)
            audio_bytes = stop_and_flush_audio_capture()
            self.logging_active = False

            with spinner("Transcribing your log entry..."):
                audio_array = process_audio_data(audio_bytes)
                text = transcribe_audio(audio_array, self.model)

            if not text.strip():
                print("⚠️  No speech detected. Nothing written to log.\n")
                return

            print("📝 Logged:", text.strip())

            self.log_count += 1
            timestamp = datetime.now().strftime("%H:%M:%S")
            formatted = f"{self.log_count} [{timestamp}] - {text.strip()}"
            if self.log_file:
                self.log_file.write(formatted + "\n")
                self.log_file.flush()

    def listen_for_audio(self):
        print("Press Ctrl + Alt + F to start/stop recording. Press Ctrl + Alt + G to toggle logging. Press ESC to exit.\n")
        keyboard.add_hotkey("ctrl+alt+f", self._toggle_recording)
        keyboard.add_hotkey("ctrl+alt+g", self._toggle_logging)

        while True:
            time.sleep(1)

    def _exit_program(self):
        print("Exiting...")
        with spinner("Shutting down audio interface... "):
            shutdown_audio()
        if self.log_file:
            self.log_file.close()
        exit()