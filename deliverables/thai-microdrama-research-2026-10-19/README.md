# Thai micro-drama decision package

Start with [the full source-linked decision plan](decision-plan.md).

For implementation and multi-agent orchestration, use the canonical [SPEC](../../docs/microdrama-system/SPEC.md), [task breakdown](../../docs/microdrama-system/task_breakdown.md) and [task status ledger](../../docs/microdrama-system/task_status.csv). The SPEC is the implementation baseline; these research documents retain rationale, source evidence and examples.

The current operating specification is [the fully automated pipeline and social-management plan](automation-plan.md): one season concept/arc approval, one final-video approval per episode, automated AI pre-review and selective repairs, automated publication/community/metadata work, and a US$10 variable-cost cap per episode. The user's clarified scope supersedes the original recurring manual production steps.

All eight accepted improvements are incorporated in section 13 of that specification and policy v2: episode-one identity/style lock, reusable directing patterns, shot-specific render quality, observation-first AI review, scoped feedback memory, queue/budget isolation, three hook experiments from existing footage, and ten-consecutive-episode qualification before increasing production volume.

Read [the optimized-compute correction](optimized-compute-addendum.md) before interpreting the original cost scenarios. FastH3/turbo/SageAttention workflows can change the GPU-cost envelope substantially; the original scenarios did not adequately research them.

The plan contains the recommendation, three concepts, ten-episode season arc, Thai/English opening minute, voice/reference specification, render benchmarks, production/publishing architecture, platform release matrix, geographic experiment, membership/DM offers, cost scenarios, two-week validation plan and ten unresolved empirical questions.

Supporting working files:

- [Cost scenarios](cost-scenarios.csv): USD assumptions and calculated costs, including labor and contingency.
- [Cost calculator](calculate-costs.py): rerun with Python 3; writes the cost CSV in this folder.
- [Example shot manifest](opening-shot-example.json): proposed episode 1, shot 2; backend-neutral, not an executable ComfyUI workflow.
- [Render benchmark template](render-benchmark-template.csv): empty by design; no render results have been fabricated.
- [Publication queue template](publication-queue-template.csv): empty starting ledger, not a deployed publishing system.
- [Automation policy example](automation-policy.example.json): machine-readable confirmed scope and proposed operating settings; inactive until implemented/configured.
- [Variable-cost ledger template](variable-cost-ledger-template.csv): reservations, accruals and actual charges, including unsuccessful jobs.
- [Directing playbook example](directing-playbook.example.json): six reusable shot patterns and initial production constraints.
- [Reliability scorecard template](reliability-scorecard-template.csv): empty qualification ledger for cost, quality, manual intervention, review time and continuation; production and seven-day management results are tracked separately.

Research date: 19 October 2026. Original scripts, visual designs, tests, pricing offers and thresholds are proposals. Public-source research and arithmetic checks were completed; paid generation, native Thai review, account onboarding, posting and audience tests were not performed. H3 global distribution rights remain unresolved. No source promises that subtitles, VPNs or AI-generated volume produce Western revenue.
