"""Streamlit view modules.

Each module exposes a ``render(...)`` callable that takes the loaded
DataFrames and writes to the global Streamlit context. Splitting the
views per-file keeps individual pages reviewable and lets us add
per-view tests later without touching the app shell.
"""
