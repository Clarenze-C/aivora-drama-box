"""Technical, audio/ASR and visual QA (T017) plus the observation/comparison and
repair lanes' siblings (T018/T019 own those modules).

This lane exports the technical QA surface only; the integrator registers routes and
jobs. The module never imports the script into an observation: expected values enter
as arguments, observed values come out of the actual media.
"""

from microdrama.qa.audio import (
    MISMATCH_CODE,
    OBSERVER_MODEL_REF,
    MediaObserver,
    OfflineMediaObserver,
    SpeechObserverAdapter,
    align_best,
    align_lines,
    as_speech_observer,
)
from microdrama.qa.config import CRITICAL_CHECK_IDS, QAConfig
from microdrama.qa.coverage import (
    checked_ranges,
    coverage_for,
    partition_coverage,
    summarize_coverage,
)
from microdrama.qa.models import (
    QAReportView,
    QARunStatus,
    TechnicalQARun,
    build_finding,
)
from microdrama.qa.report import (
    RUN_EVENT,
    build_report_view,
    green_summary,
    load_findings,
    load_run_coverage,
)
from microdrama.qa.service import (
    OBSERVE_OPERATION,
    OBSERVE_PROVIDER,
    CaptionSource,
    TechnicalQAService,
    build_technical_qa_service,
)
from microdrama.qa.visual import identity_findings, prop_findings

__all__ = [
    "CRITICAL_CHECK_IDS",
    "MISMATCH_CODE",
    "OBSERVE_OPERATION",
    "OBSERVE_PROVIDER",
    "OBSERVER_MODEL_REF",
    "RUN_EVENT",
    "CaptionSource",
    "MediaObserver",
    "OfflineMediaObserver",
    "QAConfig",
    "QAReportView",
    "QARunStatus",
    "SpeechObserverAdapter",
    "TechnicalQARun",
    "TechnicalQAService",
    "align_best",
    "align_lines",
    "as_speech_observer",
    "build_finding",
    "build_report_view",
    "build_technical_qa_service",
    "checked_ranges",
    "coverage_for",
    "green_summary",
    "identity_findings",
    "load_findings",
    "load_run_coverage",
    "partition_coverage",
    "prop_findings",
    "summarize_coverage",
]
