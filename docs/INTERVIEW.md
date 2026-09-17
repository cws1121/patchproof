# Tell the engineering story

## Thirty-second project summary

“PatchProof is a local coding-agent evaluation lab. A Qwen model proposes a small Python repair, then an orchestrator validates the change, applies a diff to a disposable fixture, runs independent test cases, and requires human approval tied to the verified artifact. I can inspect the exact prompts, usage, failures and patch. It demonstrates the reliability layer around a coding model, with an intentionally narrow execution contract.”

Use this summary only once you have worked through the code and can explain the decisions in your own words. Be transparent about AI-assisted development and the parts you personally extended or investigated.

## Walkthrough

1. Show a real local-model run. Explain the known-target AST context and its source hash.
2. Compare the model's summary with its measured test outcomes. A confident explanation can accompany a wrong patch.
3. Run an overfitting fixture: public tests pass, regression tests fail. Explain why these cases never enter retry feedback.
4. Run an unsafe fixture. Explain the allowlisted expression interpreter, numeric budgets and subprocess deadline. Do not call it a general code sandbox.
5. Approve a passing patch. Explain why approval is bound to the artifact SHA rather than only a run ID.
6. Show an evaluation report and discuss its limits: four public micro-tasks, repeated prompts, no representative repository benchmark.

## Questions to prepare for

- Why did you use deterministic orchestration instead of letting the model choose every tool call?
- How would you distinguish retrieval failure, reasoning failure, invalid patch syntax and missing tests?
- What makes a test independent of the agent that proposes the change?
- How would you safely execute arbitrary repository tests instead of this bounded interpreter?
- What happens to a run if the model server fails or the application restarts?
- How do retries change token cost and latency? When should the agent stop?
- Why is passing a finite suite weaker than proving correctness?
- How would you measure developer time saved without encouraging insecure or unmaintainable patches?
- How would a GitHub App use least-privilege access and preserve human review?

## Extensions that demonstrate your own understanding

- Add a real bug you can explain and design regression cases before adjusting the prompt.
- Implement a per-run cancellation flag and verify that canceled runs cannot be approved.
- Add property-based checks for pagination and explain why generated tests can still share oracle mistakes.
- Compare a larger model with the local baseline using the same frozen task suite.
- Write a short incident note about a failed proposal: what happened, why the gate caught it, and what remains untested.
