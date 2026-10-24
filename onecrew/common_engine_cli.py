"""Checkout native backend for the same public common workflow CLI."""
from .common_executor import NativeExecutor
from .common_handoff import handoff
from .common_verification import CandidateChecker
from .v2.engine_cli import main as engine_main


def main(argv=None):
    return engine_main(argv, native_executor=NativeExecutor, checker=CandidateChecker, handoff=handoff)
