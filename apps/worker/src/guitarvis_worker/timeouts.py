"""The job timeout, raised so that no stage can mistake it for a failure.

RQ enforces a job's timeout by raising JobTimeoutException from a SIGALRM
handler into whatever code is running. That class subclasses Exception, so
the pipeline's degrade-on-any-exception handlers would catch it, and a job
that ran out of time would end as a degraded "success" that dedupe then
serves forever. The worker's death penalty raises JobTimedOut instead. It is
a BaseException, which `except Exception` does not catch, so it reaches
process_job's requeue-or-fail path and then RQ's own retry handling.
"""

from types import FrameType, TracebackType

from rq.timeouts import JobTimeoutException, UnixSignalDeathPenalty


class JobTimedOut(BaseException):
    """The job ran past its timeout. Deliberately not an Exception."""


class JobTimeoutDeathPenalty(UnixSignalDeathPenalty):
    """RQ's SIGALRM death penalty, raising JobTimedOut for the job timeout.

    RQ times other things with the same class: the forking worker's wait on
    its work horse, and job callbacks. Those keep the exception RQ asked for,
    because RQ catches exactly that one.
    """

    def handle_death_penalty(self, signum: int, frame: FrameType | None) -> None:
        if issubclass(self._exception, JobTimeoutException):
            raise JobTimedOut(
                f"Task exceeded maximum timeout value ({self._timeout} seconds)"
            )
        super().handle_death_penalty(signum, frame)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        # RQ ignores an alarm that fires while it cancels it, once the body
        # has finished; it catches its own timeout class to do so. Keep that.
        try:
            return bool(super().__exit__(exc_type, exc, traceback))
        except JobTimedOut:
            return False
