from agents import ModelSettings
from agency_swarm import Agent, WebSearchTool
from openai.types.shared import Reasoning

from agents import ApplyPatchTool, apply_diff
from agents.editor import ApplyPatchOperation, ApplyPatchResult
from agents import ShellCommandRequest, ShellCommandOutput, ShellResult, ShellCallOutcome, ShellTool
import hashlib
import os
from pathlib import Path
import asyncio
import re

class ApprovalTracker:
    def __init__(self) -> None:
        self._approved: set[str] = set()

    def fingerprint(self, operation: ApplyPatchOperation, relative_path: str) -> str:
        hasher = hashlib.sha256()
        hasher.update(operation.type.encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(relative_path.encode("utf-8"))
        hasher.update(b"\0")
        hasher.update((operation.diff or "").encode("utf-8"))
        return hasher.hexdigest()

    def remember(self, fingerprint: str) -> None:
        self._approved.add(fingerprint)

    def is_approved(self, fingerprint: str) -> bool:
        return fingerprint in self._approved


class WorkspaceEditor:
    def __init__(self, root: Path, approvals: ApprovalTracker, auto_approve: bool) -> None:
        self._root = root.resolve()
        self._approvals = approvals
        self._auto_approve = auto_approve or os.environ.get("APPLY_PATCH_AUTO_APPROVE") == "1"

    def create_file(self, operation: ApplyPatchOperation) -> ApplyPatchResult:
        relative = self._relative_path(operation.path)
        self._require_approval(operation, relative)
        target = self._resolve(operation.path, ensure_parent=True)
        diff = operation.diff or ""
        content = apply_diff("", diff, mode="create")
        target.write_text(content, encoding="utf-8")
        return ApplyPatchResult(output=f"Created {relative}")

    def update_file(self, operation: ApplyPatchOperation) -> ApplyPatchResult:
        relative = self._relative_path(operation.path)
        self._require_approval(operation, relative)
        target = self._resolve(operation.path)
        original = target.read_text(encoding="utf-8")
        diff = operation.diff or ""
        patched = apply_diff(original, diff)
        target.write_text(patched, encoding="utf-8")
        return ApplyPatchResult(output=f"Updated {relative}")

    def delete_file(self, operation: ApplyPatchOperation) -> ApplyPatchResult:
        relative = self._relative_path(operation.path)
        self._require_approval(operation, relative)
        target = self._resolve(operation.path)
        target.unlink(missing_ok=True)
        return ApplyPatchResult(output=f"Deleted {relative}")

    def _relative_path(self, value: str) -> str:
        resolved = self._resolve(value)
        return resolved.relative_to(self._root).as_posix()

    def _resolve(self, relative: str, ensure_parent: bool = False) -> Path:
        candidate = Path(relative)
        target = candidate if candidate.is_absolute() else (self._root / candidate)
        target = target.resolve()
        try:
            target.relative_to(self._root)
        except ValueError:
            raise RuntimeError(f"Operation outside workspace: {relative}") from None
        if ensure_parent:
            target.parent.mkdir(parents=True, exist_ok=True)
        return target

    def _require_approval(self, operation: ApplyPatchOperation, display_path: str) -> None:
        fingerprint = self._approvals.fingerprint(operation, display_path)
        if self._auto_approve or self._approvals.is_approved(fingerprint):
            self._approvals.remember(fingerprint)
            return

        print("\n[apply_patch] approval required")
        print(f"- type: {operation.type}")
        print(f"- path: {display_path}")
        if operation.diff:
            preview = operation.diff if len(operation.diff) < 400 else f"{operation.diff[:400]}…"
            print("- diff preview:\n", preview)
        answer = input("Proceed? [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            raise RuntimeError("Apply patch operation rejected by user.")
        self._approvals.remember(fingerprint)


class ShellExecutor:
    """Executes shell commands with optional approval."""

    def __init__(
        self,
        cwd: Path | None = None,
        default_timeout: float | None = None,
        background_on_timeout: bool | None = None,
        env_overrides: dict[str, str] | None = None,
        force_non_interactive: bool | None = None,
        react_compiler_preference: str | None = None,
    ):
        self.cwd = Path(cwd or Path.cwd())
        if default_timeout is None:
            env_timeout = os.environ.get("CODING_AGENT_SHELL_TIMEOUT_SECONDS")
            if env_timeout:
                try:
                    default_timeout = float(env_timeout)
                except ValueError:
                    default_timeout = None
        self.default_timeout = default_timeout

        if background_on_timeout is None:
            background_on_timeout = (
                os.environ.get("CODING_AGENT_SHELL_BACKGROUND_ON_TIMEOUT", "0") == "1"
            )
        self.background_on_timeout = background_on_timeout
        self.env_overrides = env_overrides.copy() if env_overrides else {}

        if force_non_interactive is None:
            force_non_interactive = (
                os.environ.get("CODING_AGENT_SHELL_FORCE_NON_INTERACTIVE", "1") == "1"
            )
        self.force_non_interactive = force_non_interactive

        if react_compiler_preference is None:
            react_compiler_preference = os.environ.get(
                "CODING_AGENT_SHELL_REACT_COMPILER", "no"
            )
        react_compiler_preference = react_compiler_preference.strip().lower()
        if react_compiler_preference not in {"use", "no"}:
            react_compiler_preference = "no"
        self.react_compiler_preference = react_compiler_preference

        if self.force_non_interactive:
            # Encourage common CLIs (npm, npx, yarn, pnpm, etc.) to auto-select defaults and
            # skip prompts by setting environment variables they respect.
            self.env_overrides.setdefault("CI", "1")
            self.env_overrides.setdefault("npm_config_yes", "true")
            self.env_overrides.setdefault("NPX_YES", "1")
            self.env_overrides.setdefault("HUSKY_SKIP_HOOKS", "1")
            self.env_overrides.setdefault("YARN_ENABLE_IMMUTABLE_INSTALLS", "false")
            self.env_overrides.setdefault("SKIP_PROMPTS", "1")

    async def __call__(self, request: ShellCommandRequest) -> ShellResult:
        action = request.data.action

        outputs: list[ShellCommandOutput] = []
        for command in action.commands:
            env = os.environ.copy()
            env.update(self.env_overrides)
            prepared_command = self._prepare_command(command)

            if self._requires_background(prepared_command) and not self._is_backgrounded(
                prepared_command
            ):
                message = (
                    "Command appears to start a long-running dev server or watcher. "
                    "Always run such commands in the background by appending ' &' (for example "
                    "'npm run dev &' or 'uvicorn app:app --reload &')."
                )
                outputs.append(
                    ShellCommandOutput(
                        command=prepared_command,
                        stdout="",
                        stderr=message,
                        outcome=ShellCallOutcome(type="exit", exit_code=1),
                    )
                )
                continue

            proc = await asyncio.create_subprocess_shell(
                prepared_command,
                cwd=self.cwd,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            timed_out = False
            timeout = None
            if action.timeout_ms is not None:
                timeout = max(action.timeout_ms / 1000, 0)
            elif self.default_timeout is not None:
                timeout = self.default_timeout

            try:
                # Wait for the subprocess to finish, respecting either the per-call timeout
                # or the optional default timeout configured via environment variables.
                # A timeout of None means the call can run indefinitely.
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                timed_out = True
                if self.background_on_timeout:
                    # Leave the process running in the background. We won't wait for any
                    # more output here; instead, report that the command is still running.
                    stdout_bytes = b""
                    stderr_bytes = (
                        f"Command exceeded timeout of {timeout} seconds and is still running "
                        f"in the background (pid={proc.pid})."
                    ).encode("utf-8")
                else:
                    proc.kill()
                    stdout_bytes, stderr_bytes = await proc.communicate()
                    message = (
                        f"Command exceeded timeout of {timeout} seconds and was terminated "
                        f"(pid={proc.pid})."
                    )
                    stderr_bytes = f"{message}\n{stderr_bytes.decode('utf-8', errors='ignore')}".encode(
                        "utf-8"
                    )

            stdout = stdout_bytes.decode("utf-8", errors="ignore")
            stderr = stderr_bytes.decode("utf-8", errors="ignore")
            outputs.append(
                ShellCommandOutput(
                    command=prepared_command,
                    stdout=stdout,
                    stderr=stderr,
                    outcome=ShellCallOutcome(
                        type="timeout" if timed_out else "exit",
                        exit_code=getattr(proc, "returncode", None),
                    ),
                )
            )

            if timed_out:
                break

        return ShellResult(
            output=outputs,
            provider_data={"working_directory": str(self.cwd)},
        )

    _YES_FLAG_PATTERNS = (
        r"\bnpm\s+init\b",
        r"\bnpm\s+create\b",
        r"\bnpx\s+[^ ]*create",
        r"\byarn\s+create\b",
        r"\bpnpm\s+create\b",
    )
    _DEV_SERVER_PATTERNS = (
        r"\bnpm\s+run\s+(dev|start|preview|serve|storybook)\b",
        r"\bnpm\s+run\s+.*(--watch|--serve)\b",
        r"\bnpx\s+next\s+dev\b",
        r"\bnext\s+dev\b",
        r"\bvite\s+dev\b",
        r"\bnpx\s+vite\s+dev\b",
        r"\bpnpm\s+(dev|preview|start|serve)\b",
        r"\byarn\s+(dev|start|preview|serve|storybook)\b",
        r"\bnpx\s+astro\s+dev\b",
        r"\bnpx\s+remix\s+dev\b",
        r"\bnpx\s+expo\b",
        r"\bexpo\s+start\b",
        r"\buvicorn\b.+(--reload|--workers)",
        r"\bflask\s+run\b",
        r"\bdjango-admin\s+runserver\b",
        r"\bpython\s+-m\s+http\.server\b",
        r"\bnuxi\s+dev\b",
        r"\bnpx\s+nuxt\s+dev\b",
    )

    def _append_flag(self, command: str, flag: str) -> str:
        if " -- " in command:
            return command.replace(" -- ", f" {flag} -- ", 1)
        return f"{command} {flag}"

    def _has_yes_flag(self, command_lower: str) -> bool:
        return " --yes" in command_lower or " -y" in command_lower

    def _prepare_command(self, command: str) -> str:
        prepared = command.strip()
        lower = prepared.lower()

        if self.force_non_interactive:
            if not self._has_yes_flag(lower):
                for pattern in self._YES_FLAG_PATTERNS:
                    if re.search(pattern, lower):
                        prepared = self._append_flag(prepared, "--yes")
                        lower = prepared.lower()
                        break

            if "create-next-app" in lower and "--use-react-compiler" not in lower and "--no-use-react-compiler" not in lower:
                compiler_flag = (
                    "--use-react-compiler" if self.react_compiler_preference == "use" else "--no-use-react-compiler"
                )
                prepared = self._append_flag(prepared, compiler_flag)

        return prepared

    def _requires_background(self, command: str) -> bool:
        normalized = command.strip().lower()
        for pattern in self._DEV_SERVER_PATTERNS:
            if re.search(pattern, normalized):
                return True
        return False

    def _is_backgrounded(self, command: str) -> bool:
        stripped = command.rstrip()
        if stripped.endswith("&"):
            return True
        if "nohup " in stripped and "&" in stripped:
            return True
        return False


workspace_path = Path("./mnt").resolve()
approvals = ApprovalTracker()
editor = WorkspaceEditor(workspace_path, approvals, auto_approve=True)
tool = ApplyPatchTool(editor=editor)
shell_tool = ShellTool(executor=ShellExecutor(cwd=workspace_path))

coding_agent = Agent(
    name="CodingAgent",
    description="A gpt-5.1-based coding assistant template with no tools or instructions configured.",
    instructions="./instructions.md",
    tools_folder="./tools",
    model="gpt-5.1-codex",
    tools=[tool, shell_tool, WebSearchTool()],
    model_settings=ModelSettings(
        reasoning=Reasoning(
            effort="medium",
            summary="auto",
        ),
    ),
)


