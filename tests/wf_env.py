"""Test-side environment helpers (not part of the historical R00 kit pins).

An installed scenario or an owner verb in a test stands for the OWNER's own terminal. When the test runner itself
runs inside an AI tool session (Claude Code sets CLAUDE_CODE_CHILD_SESSION for every subprocess), the markers would
leak into the scenario and the W03/C11 guards would rightly refuse owner verbs there. A test that models the owner's
terminal clears them for its duration; a test that wants the marker sets it explicitly.
"""
import os

AI_SESSION_MARKERS = ('CLAUDE_CODE_CHILD_SESSION', 'CLAUDECODE')


def owner_terminal(case):
    """Clear the AI-session markers for the rest of this test case and restore them afterwards."""
    saved = {name: os.environ.pop(name) for name in AI_SESSION_MARKERS if name in os.environ}
    def restore():
        for name, value in saved.items():
            os.environ[name] = value
    case.addCleanup(restore)
    return saved
