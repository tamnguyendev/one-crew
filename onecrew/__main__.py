import sys

from .console import force_utf8

force_utf8(sys.stdout, sys.stderr)
from .cli import main

raise SystemExit(main())
