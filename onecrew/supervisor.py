"""Legacy process API, using the identical shared Windows implementation."""
from .process_core import (
    native_python, validate_executable, kernel, identity, probe,
    BasicLimit, ExtendedLimit, Accounting, Job, Supervisor,
)
