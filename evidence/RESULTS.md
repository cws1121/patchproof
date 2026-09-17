# Measured results

These are local development measurements from September 17, 2026. They cover four public synthetic expression-repair tasks, not real-repository coding performance. All model runs use temperature 0 and seed 42. Regression cases are withheld from each prompt and retry loop, but the entire suite is public in source.

## Initial model baseline

Model: official Qwen2.5-Coder-0.5B-Instruct, Q4_K_M; llama.cpp `b11026`; CPU; test-guided strategy, at most three proposals per task.

| Task | Gate | Attempts | Tokens | Run time |
|---|---|---:|---:|---:|
| Shipping threshold | Rejected | 3 | 870 | 12.4 s |
| Pagination ceiling | Rejected | 2 | 550 | 8.3 s |
| Owner/admin permission | Rejected | 1 | 238 | 4.4 s |
| Capped backoff | Rejected | 3 | 940 | 11.2 s |

**0/4 passed.** Shipping and backoff repeated the original bug. Pagination proposed unsupported `ceil`; the access task included `return` rather than an expression. Format/policy failures count as failures of the complete system contract, even if a broader execution environment could accept a different output.

Raw summary: [qwen-0.5b-test-guided.json](qwen-0.5b-test-guided.json).

The default model has been upgraded to Qwen Coder 1.5B. Its measurements will be recorded after a verified local run; the smaller model's failures are retained rather than replaced by fixture results.

## Deterministic verification checks

| Proposal source | Public tests | Gate pass | Expected outcome |
|---|---|---:|---|
| Correct fixtures | All pass | 4/4 | Ready for review; never auto-approved |
| Overfitting fixtures | All pass | 0/4 | Independent regression cases reject every task |
| Unsafe fixtures | Not executed | 0/4 | Policy rejects every proposal before patch application |

These fixture results validate orchestration behavior. They are **not model solve rates**. Individual offline test runs complete in roughly 0.2–0.6 seconds on this machine, excluding package setup. Timing varies with machine load.

## Interpretation

- Do not extrapolate a percentage from four intentionally simple tasks to a large codebase.
- A broader model or a different prompt can improve outputs, but should be judged under the same contract.
- Compare context-only and test-guided strategies using fresh CLI runs; record both failures and usage.
- Keep model capability, policy compatibility, infrastructure failures and test coverage as separate failure categories.
- Passing finite tests is evidence, not proof of correctness. The name PatchProof describes the review workflow, not formal verification.
