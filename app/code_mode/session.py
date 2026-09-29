"""Tool-use loop for Code mode.

Claude gets read/write tools scoped to one chosen folder via FolderSandbox. Reads
(list_files, read_file) execute immediately and feed straight back into the loop.
Two tools instead pause the loop and hand control back to the user:
  - write_file: returns a diff, resolved via resolve_write() (approve/reject).
  - ask_questions: returns one or more multiple-choice questions, resolved via
    resolve_questions() (the user's answers). Use this for a decision only the user
    can make — it's not a permission prompt, Claude asks it because it needs an answer.
Nothing happens on disk, and the loop doesn't continue, until the relevant resolve_*
call comes back from the UI.

One CodeSession represents one folder + one running task/tool-loop; the Api holds at
most one at a time (single-window app, matching Phase 1/2's single-session model).
"""

import difflib
import itertools

from app.claude_client import get_client
from app.code_mode.sandbox import FolderSandbox, SandboxViolation
from app.code_mode.tools import TOOLS, run_read_only_tool
from app.pricing import compute_cost

MAX_TOOL_ITERATIONS = 25
MAX_TOKENS = 4096

_write_id_counter = itertools.count(1)
_question_set_id_counter = itertools.count(1)


class CodeSession:
    def __init__(self, folder: str):
        self.sandbox = FolderSandbox(folder)
        self.folder = str(self.sandbox.root)
        self.messages: list[dict] = []
        self.model_id: str | None = None
        self.initial_prompt: str | None = None
        self.pending_writes: dict[int, dict] = {}  # write_id -> {tool_use_id, path, new_content, diff}
        self.pending_questions: dict[int, dict] = {}  # set_id -> {tool_use_id, questions: [...]}
        self._resolved_tool_results: list[dict] = []
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cost_usd = 0.0

    # ---- public API used by app/api.py -------------------------------------

    def start_task(self, prompt: str, model_id: str) -> dict:
        self.model_id = model_id
        self.initial_prompt = prompt
        self.messages.append({"role": "user", "content": prompt})
        return self._run_loop()

    def resolve_write(self, write_id: int, approve: bool) -> dict:
        pending = self.pending_writes.pop(write_id, None)
        if pending is None:
            raise KeyError(f"No pending write with id {write_id}")

        if approve:
            self.sandbox.write_file(pending["path"], pending["new_content"])
            result_text = f"Change to '{pending['path']}' was approved and written to disk."
        else:
            result_text = (
                f"Change to '{pending['path']}' was rejected by the user. "
                "Do not rewrite it unless explicitly asked again."
            )

        self._resolved_tool_results.append({
            "type": "tool_result",
            "tool_use_id": pending["tool_use_id"],
            "content": result_text,
        })
        return self._after_resolving_one()

    def resolve_questions(self, question_set_id: int, answers: list[str]) -> dict:
        pending = self.pending_questions.pop(question_set_id, None)
        if pending is None:
            raise KeyError(f"No pending question set with id {question_set_id}")

        parts = []
        for q, a in zip(pending["questions"], answers):
            parts.append(f"Q: {q['question']}\nA: {a}")
        result_text = "\n\n".join(parts) if parts else "(no answers provided)"

        self._resolved_tool_results.append({
            "type": "tool_result",
            "tool_use_id": pending["tool_use_id"],
            "content": result_text,
        })
        return self._after_resolving_one()

    # ---- internals ----------------------------------------------------------

    def _after_resolving_one(self) -> dict:
        """Shared tail for resolve_write/resolve_questions: if anything else from this
        turn is still awaiting input, stay paused; otherwise flush the accumulated
        tool_results back to Claude and resume the loop."""
        if self.pending_writes or self.pending_questions:
            return self._pending_input_result()

        self.messages.append({"role": "user", "content": self._resolved_tool_results})
        self._resolved_tool_results = []
        return self._run_loop()

    def _run_loop(self) -> dict:
        client = get_client()

        for _ in range(MAX_TOOL_ITERATIONS):
            response = client.messages.create(
                model=self.model_id,
                max_tokens=MAX_TOKENS,
                tools=TOOLS,
                messages=self.messages,
            )
            self._record_usage(response.usage)
            self.messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason != "tool_use":
                text = "".join(block.text for block in response.content if block.type == "text")
                return {"status": "final", "text": text, **self._usage_summary()}

            tool_results = []
            has_pending_input = False
            for block in response.content:
                if block.type != "tool_use":
                    continue
                try:
                    if block.name == "write_file":
                        self._queue_pending_write(block)
                        has_pending_input = True
                    elif block.name == "ask_questions":
                        self._queue_pending_questions(block)
                        has_pending_input = True
                    else:
                        output = run_read_only_tool(self.sandbox, block.name, block.input)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": output,
                        })
                except (SandboxViolation, FileNotFoundError, NotADirectoryError) as exc:
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": f"Error: {exc}",
                        "is_error": True,
                    })

            if has_pending_input:
                self._resolved_tool_results = tool_results
                return self._pending_input_result()

            self.messages.append({"role": "user", "content": tool_results})

        return {
            "status": "final",
            "text": "(stopped: too many tool-use iterations without finishing)",
            **self._usage_summary(),
        }

    def _queue_pending_write(self, block) -> None:
        path = block.input["path"]
        new_content = block.input["content"]
        old_content = self.sandbox.read_file_raw(path)  # may raise SandboxViolation
        diff = "\n".join(
            difflib.unified_diff(
                old_content.splitlines(),
                new_content.splitlines(),
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
                lineterm="",
            )
        ) or "(no textual diff — new file or identical content)"

        write_id = next(_write_id_counter)
        self.pending_writes[write_id] = {
            "tool_use_id": block.id,
            "path": path,
            "new_content": new_content,
            "diff": diff,
        }

    def _queue_pending_questions(self, block) -> None:
        questions = block.input.get("questions") or []
        set_id = next(_question_set_id_counter)
        self.pending_questions[set_id] = {
            "tool_use_id": block.id,
            "questions": questions,
        }

    def _pending_input_result(self) -> dict:
        return {
            "status": "pending_input",
            "pending_writes": [
                {"id": write_id, "path": p["path"], "diff": p["diff"]}
                for write_id, p in self.pending_writes.items()
            ],
            "pending_questions": [
                {"id": set_id, "questions": q["questions"]}
                for set_id, q in self.pending_questions.items()
            ],
            **self._usage_summary(),
        }

    def _record_usage(self, usage) -> None:
        self.total_input_tokens += usage.input_tokens
        self.total_output_tokens += usage.output_tokens
        self.total_cost_usd += compute_cost(self.model_id, usage.input_tokens, usage.output_tokens)

    def _usage_summary(self) -> dict:
        return {
            "model_used": self.model_id,
            "input_tokens": self.total_input_tokens,
            "output_tokens": self.total_output_tokens,
            "cost_usd": self.total_cost_usd,
        }
