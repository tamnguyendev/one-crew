"""Legacy artifact-provider API, backed by the shared protocol implementation."""
import json
import os
from pathlib import Path
import shutil
import subprocess

from .ledger import LedgerError, canonical
from .snapshots import durable_write
from .subscription import environment, CLAUDE_AUTH_ARGS, CODEX_AUTH_ARGS
from .artifact_provider_core import (
    executable, ExternalArtifact, ClaudeArtifact, KiroArtifact, CodexArtifact,
    KIRO_AGENT, KIRO_PROMPT_CAP, kiro_argv, kiro_stream, json_object, make_worker,
    Supervisor, doctor as _doctor,
)


def doctor(provider):
    # Preserve the legacy injectable executable probe; the protocol has one body.
    return _doctor(provider, executable_fn=executable)
