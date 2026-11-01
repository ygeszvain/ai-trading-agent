"""Advisory research layer: a local model, probed, budgeted, and evaluated.

Plan section 8. Nothing here can execute: research jobs run the local model
against point-in-time synthetic data, validate and sanitize its output, and
persist advisory records alongside the deterministic strategy's decisions.
"""

from .capability import GOLDEN_THRESHOLD, probe
from .evaluation import EvaluatedOutput, evaluate_output
from .jobs import JobSummary, job_id_for, run_job
from .model_client import (
    LocalModelClient,
    ModelBudgetError,
    ModelClientError,
    ModelResponse,
    ModelTimeoutError,
    ModelUnreachableError,
)
from .prompts import PROMPT_VERSIONS, ResearchBrief, build_prompt

__all__ = [
    "EvaluatedOutput",
    "GOLDEN_THRESHOLD",
    "JobSummary",
    "LocalModelClient",
    "ModelBudgetError",
    "ModelClientError",
    "ModelResponse",
    "ModelTimeoutError",
    "ModelUnreachableError",
    "PROMPT_VERSIONS",
    "ResearchBrief",
    "build_prompt",
    "evaluate_output",
    "job_id_for",
    "probe",
    "run_job",
]
