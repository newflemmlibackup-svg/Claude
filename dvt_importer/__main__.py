import sys

if "--selftest" in sys.argv:
    from .selftest import run

    sys.exit(run())

from .gui import main

main()
