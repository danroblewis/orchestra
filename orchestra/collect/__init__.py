"""Instruments: the collectors a project (``[[collect]]``, ``[[scrape]]`` in ``orchestra.toml``) or
a plugin (``Plugin.collectors``) declares, run by the host that launches.

An instrument measures the running system and never acts on it, so it is not a machine (AGENTS.md
rule 7): it is not announced on the bus and is not on the Machines page. A **script collector**
(``[[collect]]``) is a command the host runs on an interval; a **scrape** (``[[scrape]]``) is a URL
it reads on an interval. Either gives the Prometheus text exposition format (``exposition``),
which becomes points in the project's metrics store, labelled with the project and
``instrument = <name>`` (provenance), the target's own labels kept. Nothing needs to import
Orchestra: a shell script that prints two lines is an instrument. ``spec`` reads the entries,
``fetch`` gets the text, ``round`` turns it into points, ``runner`` keeps them on their intervals
and records their health in the runtime record (``instruments``).

The metrics store is filled by instruments directly. Orchestra's own count of the bus's events
(``orchestra.collectors``, ``orchestra_events_total``) is the one series derived from the event
log, and is secondary."""
