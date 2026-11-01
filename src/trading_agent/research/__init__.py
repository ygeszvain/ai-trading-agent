"""Advisory research layer: a local model, probed, budgeted, and evaluated.

Plan section 8. Nothing here can execute: research jobs run the local model
against point-in-time synthetic data, validate and sanitize its output, and
persist advisory records alongside the deterministic strategy's decisions.
M3: registered, versioned, protocol-budgeted evaluation of the deterministic
strategy itself (economic edge vs passive, fail-closed verdicts).
"""

from .capability import GOLDEN_THRESHOLD, probe
from .econ_eval import (
    EdgeReport,
    FoldOutcome,
    evaluate_protocol,
    render_report_json,
    render_report_markdown,
    write_report,
)
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
from .protocol import EvalProtocol, EvalVerdict, standard_protocol

__all__ = [
    "EdgeReport",
    "EvalProtocol",
    "EvalVerdict",
    "EvaluatedOutput",
    "FoldOutcome",
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
    "evaluate_protocol",
    "job_id_for",
    "probe",
    "render_report_json",
    "render_report_markdown",
    "run_job",
    "standard_protocol",
    "write_report",
]
