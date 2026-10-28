"""Instruments shipped with Orchestra for any repository to run under ``[[collect]]``.

Each is one file that imports nothing from Orchestra (the standard library only), so it runs as
``python -m orchestra.instruments.<name>`` where Orchestra is installed, or copied into a
repository and run as a script. Orchestra's core never imports them: they are measurements a
repository chooses, like a script of its own (USING_ORCHESTRA.md section 3)."""
