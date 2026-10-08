"""Keep existing spec CLI backwards compatible; add autonomous task commands."""
import sys
from . import specs

def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    index=0
    if args and args[0]=='--project': index=2
    elif args and args[0].startswith('--project='): index=1
    if len(args)>index and args[index]=='task':
        from .runtime import main as task_main
        return task_main(args)
    return specs.main(args)
