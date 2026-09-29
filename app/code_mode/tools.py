"""Anthropic tool-use schemas for Code mode.

list_files and read_file are read-only and dispatched immediately from run_read_only_tool.
write_file and ask_questions are intentionally NOT dispatched here — session.py always
intercepts them: write_file routes through the diff/approval flow before anything touches
disk, and ask_questions pauses the loop until the user answers via the UI.
"""

TOOLS = [
    {
        "name": "list_files",
        "description": "List files and directories under a relative path inside the project folder.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative directory path, '.' for the project root.",
                },
            },
        },
    },
    {
        "name": "read_file",
        "description": "Read the text contents of a file at a relative path inside the project folder.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative file path."},
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": (
            "Propose writing full new contents to a file at a relative path inside the "
            "project folder. This does not write immediately — the user reviews a diff "
            "and approves or rejects it before anything is saved."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative file path."},
                "content": {"type": "string", "description": "Full new file contents."},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "ask_questions",
        "description": (
            "Ask the user one or more multiple-choice questions before proceeding, when a "
            "decision only they can make is blocking the task (which approach to take, which "
            "file/feature to target, a naming or scope choice, an ambiguous requirement). Do "
            "NOT use this to ask permission to write a file — that is handled automatically by "
            "the write_file approval flow. Batch related questions into one call when possible; "
            "call the tool again later in the same task if a follow-up question comes up. The "
            "user can also type a free-form answer instead of picking a listed option."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "questions": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 4,
                    "items": {
                        "type": "object",
                        "properties": {
                            "question": {"type": "string", "description": "The question to ask."},
                            "options": {
                                "type": "array",
                                "minItems": 2,
                                "maxItems": 4,
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "label": {"type": "string"},
                                        "description": {
                                            "type": "string",
                                            "description": "Optional one-line clarification of this option.",
                                        },
                                    },
                                    "required": ["label"],
                                },
                            },
                            "multiSelect": {
                                "type": "boolean",
                                "description": "True if more than one option may be selected.",
                            },
                        },
                        "required": ["question", "options"],
                    },
                },
            },
            "required": ["questions"],
        },
    },
]


def run_read_only_tool(sandbox, name: str, tool_input: dict) -> str:
    """Executes list_files/read_file immediately. Raises ValueError for anything else —
    callers must intercept write_file themselves before reaching this function."""
    if name == "list_files":
        entries = sandbox.list_files(tool_input.get("path", "."))
        return "\n".join(entries) if entries else "(empty directory)"
    if name == "read_file":
        return sandbox.read_file(tool_input["path"])
    raise ValueError(f"'{name}' is not a read-only tool")
