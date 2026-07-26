# parser/__init__.py
"""
Parser module for Nala compiler.
"""

from parser.parser import Parser, ParseError, parse_source

__all__ = ["Parser", "ParseError", "parse_source"]
