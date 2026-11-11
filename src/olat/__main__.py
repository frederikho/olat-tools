"""python -m olat <command> (with PYTHONPATH=src, or after `pip install -e .`)."""
import sys

from .cli import main

sys.exit(main())
