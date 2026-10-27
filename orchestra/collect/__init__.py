"""Collectors a project declares in ``orchestra.toml``, run by the host that launches.

A **script collector** (``[[collect]]``) is a command the host runs on an interval; a **scrape**
(``[[scrape]]``) is a URL it reads on an interval. Either gives the Prometheus text exposition
format (``exposition``), which becomes points in the project's metrics store, labelled with the
project and ``machine = <name>``. Nothing needs to import Orchestra: a shell script that prints
two lines is a collector. ``spec`` reads the entries, ``fetch`` gets the text, ``round`` turns it
into points, ``runner`` keeps them on their intervals.

Orchestra's own event counter is another thing: ``orchestra.collectors``."""
