import os
import subprocess
import sys
import tempfile
from pathlib import Path


OUTPUT_LIMIT_BYTES = 16_384


def _read_output(file_path: Path) -> str:
    with file_path.open("rb") as output_file:
        content = output_file.read(OUTPUT_LIMIT_BYTES + 1)
    truncated = len(content) > OUTPUT_LIMIT_BYTES
    text = content[:OUTPUT_LIMIT_BYTES].decode("utf-8", errors="replace")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if truncated:
        text += "\n[Output truncated]"
    return text


def execute_python_code(code_string: str, timeout_seconds: float = 3.0) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="code-companion-") as working_directory:
        stdout_path = Path(working_directory) / "stdout.txt"
        stderr_path = Path(working_directory) / "stderr.txt"
        environment = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONIOENCODING": "utf-8",
        }
        timed_out = False
        with stdout_path.open("wb") as stdout_file, stderr_path.open("wb") as stderr_file:
            try:
                process = subprocess.Popen(
                    [sys.executable, "-I", "-S", "-c", code_string],
                    stdin=subprocess.DEVNULL,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    cwd=working_directory,
                    env=environment,
                    close_fds=True,
                )
                process.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                timed_out = True
                process.kill()
                process.wait()

        stdout = _read_output(stdout_path)
        stderr = _read_output(stderr_path)
        if timed_out:
            stderr = f"Execution timed out after {timeout_seconds:g} seconds."
        return {
            "success": not timed_out and process.returncode == 0,
            "stdout": stdout,
            "stderr": stderr,
        }
