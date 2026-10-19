"""Canonical system dynamics models on the ladder (tag `canonical`): classic models imported through
PySD (sdlab/ladder/pysd_import.py) or written by hand as Vensim files (models/), and the coverage of
SDXorg/test-models by SD Lab's case format (coverage.py, docs/research/canonical-coverage.md).

read.py reads a model through PySD into sympy rates; match.py matches rates onto SD Lab's forms;
timefns.py evaluates outside drivers with PySD's semantics. pysd and sympy are optional packages:
nothing here is imported by the ladder itself.
"""
