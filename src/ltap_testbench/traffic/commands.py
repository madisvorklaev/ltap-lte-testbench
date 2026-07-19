import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class CommandResult:
    argv: list[str]
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False


def run_command(argv: list[str], timeout_seconds: float | None = None) -> CommandResult:
    try:
        proc = subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        return CommandResult(
            argv=argv,
            exit_code=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
        )
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            argv=argv,
            exit_code=124,
            stdout=exc.stdout if isinstance(exc.stdout, str) else "",
            stderr=exc.stderr if isinstance(exc.stderr, str) else "",
            timed_out=True,
        )
