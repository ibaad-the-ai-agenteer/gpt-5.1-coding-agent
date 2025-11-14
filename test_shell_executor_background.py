import asyncio
import os
from pathlib import Path

from agents import ShellActionRequest, ShellCallData, ShellCommandRequest

from coding_agent.coding_agent import ShellExecutor


async def run_background_process_test() -> None:
    """
    Simple executable test to verify that long-running shell commands are not killed
    when they exceed their timeout and instead continue running in the background.
    """
    workspace_dir = Path("./mnt").resolve()
    workspace_dir.mkdir(parents=True, exist_ok=True)

    marker_file = workspace_dir / "shell_executor_background_marker.txt"

    # Clean up any previous runs
    if marker_file.exists():
        marker_file.unlink()

    # This command waits 2 seconds and then writes to the marker file.
    # We will use a much shorter timeout so that the shell executor times out
    # while the subprocess is still running. If the subprocess is not killed
    # on timeout, it should still create the file.
    command = (
        "python -c \"import time, pathlib; "
        f"time.sleep(2); pathlib.Path(r'{marker_file.as_posix()}').write_text('done')\""
    )

    action = ShellActionRequest(commands=[command], timeout_ms=500)
    call_data = ShellCallData(call_id="test_background", action=action)
    request = ShellCommandRequest(ctx_wrapper=None, data=call_data)  # type: ignore[arg-type]

    # Ensure background mode is enabled for this test so that the process keeps
    # running after the timeout fires.
    previous_background_setting = os.environ.get("CODING_AGENT_SHELL_BACKGROUND_ON_TIMEOUT")
    os.environ["CODING_AGENT_SHELL_BACKGROUND_ON_TIMEOUT"] = "1"
    try:
        executor = ShellExecutor(cwd=workspace_dir)

        # Run the shell executor – this should return after ~0.5s due to timeout.
        await executor(request)
    finally:
        if previous_background_setting is None:
            os.environ.pop("CODING_AGENT_SHELL_BACKGROUND_ON_TIMEOUT", None)
        else:
            os.environ["CODING_AGENT_SHELL_BACKGROUND_ON_TIMEOUT"] = previous_background_setting

    # Wait long enough for the background process (if still running) to finish
    # and write the marker file.
    await asyncio.sleep(3)

    if not marker_file.exists():
        print("Background process test FAILED: marker file was not created.")
        raise SystemExit(1)

    # Clean up and exit successfully
    marker_file.unlink(missing_ok=True)
    print("Background process test PASSED: marker file was created.")


if __name__ == "__main__":
    asyncio.run(run_background_process_test())


