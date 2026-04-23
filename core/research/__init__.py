"""Research governance layer (Phase E).

Introduces candidate lifecycle tracking separate from the experimental
trial archive (`core/mining/rcm_archive.py`). Trials are immutable
experiment records; candidates are governance objects with a state
machine and revoke workflow.

See:
  - docs/20260424-prd_phase_e_execution.md
  - docs/20260424-prd_phase_e_governance_and_paper.md
  - docs/20260424-prd_layered_quant_architecture.md (lifecycle S0-S5)
"""
