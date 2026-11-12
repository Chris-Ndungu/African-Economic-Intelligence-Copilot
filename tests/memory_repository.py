"""An in-memory stand-in for ``InvestigationRepository``, for the page tests.

It implements the calls a run makes, with the same state rules as the real
repository: ``claim`` moves ``pending`` to ``running`` once, a success is
saved only for a ``running`` run, and a failure keeps no result.
"""

import uuid
from datetime import UTC, datetime

from copilot_core.repository import (
    Claim,
    InvestigationNotFoundError,
    InvestigationPage,
)
from copilot_core.schemas import (
    Investigation,
    InvestigationRun,
    InvestigationSummary,
    LLMUsage,
)


class MemoryRepository:
    def __init__(self) -> None:
        self.items: dict[uuid.UUID, Investigation] = {}

    def create_run(self, question, selection, data_mode, title):
        now = datetime.now(UTC)
        run = InvestigationRun(
            question=question,
            selection=selection,
            prompt_version=None,
            model=None,
            tool_calls=[],
            validation=None,
            usage=LLMUsage(calls=0, input_tokens=0, output_tokens=0, latency_ms=0),
        )
        item = Investigation(
            id=uuid.uuid4(),
            title=title,
            status="pending",
            data_mode=data_mode,
            request=None,
            result=None,
            error=None,
            run=run,
            created_at=now,
            updated_at=now,
        )
        self.items[item.id] = item
        return item

    def get(self, investigation_id):
        try:
            return self.items[investigation_id]
        except KeyError:
            raise InvestigationNotFoundError(investigation_id) from None

    def _set(self, investigation_id, **changes):
        item = self.get(investigation_id).model_copy(update=changes)
        self.items[investigation_id] = item
        return item

    def claim(self, investigation_id, pending_timeout_seconds):
        item = self.get(investigation_id)
        if item.status != "pending":
            return Claim(False, item)
        return Claim(True, self._set(investigation_id, status="running"))

    def save_success(self, investigation_id, result, run):
        if self.get(investigation_id).status != "running":
            return None
        return self._set(
            investigation_id, status="succeeded", result=result, request=result.request, run=run
        )

    def mark_failed(self, investigation_id, error, run=None, statuses=("pending", "running")):
        if self.get(investigation_id).status not in statuses:
            return False
        changes = {"status": "failed", "error": error, "result": None}
        if run is not None:
            changes["run"] = run
        self._set(investigation_id, **changes)
        return True

    def list(self, limit=20, cursor=None):
        ordered = sorted(self.items.values(), key=lambda i: i.created_at, reverse=True)
        return InvestigationPage(
            items=[
                InvestigationSummary(
                    id=i.id,
                    title=i.title,
                    status=i.status,
                    data_mode=i.data_mode,
                    investigation_type=None,
                    countries=[],
                    indicators=[],
                    created_at=i.created_at,
                    updated_at=i.updated_at,
                )
                for i in ordered[:limit]
            ],
            limit=limit,
            next_cursor=None,
        )
