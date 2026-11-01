"""The intended model (docs/proposals/intended-model.md): the **declared layer** of what the owner
intends (stocks, effects, targets, flows, machines with their envelope and opaque ``spec``, event
types, P5's attachments) and what a plugin or inference proposes, kept beside the discovered
model, and the **comparison** of the two.

It runs nothing (AGENTS.md rule 1): a declared machine is not started, a declared stock binds no
series, a declared flow changes no equation. Discovery never reads it (rule 7 as amended).

| module | what it is |
|---|---|
| ``store`` | ``IntendedStore``: the journal and the versions ``dN``, ``apply``, ``read`` (``ModelStore.intended()``) |
| ``checks`` | ids, the machine envelope, provenance, derived fields refused |
| ``ops``, ``machine_ops``, ``revise`` | the ops of §6.3; revisions applied at once or kept pending, the owner's precedence |
| ``consent`` | whether an op has the owner's consent: the owner asks, or a plugin answers the owner's request |
| ``keys`` | a discovered part's key (§3.1) |
| ``history`` | suggestions, settling, came and went (§3.3) |
| ``diff`` | the structural diff of ``dN``, ``vM``, ``vK``, cached |
| ``facts``, ``expected``, ``view`` | the Dynamics page's block, with facts read under a time limit |
| ``params`` | the comparison's ``since`` and ``v``, parsed in one place |
| ``machines_view`` | the Machines page's ``intent``, ``comparison``, edges and types |
| ``names`` | the names in a machine's draft expected effect, resolved one way |
| ``drafts`` | whether an edit of a machine's draft expected effect can be published yet |
| ``requests`` | the owner's requests from the pages (``orchestra.intent.requested``) |
| ``announce`` | the host's ``orchestra.intent.changed`` |
| ``design`` | the plugin's summary |
"""

from .checks import IntentError
from .store import IntendedStore

__all__ = ["IntendedStore", "IntentError"]
