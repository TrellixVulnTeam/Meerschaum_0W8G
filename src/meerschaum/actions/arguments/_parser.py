#! /usr/bin/env python
# -*- coding: utf-8 -*-
# vim:fenc=utf-8

"""
This module creates the argparse Parser
"""

import argparse
from meerschaum.config import __doc__ as doc

parser = argparse.ArgumentParser(
    description="Meerschaum actions parser",
    usage="mrsm [action]"
)

parser.add_argument(
    'action', nargs='+', help="Action to execute"
)
parser.add_argument(
    '--debug', '-d', help="Print debug statements (max verbosity)"
)
parser.add_argument(
    '--version', '-V', action="version", version=doc
)
parser.add_argument(
    '--pretty', '-p', action="store_true", help="Pretty print the output (where supported)"
)
