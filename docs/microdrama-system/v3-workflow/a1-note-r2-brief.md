# A1 design note, revision 2 (GLM): apply the Codex critique N1-1..N1-18

Orchestrator: Opus, 11 Nov 2026. You wrote `A1-design-note.md` (v1.1). Codex critiqued it:
`/root/AIVORA/drama-box/docs/microdrama-system/v3-workflow/codex-a1-note-critique.md` (REWORK).
**Every finding N1-1..N1-18 is accepted; its "Replace" wording is binding.** Revise the note **in place**
to **v1.2**.

Inputs are unchanged from your first brief (`a1-note-brief.md`): `phase-A-spec.md` v0.3, the Codex
critiques, `a-factmap.md`, master `SPEC-v3.md` v0.4.4, `phase-A0-spec.md` v0.4. **Cite `file:line` for
every code claim, and re-verify any line you reuse.**

## Orchestrator rulings where Codex gave a choice

1. **N1-5:** use **immutable activation records**.
   - Decisions and supersessions are appended as separate facts (`gate_activation_events`, or rows in
     the decision/supersession tables), and openness is derived from them.
   - Supersession needs no approval.
   - Nothing can be undone or rebound.
   - Spec §2.5 stays as written (append-only).
2. **N1-10:** the closed `DeferReason` vocabulary is enforced **at the jobs table write boundary by A0's
   migration 0027**. 0027 isn't built yet, so A0-D adds the CHECK; add that requirement to your §3
   ownership table.
   - **`defer_reason IS NULL` on a `RETRY_WAIT` job** means an ordinary bounded transport retry. It
     projects **no** side-state wait; the UI shows it as retrying.
   - Every enum value maps explicitly in the view; there is no fall-through.
   - Remove the claim of a read-time CHECK on the view.
3. **N1-7:** adopt Codex's revision plan exactly: validate at r, record at r, transitions use the decision
   context, then advance once.

## Write

- Update `A1-design-note.md` to v1.2. Change the header and keep §12 (the rulings, with OQ-3 adjusted per
  ruling 2).
- Add **§13 Finding → resolution**, mapping every N1-n to the section that fixes it.
- Keep it at most about 750 lines. Where the full inventory (N1-14) would be long, use a compact table:
  one row per boundary.
- Prose style: plain, short sentences.

## Limits

- Read-only except the note file.
- No code, tests, commits, network or systemd.
- Never print environment variables, keys or tokens.
- No deletion commands.
- Final message: the note's path and one line per finding saying where it is resolved.
