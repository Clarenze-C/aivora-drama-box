# T031 benchmark operator notes

## Resume window after an uncertain prompt submission

Each prompt reservation expires 600 seconds (10 minutes) after it is created by
default. After a worker restart, resume reconciles the durable provider operation
through ComfyUI history and queue; it never submits the prompt again. Resume the
experiment within the hold window so the reservation remains active while that
reconciliation proceeds.

If the janitor expires the hold first, the resumed submit is refused. That refusal
is terminal for the experiment: its execution outcome becomes `FAILED`. The
operator can still reconcile the provider operation, clean up the owned pod, and
settle billing, but cannot reopen the experiment or dispatch another prompt.
