"""Execute slow checks outside the workflow lock, commit only current results."""

from pathlib import Path
from contextlib import contextmanager
import signal
import threading
from uuid import uuid4

from . import evidence
from .workflow import WorkflowError, load_workflow, workflow_lock, write_workflow


@contextmanager
def check_cancellation():
    """Allow CLI SIGTERM to unwind subprocess and evidence cleanup normally."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    previous = signal.getsignal(signal.SIGTERM)

    def cancel(signum, frame):
        raise WorkflowError("Verification was cancelled")

    signal.signal(signal.SIGTERM, cancel)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)


def state_hash(workflow: dict) -> str:
    # Check generations have their own token. Everything else (including pending
    # tasks, reservations, run/closure records and policy) belongs to the input.
    return evidence.fingerprint({
        key: value for key, value in workflow.items()
        if key not in {"checkExecution", "checkEvidence", "checkFailure", "mainReview"}
    })


def run_workflow_checks(root: Path, workflow_id: str, checks_file: Path) -> Path:
    # Tests may share build outputs or services. Preserve the old single-check
    # behavior without blocking unrelated workflow operations behind test runtime.
    with workflow_lock(root, workflow_id, timeout_seconds=0, purpose="checks") as check_fd:
        return _run_checks(root, workflow_id, checks_file, check_fd)


def _run_checks(root: Path, workflow_id: str, checks_file: Path, check_fd: int) -> Path:
    execution_id = uuid4().hex
    try:
        with workflow_lock(root, workflow_id):
            workflow = load_workflow(root, workflow_id)
            if workflow["status"] == "accepted":
                raise WorkflowError("Accepted workflows are immutable")
            workflow.pop("checkEvidence", None)
            workflow.pop("checkFailure", None)
            workflow.pop("mainReview", None)
            marker = {"id": execution_id, "stateHash": state_hash(workflow)}
            workflow["checkExecution"] = marker
            # Invalidate old success before reading inputs or starting a process.
            write_workflow(root, workflow)
            source = evidence.snapshot(
                workflow["policy"]["projectRoot"], workflow["policy"]["artifactRoot"]
            )

        result = evidence.run_checks(
            workflow, checks_file, expected_source=source, check_lock_fd=check_fd
        )

        with workflow_lock(root, workflow_id):
            current = load_workflow(root, workflow_id)
            if current.get("checkExecution") != marker:
                raise WorkflowError("Checks were superseded; older results cannot be committed")
            if current["status"] == "accepted" or state_hash(current) != marker["stateHash"]:
                raise WorkflowError("Workflow changed during checks; rerun current checks")
            if result["source"] != evidence.snapshot(
                current["policy"]["projectRoot"], current["policy"]["artifactRoot"]
            ):
                raise WorkflowError("Source changed before check results could commit; rerun checks")
            current.pop("checkExecution")
            current.pop("checkFailure", None)
            current["checkEvidence"] = result
            current.pop("mainReview", None)
            return write_workflow(root, current)
    except BaseException as error:
        # Never let an older failure clear a newer check's success or reservation.
        # A killed process leaves the marker unresolved and acceptance blocked;
        # a fresh run can replace it without trusting partial output.
        with workflow_lock(root, workflow_id):
            current = load_workflow(root, workflow_id)
            if (current.get("checkExecution") or {}).get("id") == execution_id:
                current.pop("checkExecution")
                current.pop("checkEvidence", None)
                current.pop("mainReview", None)
                current["checkFailure"] = {"id": execution_id, "error": str(error)[-4000:]}
                write_workflow(root, current)
        raise
