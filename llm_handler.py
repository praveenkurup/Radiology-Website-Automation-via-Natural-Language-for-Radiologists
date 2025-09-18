import json
import os
import platform
import subprocess
import threading
from dotenv import load_dotenv
from openai import OpenAI
from llm_command_parser import LLMCommandParser
import time
import itertools
import sys
from contextlib import contextmanager, redirect_stdout
from queue import Queue
import keyboard
import io


ERROR_THRESHOLD = 6
error_sound = "./sound effects/error.wav"
sucess_sound = "./sound effects/success.wav"
step_sucess_sound = "./sound effects/step_success.wav"

CURRENT_FULLSCREEN_SCAN = None


@contextmanager
def spinner(message="Processing", status_getter=None):
    stop_event = threading.Event()
    max_length = 100
    result_status = {"symbol": "✅"}

    def spin():
        truncated = (message[:max_length] + '...') if len(message) > max_length else message
        padding = ' ' * 20
        for symbol in itertools.cycle(['|', '/', '-', '\\']):
            if stop_event.is_set():
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
        f = io.StringIO()
        with redirect_stdout(f):
            yield
    finally:
        stop_event.set()
        thread.join()


# --- Load environment variables ---
load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# -- Config --
MODEL_NAME = os.getenv("MODEL")
BROWSER_START_URL = "https://app.supervisely.com/"
# BROWSER_START_URL = "https://app.supervisely.com/app/volumes/?datasetId=1059758&volumeId=358377319"
CHROME_USER_DATA = r"C:\Users\Praveen\Desktop\Work\voice_command_agent_for_radiologist_final_project\profile"

# --- Init ---
prompt_history = []
stop_requested = False  # Global flag to break loop


def build_prompt(prompt_history, command_history, url, page_data, user_request="", CURRENT_FULLSCREEN_SCAN=""):
    prompt = f"""
    You are a browser automation assistant. Your goal is to complete the **user's request** by returning one or more browser actions in the correct order.

    🧑‍💻 User's Request:
    {user_request}

    📓 Previous User Prompts:
    {json.dumps(prompt_history)}

    NOTE: link to supervisely is app.supervisely.com, you can select projects and datasets can by clicking the dataset name and start annotation by pressing the "annotate" after selecting the dataset. Don't press the three dots in dataset or projects

    VERY IMPORTANT INSTRUCTION:
    - Never send 2 or more actions until its to fill a input form and then press a button.
    - Always check command history and check if the action you are going to send is there or not, if yes and executed without errors, then don't send that action, either continue with the next action from user request or send done.

    ---
    🛠️ Available Actions:

    1. click  
    - Clicks an element on the page.  
    - Example: {{ "action": "click", "element_id": 42, "intend": "Click the submit button" }}

    2. fill  
    - Fills text into an input field.  
    - Example: {{ "action": "fill", "element_id": 17, "text": "user@example.com", "intend": "Fill in the email input" }}

    3. scroll  
    - Scrolls the page.  
    - Example: {{ "action": "scroll", "direction": "down", "pixels": 500, "intend": "Scroll down to find more content" }}

    4. wait  
    - Waits for a duration.  
    - Example: {{ "action": "wait", "seconds": 3, "intend": "Wait for animations or content to load" }}

    5. navigate  
    - Navigates browser history.  
    - Example: {{ "action": "navigate", "direction": "back", "intend": "Go back to the previous page" }}

    6. goto  
    - Navigates to a specific URL.  
    - Example: {{ "action": "goto", "url": "https://example.com/login", "intend": "Open the login page" }}

    7. press_enter  
    - Sends Enter key to an input.  
    - Example: {{ "action": "press_enter", "element_id": 19, "intend": "Submit the search form" }}

    8. move_slider  
    - Moves a labeled slider to the specified value.  
    - target_text is the scan name (e.g., "Axial", "Coronal", "Sagittal", etc).  
    - If the scan name is not mentioned in the user request, use the value of `Current Full Screen Scan` provided as context.  
    - target_value is the value the user mentioned (numerical).  
    - If the user says *increase* or *decrease*, interpret it as a relative change.  
        - Set **increment_mode = 1**  
        - Use a **positive target_value** for *increase*  
        - Use a **negative target_value** for *decrease*  
    - If the user says *go to* or *set to*, interpret it as an absolute value.  
        - Set **increment_mode = 0**  
        - target_value must always be **positive**  
    - slider_per_sec is how many slides should be shown per second.  
    - If not mentioned by the user, default to **1**
    - Send done if the same zoom command has been in the command_history and was sucessfully executed.

    - Examples:  
    - "Increase Sagittal scan slider by 20, slider per second 3" →  
        {{ "action": "move_slider", "target_text": "Sagittal", "target_value": 20, "increment_mode": 1, "slides_per_sec": 3, "intend": "Increase Sagittal slider by 20" }}

    - "Decrease Axial scan by 10" →  
        {{ "action": "move_slider", "target_text": "Axial", "target_value": -10, "increment_mode": 1, "slides_per_sec": 1, "intend": "Decrease Axial slider by 10" }}

    - "Go to 30 slides in Coronal scan" →  
        {{ "action": "move_slider", "target_text": "Coronal", "target_value": 30, "increment_mode": 0, "slides_per_sec": 1, "intend": "Set Coronal slider to 30" }}

    9. get_coordinates  
    - Gets the bounding box of a DOM element.  
    - Example: {{ "action": "get_coordinates", "element_id": 51, "intend": "Get canvas coordinates before zooming" }}

    10. zoom  
    - Zooms into a canvas element.  
    - Example: {{ "action": "zoom", "scan_name": "Axial", "target_zoom": 1.5, "direction": "bottom left", "intend": "Zoom into the axial canvas at top-left" }}
    - You must choose one of the 9 fixed directions: "top left", "top right", "bottom left", "bottom right", "center", "center top", "center bottom", "middle left", "middle right" using user request
    - When user say, bring back zoom to normal, or reset zoom, using center direction and sacle as 1.
    - If scan name isin't mentioned, use the scan name in Current Full Screen Scan given below

    11. enter_fullscreen  
    - Enters fullscreen using the scan name, Use this action whenever user asks to enter fullscreen any scan
    - Example: {{ "action": "enter_fullscreen", "scan_name": "Axias"}}

    12. done  
    - Signals task completion.  
    - Example: {{ "action": "done", "intend": "The requested task was successfully completed" }}

    ---
    ✅ IMPORTANT RULE:

    **Always use the `element_id` field from the DOM (in `page_data`) to refer to elements.**  
    Each element has a unique `element_id` corresponding to an internal CSS selector. Do not try to guess or generate selectors yourself.  

    When acting on a specific element:
    - Find the right element based on visible text, tag, or attributes.
    - Use its `element_id` when returning any action.

    If you cannot find a matching element:
    - Respond with "element not found" and do not run any action.

    ---
    📌 DOM Matching Requirements:

    - Use only `element_id` values from `page_data`.
    - Never guess or invent any selectors.
    - Each `element_id` corresponds internally to a real `_selector`.

    ---

    🧠 Contextual Knowledge (Use When Relevant):

    - The `i` tag with class `mdi-fullscreen-exit` is used to exit fullscreen mode.
    - If the user asks to zoom without specifying the scan (e.g. Axial, Coronal, Sagittal, Perspective):  
      - Use the `Current Full Screen Scan` value provided in context.  

    - If the user says something like "zoom a little bit more on coronal scan bottom right", check if a zoom action was already applied to that scan.  
      - If yes, apply additional zoom starting from the previously used scale.  

    - If the user asks to move the slider (increase / decrease / go to a slide) without specifying the scan:  
      - Use the `Current Full Screen Scan` as the target scan.

    - Try to avoid sending multiple actions as much as possible.. ONLY and ONLY use it for filling up inputs and pressing submit.

    - If user says select a specfic volume, go through the div with class list-wrapper, use the idx of it children to select the user said one

    - All normal scan names are Axial, Sagittal and Coronal. To fix if there is a typo or issue in trasncribtion of scan name.

     When the user instructs to fill input fields like email, username, or password, interpret the spoken command contextually rather than literally, as the input may come from voice-to-text transcription and may include verbal representations or formatting issues.

        Follow these rules:

        📧 For emails and usernames:
        Remove unnecessary spaces unless the user explicitly says “space”.

        Replace phrases like:

        "at the rate", "at the right" → @

        "hyphen -" -> "" nothing

        "dot" → .

        "underscore" → _

        For example:

        "praveen k at the rate gmail dot com" → "praveenk@gmail.com"

        🔐 For passwords:
        Remove all spaces by default unless the user explicitly says a space is required.

        Treat alphabetic characters as lowercase unless the user says no matter if its caps or lower case in prompt:

        “caps” / “capital” / “uppercase” → Next letter is uppercase.

        “all caps” / “everything caps” → All following characters are uppercase until stated otherwise.

        Convert spoken phrases to symbols/numbers:

        “exclamation mark” → !

        “dollar” → $

        “hash” → #

        “one two three” → 123, etc.

        Ignore filler phrases like “with password”, “the password is”, etc.

        Examples:

        "password as M E G caps I L N 3" → "MEGiln3"

        "and with password all caps LLMS 123 exclamation mark" → "LLMS123!"

        Use your understanding of spoken English patterns and correct formatting to infer the intended input accurately.

    ---
    🌐 Current Page URL:
    {url}

    📜 Command History (latest last):
    {json.dumps(command_history)}

    🧩 DOM Snapshot:
    {page_data}

    Current Full Screen Scan: {CURRENT_FULLSCREEN_SCAN}

    ---
    Before you respond:

    1. Check if any matching `click`, `move_slider`, `zoom`, etc. already completed the request
    2. Only return new actions if they are clearly needed
    3. Otherwise, return:
    {{ "action": "done", "intend": "All steps from the user request were already completed" }}


    ⛔ Do NOT wrap your output in markdown. Return a raw JSON **list** of action objects.

    Now return the next action(s) to perform.
    """
    return prompt



def query_llm(prompt):
    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {
                "role": "system",
                "content": (
                    "You control a web browser using JSON commands. Do not use natural language.\n"
                    'If the task appears to be completed already based on the DOM or last command result, return { "action": "done" } immediately. '
                    "Only take actions if you are confident they are still necessary."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0,
    )
    return response.choices[0].message.content.strip()

stop_requested = False

def stop_task():
    global stop_requested
    stop_requested = True
    print("\n⏹️ Stop requested via ESC key.\n")

    
def _play_sound(sound_file):
    if platform.system() == "Windows":
        subprocess.Popen(['ffplay', '-nodisp', '-autoexit', '-loglevel', 'quiet', sound_file])
    else:
        subprocess.Popen(['afplay', sound_file])  # macOS


def main(main_queue: Queue):
    global stop_requested, CURRENT_FULLSCREEN_SCAN
    
    keyboard.add_hotkey("esc", stop_task)
    task_queue = main_queue
    agent = LLMCommandParser(url=BROWSER_START_URL, usr_dir=CHROME_USER_DATA)
    error_counter = 0

    # --- Main Loop ---
    try:
        while True:
                print("Standby for command, Press Ctrl + Alt + F to start recording...")
                task = task_queue.get()

                if task.lower() == "exit":
                    agent.driver.quit()
                    break

                print(f"\n🚀 Starting task: {task}")
                done = False
                stop_requested = False
                command_history = []
                prompt_history.append(task)

                while not done:
                    if stop_requested:
                        print("⏹️ Task interrupted by hotkey.")
                        break
                        
                    if error_counter >= ERROR_THRESHOLD:
                        print("Consecutive errors exceeded threshold, stopping task!")
                        break


                    current_html = agent.driver.page_source
                    dom_data = agent.page_source_parser(current_html)

                    prompt = build_prompt(
                        prompt_history=prompt_history,
                        command_history=command_history,
                        url=agent.driver.current_url,
                        page_data=dom_data,
                        user_request=task,
                    )

                    llm_output = (
                        query_llm(prompt).strip().replace("```json", "").replace("```", "")
                    )

                    # print("\n\nLLM OUTPUT!", llm_output, "\n\n")
                    try:
                        actions = json.loads(llm_output)
                        if not isinstance(actions, list):
                            actions = [actions]
                    except Exception as e:
                        print(f"\n❌ Failed to parse LLM output: {e}")
                        print(f"🧾 Raw output:\n{llm_output}")
                        break

                    for action in actions:
                        if action.get("action", "").lower() == "done":
                            done = True
                            break

                        if action.get("action", "").lower() == "enter_fullscreen":
                            CURRENT_FULLSCREEN_SCAN = action.get("scan_name", "")

                        result_container = {"result": ""}

                        def get_status():
                            return result_container["result"]

                        with spinner(
                            f"🤖 Executing: {action.get('intend', action['action'])} {"Press p to stop slider" if action.get('action', action['action']) == "move_slider" else ""}",
                            status_getter=get_status,
                        ):
                            try:
                                result = agent.parse_and_execute(
                                    json.dumps(action)
                                )
                                print(f"\nResults is {result}")
                            except Exception as e:
                                print("Some error happened!")
                                result = "Error occurred while trying to execute command"
                                print(f"\nResults is {result}, {e}")
                            result_container["result"] = result or ""


                        command_history.append({"command": action, "result": result})

                        if "Error occurred while trying to execute command".lower() in result.lower():
                            _play_sound(error_sound)
                            error_counter += 1
                        else:
                            _play_sound(step_sucess_sound)
                            error_counter = 0

                    time.sleep(1.2)

                if error_counter < ERROR_THRESHOLD and not stop_requested:
                    _play_sound(sucess_sound)
                    print(f"✅ {task} — Task Completed!\n")
                error_counter = 0

    except KeyboardInterrupt:
        print("\n👋 Exiting automation.")

    finally:
        agent.close()
