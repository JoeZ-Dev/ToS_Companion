# ToS_Companion: Agent Development Protocol

**Version:** 1.0
**Status:** Active, Binding for ToS_Companion Development

This document defines the development philosophy and operational workflow for any AI agent working on the ToS_Companion (Momentum Trading Companion) project. It is the procedural counterpart to the functional requirements in `specs.md`. Adherence to this protocol is non-negotiable.


---

## 1. Core Philosophy: Test-Driven Development (TDD)

Every single line of production code must be written in direct response to a failing test. The development cycle is strictly **RED-GREEN-REFACTOR-COMMIT**.

-   **RED:** Write a new, failing test that describes a single, small piece of desired business behavior.
-   **GREEN:** Write the absolute minimum amount of production code required to make that test pass, while ensuring all existing tests continue to pass.
-   **REFACTOR:** After a feature's behavior is fully implemented and tested, assess the production code for improvements in clarity, structure, and efficiency, without changing its external behavior.
-   **COMMIT:** After each successful GREEN step, the agent must commit the code with a concise, behavior-focused message (e.g., "test: add failing test for user limit", "feat: implement user playlist limit").

---

## 2. Technical Principles & Stack Conventions

### 2a. Testing
-   **Framework:** `pytest` is the sole testing framework.
-   **Behavior-Driven:** Tests must validate the application's behavior. Test names must reflect the behavior under test (e.g., `test_returns_403_when_playlist_limit_is_reached`), not the implementation detail.
-   **Public API Boundary:** Tests must primarily validate behavior through public module interfaces and boundary adapters (e.g., Analysis Engine inputs/outputs, Bar Aggregator inputs/outputs, Order/EMM/SyntheticTrigger behaviors, Journal writes). UI tests may be limited to smoke-level validation unless `specs.md` explicitly requires full GUI automation.
-   **Coverage:** All new business logic must be introduced via a failing test. No untested logic may enter the production codebase.
-   **Reproducibility:** All tests must be deterministic. Any use of randomness must be controlled and seeded to ensure tests produce the same result on every run.

### 2b. Strict Typing
-   **Type Hints:** All functions, variables, and data structures must use Python's standard type hints.
-   **Static Analysis (target):** Use type hints throughout. If `mypy` is configured in-repo, code must pass it. Do not introduce a strict `mypy` requirement unless `specs.md` explicitly mandates it.


### 2c. Contract-First Boundary Design
-   **Data Contracts:** Define explicit typed contracts (e.g., dataclasses / TypedDict) for boundary-crossing data:
    - Schwab REST responses → internal normalized models
    - Schwab stream messages → canonical quote events
    - AE snapshot inputs/outputs
    - LLM coach request/response schemas
-   **Validation:** Validate inbound Schwab payloads and any LLM output against these contracts. Schema mismatch must fail loudly and be journaled per `specs.md`.


### 2d. Immutability & Functional Style
-   **No Side Effects:** Functions should be pure wherever possible.
-   **Immutable Operations:** Data structures will be treated as immutable. In-place modification is forbidden. To change a structure, a new copy with the updated data will be created and returned.
-   **Clarity over Cleverness:** Prefer simple, readable code.

---

## 3. Agentic TDD Workflow in Practice

The agent's implementation of any feature will follow this precise, iterative sequence:

1.  **Receive Objective:** The user provides a high-level goal.
2.  **Step 1 (RED): Create Failing Test:** The agent creates a test for the most basic success case. The agent presents the failing test and its output.
3.  **Step 2 (GREEN): Write Minimal Code:** The agent writes the simplest possible production code to make the test pass. The agent presents the now-passing test suite.
4.  **Step 3 (COMMIT):** The agent commits the changes with a message describing the new behavior.
5.  **Step 4 (ITERATE): Add Next Failing Test:** The agent adds a new test for the next piece of required behavior. This new test will fail. The agent presents the failure.
6.  **Step 5 (ITERATE): Make It Pass & Commit:** The agent adds the minimal production logic to make the new test pass, then commits the changes.
7.  **Repeat:** Steps 4 and 5 are repeated until all behaviors for the feature are implemented.
8.  **Step 6 (REFACTOR): Propose Improvements:** Once complete, the agent analyzes the code for refactoring opportunities. If any are found, the agent commits all work *before* refactoring, then proceeds with the improvements, running the test suite after to ensure no behavior was broken.

This protocol ensures that the AmpUP V2 codebase is built in a verifiable, robust, and maintainable manner with a clean, atomic Git history.