from agents import ModelSettings
from agency_swarm import Agent, WebSearchTool, ImageGenerationTool, ImageGeneration
from agency_swarm.tools import PersistentShellTool
from openai.types.shared import Reasoning

from agents import ApplyPatchTool, apply_diff
from agents.editor import ApplyPatchOperation, ApplyPatchResult
from agents import ShellCommandRequest, ShellCommandOutput, ShellResult, ShellCallOutcome, ShellTool
from .tools.UpdatePlanTool import UpdatePlan
import hashlib
import os
from pathlib import Path
import asyncio

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


workspace_path = Path("./mnt").resolve()
approvals = ApprovalTracker()
editor = WorkspaceEditor(workspace_path, approvals, auto_approve=True)
apply_patch_tool = ApplyPatchTool(editor=editor)

coding_agent = Agent(
    name="CodingAgent",
    description="A gpt-5.1-based coding assistant template with no tools or instructions configured.",
    instructions="./instructions.md",
    model="gpt-5.1-codex",
    tools=[apply_patch_tool, WebSearchTool(), PersistentShellTool, UpdatePlan],
    model_settings=ModelSettings(
        reasoning=Reasoning(
            effort="medium",
            summary="auto",
        ),
    ),
)


