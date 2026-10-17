"""PromLab: a fabricated Kubernetes fleet as Prometheus data, and a PromQL server over it.

`python -m sdlab.promlab.generate` simulates the fleet and writes the series;
`python -m sdlab.promlab.server` answers the Prometheus HTTP API over them.
"""
