import audio_handler
import llm_handler
from multiprocessing import Process, Queue


def main():
    print("Starting program")

    task_queue = Queue()

    llm = Process(target=llm_handler.main, args=(task_queue,))
    llm.start()

    audio_listner_instance = audio_handler.AudioHandler(task_queue)

    audio_listner_instance.listen_for_audio()

    llm.join()

if "__main__" == __name__:
    main()