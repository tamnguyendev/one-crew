"""The `onecrew` console script: forces UTF-8 on stdout/stderr, then runs the v2 router (onecrew.v2.cli.main).

On Windows a console script started without PYTHONUTF8 writes through cp1252 and died with UnicodeEncodeError on the
Vietnamese output (plan lint reasons, plan show, --help). Only the process's own stdout/stderr are reconfigured, once, at
start; nothing else (files, child processes) changes encoding. Under PYTHONUTF8=1 the streams are already UTF-8 and stay so."""
import sys


def force_utf8(*streams):
    """Make each text stream write UTF-8; a character a (non-UTF-8) stream cannot take is replaced instead of raising."""
    for stream in streams:
        reconfigure = getattr(stream, 'reconfigure', None)
        if reconfigure is None: continue
        try: reconfigure(encoding='utf-8', errors='replace')
        except (ValueError, OSError): pass       # detached or closed stream: leave it as it is


def main(argv=None):
    force_utf8(sys.stdout, sys.stderr)
    from .v2.cli import main as v2_main
    return v2_main(argv)


if __name__ == '__main__':
    sys.exit(main())
