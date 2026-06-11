"""Staged import sessions (issue #207, ADR-0037).

Everything write-related in the API lives in this subpackage; the
modules outside it stay read-only (ADR-0035). See ADR-0037 for the
architecture: upload -> detect -> parse -> staged rows -> review ->
commit through the existing loaders.
"""
