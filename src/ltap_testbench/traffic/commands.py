import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class CommandResult:
    argv: list[str]
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False


def run_command(
    argv: list[str],
    timeout_seconds: float | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> CommandResult:
    if should_cancel is not None:
        proc = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        deadline = time.monotonic() + timeout_seconds if timeout_seconds is not None else None
        while proc.poll() is None:
            if should_cancel():
                proc.terminate()
                try:
                    stdout, stderr = proc.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    stdout, stderr = proc.communicate()
                return CommandResult(
                    argv=argv,
                    exit_code=130,
                    stdout=stdout,
                    stderr=(stderr or "") + "\ncancelled\n",
                )
            if deadline is not None and time.monotonic() >= deadline:
                proc.kill()
                stdout, stderr = proc.communicate()
                return CommandResult(
                    argv=argv,
                    exit_code=124,
                    stdout=stdout,
                    stderr=stderr,
                    timed_out=True,
                )
            time.sleep(0.1)
        stdout, stderr = proc.communicate()
        return CommandResult(argv=argv, exit_code=proc.returncode, stdout=stdout, stderr=stderr)
    try:
        completed = subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        return CommandResult(
            argv=argv,
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            argv=argv,
            exit_code=124,
            stdout=exc.stdout if isinstance(exc.stdout, str) else "",
            stderr=exc.stderr if isinstance(exc.stderr, str) else "",
            timed_out=True,
        )
