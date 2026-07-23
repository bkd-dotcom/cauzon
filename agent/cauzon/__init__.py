"""Cauzon — a path-grounded root-cause agent for data incidents on DataHub.

Cauzon investigates a failing data-quality assertion / incident by walking
DataHub's lineage graph *upstream*, ranking candidate culprits, and — crucially —
returning a root cause only when it can back the claim with a *verifiable lineage
path* (the exact edges + the SQL transform that introduced the fault). It then
writes the incident dossier back to DataHub so the next person or agent inherits
    the knowledge.

Design is grounded in 2025-2026 top-venue work:
  - RCAFlow (AAAI 2026): hierarchical multi-agent root-cause planning.
  - RCRank (VLDB 2025): multimodal ranking of root causes.
  - PAVE / OpenRCA 2.0: the "ungrounded diagnosis" problem — a correct cause with
    an unverified path is not acceptable. Cauzon rejects unprovable hypotheses.
  - DeepRoot (ICML 2026): separate *grounding* from *reasoning* to cut hallucination.
"""

__version__ = "0.1.0"
