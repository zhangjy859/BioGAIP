import subprocess
import threading
import time
import os
import signal


def run_shell_command(command, timeout=None):
    """
    Executes a shell command, prints stdout and stderr in real-time,
    and kills the process tree if timeout is exceeded.

    :param command: The shell command to execute (str).
    :param timeout: Optional timeout in seconds (int or float). If exceeded, kill the process tree.
    """
    # Start the process with shell=True, and set preexec_fn to create a new process group
    proc = subprocess.Popen(
        command,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        preexec_fn=os.setsid  # Create a new process group for killing the tree
    )

    # Threads to read and print stdout and stderr in real-time
    def read_stdout():
        for line in iter(proc.stdout.readline, ''):
            print(line, end='')

    def read_stderr():
        for line in iter(proc.stderr.readline, ''):
            print(line, end='')

    stdout_thread = threading.Thread(target=read_stdout)
    stderr_thread = threading.Thread(target=read_stderr)
    stdout_thread.start()
    stderr_thread.start()

    # Monitor for timeout
    start_time = time.time()
    while proc.poll() is None:
        if timeout is not None and time.time() - start_time > timeout:
            # Kill the entire process group
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            print("\nTimeout exceeded, process tree killed.")
            break
        time.sleep(0.1)

    # Wait for threads to finish
    stdout_thread.join()
    stderr_thread.join()

    # Wait for process to terminate
    proc.wait()

    return proc.returncode




if __name__ == '__main__':
    #unittest.main()
    run_shell_command("echo okay; sleep 1; echo error 1>&2; sleep 10; echo done", timeout=5)