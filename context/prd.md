# TokenPilot — Technical Product Requirements Document

**Product:** TokenPilot  
**Category:** AI engineering cost intelligence and workflow optimization  
**Document version:** 1.0  
**Status:** Proposed — MVP specification  
**Primary audience:** Indie developers and students building with AI coding agents  
**Initial deployment:** Local-first developer application  
**Target build:** Meta Global AI Developer Hackathon

---

## 1. Executive Summary

TokenPilot is an AI engineering cost intelligence platform that helps developers understand how much their AI coding workflows cost, where resources are being wasted, and how to improve efficiency without sacrificing code quality.

As developers increasingly use multiple AI models, coding agents, API providers, and local inference runtimes, their usage data becomes fragmented across tools. Existing token counters and billing dashboards can report consumption, but they generally do not connect that consumption to engineering outcomes such as features implemented, bugs fixed, tests passed, or tasks abandoned.

TokenPilot addresses this gap by collecting AI usage telemetry, attributing costs to projects and engineering tasks, analyzing workflows for inefficiencies, and enabling repeatable benchmarks of alternative models and configurations.

Meta Muse models provide the intelligence layer that interprets workflow traces, investigates suspected inefficiencies, and proposes evidence-grounded optimization experiments. Deterministic analytics, execution logs, and automated tests validate the findings.

The core product loop is:

1. Observe AI coding activity.
2. Attribute costs and outcomes.
3. Detect inefficiencies.
4. Explain findings with supporting evidence.
5. Recommend a concrete optimization.
6. Benchmark the alternative.
7. Verify correctness and calculate realized savings.

**Product principle:** TokenPilot must optimize for the cost of successfully completing engineering work, not simply the number of tokens consumed.

## 2. Problem Statement

### 2.1 The problem

Developers using AI-assisted coding workflows lack a unified, outcome-oriented view of their AI engineering expenditure.

Usage may be distributed across hosted APIs, coding agents, compatible gateways, and local models. Even when individual tools expose usage statistics, developers often cannot determine:

- Which projects and engineering tasks consume the most money.
- Which workflows spend heavily without producing working code.
- Whether retries and repeated context materially increase costs.
- Whether an expensive model performs better than a cheaper alternative on the same task.
- Which prompts, model configurations, or execution strategies are most effective.
- How much an optimization actually saves while preserving correctness.

### 2.2 Why existing approaches are insufficient

Token counters answer how much was consumed. Provider billing pages answer how much was charged. Observability tools expose traces and request metrics.

TokenPilot must connect these signals to the engineering outcome.

For example, two coding sessions may each cost $0.80. One successfully fixes a bug with passing tests; the other makes several attempts and leaves the bug unresolved. Treating those sessions as equally productive misses the most important information.

TokenPilot therefore treats engineering tasks and verified outcomes as first-class analytical entities.

### 2.3 Target outcome

A developer should be able to open TokenPilot and answer:

1. Where is my AI coding budget going?
2. Why are particular workflows expensive or ineffective?
3. What specific change should I try?
4. Does the alternative work as well as the original?
5. How much money did the change actually save?

---

## 3. Product Vision and Goals

### 3.1 Vision

Become the intelligence layer between developers and their AI engineering tools, making AI-assisted software development measurable, explainable, and continuously improvable.

### 3.2 MVP goals

- Establish a reliable usage ledger.
- Attribute recorded usage to projects, sessions, and engineering tasks where metadata permits.
- Calculate transparent costs and clearly identify estimates.
- Identify deterministic waste signals.
- Use Meta Muse models to investigate traces and generate actionable findings.
- Support controlled, repeatable comparisons of coding workflows.
- Associate benchmark results with actual test outcomes.
- Report potential versus experimentally verified savings.
- Keep source code, credentials, and telemetry local by default, with explicit controls over external data sharing.

### 3.3 Non-goals

The MVP will not attempt to:

- Automatically route every production request between models.
- Replace existing coding agents or IDEs.
- Integrate every AI provider or coding tool.
- Automatically rewrite prompts or source code without developer approval.
- Guarantee that a model recommendation will improve performance.
- Build team billing, enterprise access controls, or organization-wide administration.
- Offer a marketplace of integrations.
- Provide a comprehensive cloud analytics service.
- Treat local inference as cost-free.
- Claim that a reduction in token usage necessarily means an improvement.

Routing may be introduced later as an optional execution mechanism for testing an optimization.

---

## 4. Target Users and Use Cases

### 4.1 Primary persona: Indie developer

A solo developer uses several AI coding tools and wants to reduce API expenditure without reducing output quality.

**Needs:**
- A consolidated cost view.
- Project-level attribution.
- Identification of inefficient sessions.
- Practical optimization recommendations.
- A way to compare configurations objectively.

### 4.2 Secondary persona: AI-heavy student or hobbyist

A developer experiments with hosted and local models and needs to understand the trade-offs between price, speed, and coding quality.

**Needs:**
- Cost and token transparency.
- Repeatable benchmark tasks.
- Local inference measurements.
- Simple reports that explain which configuration performed best.

### 4.3 Core user journeys

**Journey A — Understand spending**

1. Start the TokenPilot collector or gateway.
2. Execute coding tasks using a supported workflow.
3. View spending by project, session, model, and date.
4. Open an expensive session.
5. Inspect the requests, retries, failures, and cost breakdown.

**Journey B — Investigate waste**

1. Open the insights page.
2. Select a detected inefficiency.
3. Review supporting events and measurements.
4. Read the AI-generated explanation.
5. Approve or dismiss the recommendation.

**Journey C — Benchmark an optimization**

1. Select a representative coding task.
2. Choose a baseline configuration.
3. Choose an alternative model or workflow configuration.
4. Run both configurations against equivalent initial repository states.
5. Execute identical acceptance tests.
6. Compare cost, latency, retries, and correctness.
7. Save the results as a benchmark experiment.

**Journey D — Verify savings**

1. Select a completed benchmark.
2. Compare baseline and optimized results.
3. Review the cost difference and test outcomes.
4. Mark the experiment as accepted, rejected, or inconclusive.
5. Include the validated result in a project report.

---

## 5. Product Scope

### 5.1 P0 — Required for MVP

| Capability | Requirements |
|---|---|
| Usage ingestion | Capture requests, model identifiers, token counts, timestamps, latency, status, and available provider metadata. |
| Usage ledger | Persist normalized events with stable identifiers and deduplication. |
| Project attribution | Associate events with a project and, where available, a session and task. |
| Cost engine | Calculate costs from explicit model pricing and actual token usage. |
| Dashboard | Display spending, usage, latency, failures, and cost trends. |
| Waste detection | Detect repeated requests, retries, excessive context, and expensive unsuccessful sessions using deterministic rules. |
| AI investigation | Generate structured, evidence-linked explanations and recommendations using a Meta Muse model. |
| Benchmarking | Compare baseline and alternative configurations on reproducible tasks. |
| Outcome verification | Execute defined acceptance tests and record their results. |
| Savings reports | Distinguish estimated savings from measured benchmark savings. |

### 5.2 P1 — After the core loop works

- Additional coding-tool adapters.
- Ollama integration and local runtime telemetry.
- Local-versus-hosted comparisons.
- Budget thresholds and alerts.
- Historical comparisons of workflow configurations.
- Exportable reports.
- A controlled, opt-in proxy for supported tools.

### 5.3 P2 — Future product

- Optional automatic model routing.
- Organization and team analytics.
- CI-based benchmarking.
- Advanced context and prompt optimization.
- More sophisticated workflow recommendation strategies.
- Cloud synchronization and shared benchmark repositories.

P1 and P2 features must not delay the core usage-to-insight-to-benchmark workflow.

---

## 6. Functional Requirements

### FR-01: Usage ingestion

The system shall accept usage events through a supported OpenAI-compatible API gateway.

Each recorded event should contain the following information when available:

- Provider.
- Model identifier.
- Request and response timestamps.
- Input and output token counts.
- Cached input tokens, if exposed.
- Reasoning token counts, if exposed separately.
- Request latency.
- HTTP status and error category.
- Request identifier.
- Session identifier.
- Project identifier.
- Task or benchmark identifier.
- Retry metadata.
- Tool-call metadata.
- Usage source and confidence.

Missing fields must remain explicitly unknown rather than being fabricated or silently treated as zero.

**Acceptance criteria**

- Successful requests generate persisted events.
- Failed requests are recorded even if no token usage is returned.
- Duplicate ingestion does not silently double-count usage.
- Provider-reported usage is retained separately from locally estimated usage.
- Unsupported telemetry is documented.

### FR-02: Usage normalization and attribution

All adapters shall normalize incoming telemetry into a common event schema.

Attribution precedence:

1. Explicit task and project identifiers supplied by the integration.
2. Explicit session metadata.
3. Configured project-specific gateway or collector settings.
4. User-confirmed manual association.
5. Unattributed event.

The system must not infer a project solely from arbitrary prompt text.

Users shall be able to correct attribution without modifying the original raw event.

**Acceptance criteria**

- Every event has a unique internal ID.
- Events with insufficient metadata remain unattributed.
- Attribution changes are auditable.
- Aggregates are recalculated after corrections.

### FR-03: Cost calculation

The cost engine shall calculate request-level and aggregated costs using a versioned pricing catalogue.

For a model with input and output pricing:

Cost = input token cost + output token cost + applicable additional charges.

For example:

\[
C =
\frac{T_i P_i}{10^6}
+
\frac{T_o P_o}{10^6}
+
C_{\text{additional}}
\]

Where:

- \(T_i\) = billable input tokens.
- \(T_o\) = billable output tokens.
- \(P_i\) = input price per million tokens.
- \(P_o\) = output price per million tokens.

Additional charges may include separately priced cached tokens, reasoning tokens, or provider-specific components, but only when the provider's pricing rules require them.

The implementation must avoid double-counting tokens already included in another billing category.

Cost records must identify:

- Pricing source.
- Pricing version.
- Currency.
- Usage measurement source.
- Calculation timestamp.
- Whether the value is actual, estimated, or unavailable.

Provider-reported billed amounts take precedence for actual billing totals when their scope and semantics are known.

**Acceptance criteria**

- Cost calculations are reproducible from usage and pricing records.
- Historical events retain the pricing version used for the original estimate.
- Unknown pricing produces an unknown estimate, not a fabricated zero.
- Dashboard totals distinguish estimated usage cost from actual billed charges.

### FR-04: Usage and cost dashboard

The dashboard shall provide:

**Summary metrics**
- Total recorded spend.
- Actual versus estimated cost.
- Total input and output tokens.
- Request count.
- Failed request count.
- Retry count.
- Average and percentile latency where sufficient samples exist.
- Spend by project.
- Spend by model and provider.

**Breakdowns**
- Time-series spending.
- Project and session rankings.
- Model-level cost comparison.
- Successful versus unsuccessful task costs where outcomes are available.
- Cost concentration in the most expensive sessions.

Filters shall include date range, project, provider, model, and task outcome where available.

The interface must show when data is incomplete, estimated, or imported.

### FR-05: Deterministic waste detection

The initial insight engine shall implement rule-based detectors.

#### Detector A — Repeated request

Identify requests with identical normalized payload fingerprints or repeated tool-call identifiers within a configurable window.

The detector must distinguish true duplicate attempts from legitimate repeated work.

#### Detector B — Retry amplification

Group related attempts and calculate the additional cost attributable to retries.

\[
C_{\text{retry}} = \sum_{r \in R_{\text{retry}}} C_r
\]

Report retry frequency, failure reasons, and cumulative cost.

#### Detector C — Repeated context

Identify repeated large context blocks across requests in the same session when request payload visibility permits.

Report repeated bytes or tokens where measurable. Label hash-only or partial observations accordingly.

#### Detector D — Expensive unsuccessful task

Identify tasks with high cumulative spend and a failed, abandoned, or unverified outcome.

Do not classify missing outcome data as failure.

#### Detector E — High context-to-output ratio

Flag unusually high input consumption relative to output generation using configurable thresholds or workload-specific baselines.

This is a diagnostic signal, not proof of waste. Long-context reasoning tasks can legitimately require large inputs.

#### Detector F — Runaway session

Identify sessions that exceed configured thresholds for duration, request count, retry count, or cost without a recorded successful outcome.

The detector should distinguish an open or still-running task from a confirmed failure.

#### Detector G — Model inefficiency

Identify benchmark evidence where a configuration consumes more resources but does not produce a better verified result.

This detector requires comparable benchmark runs; raw cost differences between unrelated tasks are insufficient.

Each detector shall output a rule identifier, evidence references, severity, confidence, and explanatory metadata.

### FR-06: AI-assisted investigation

The AI investigator shall use a supported Meta Muse model to analyze a bounded set of relevant telemetry and detected signals.

Inputs may include:

- Session-level metrics.
- Selected normalized request metadata.
- Deterministic detector findings.
- Error categories.
- Benchmark outcomes.
- Explicitly authorized excerpts of request or response content.

The model shall return structured output containing:

- Summary.
- Suspected root cause.
- Supporting evidence IDs.
- Impact assessment.
- Recommended action.
- Expected direction of impact.
- Validation procedure.
- Confidence level.
- Limitations or missing evidence.

The model must not invent token counts, costs, request IDs, test results, or other measurements.

Every factual finding must refer to evidence available in the investigation input.

If the available evidence does not support a conclusion, the investigator shall report insufficient evidence.

Recommendations must distinguish:
- Observed facts.
- Hypotheses.
- Proposed experiments.
- Measured results.

### FR-07: Recommendation management

Users shall be able to:

- View a recommendation and its evidence.
- Mark it as useful, not useful, or not applicable.
- Dismiss it.
- Create a benchmark from it.
- Record whether the recommendation was implemented.
- Compare the outcome against the original baseline.

The MVP shall not automatically modify production workflows.

### FR-08: Benchmark management

Users shall be able to create and execute controlled benchmark experiments.

A benchmark definition shall include:

- Name and description.
- Project and repository.
- Task specification.
- Baseline configuration.
- Alternative configuration or configurations.
- Initial repository revision.
- Acceptance criteria.
- Test command or test suite.
- Timeout and resource limits.
- Repeat count.
- Model and configuration metadata.

Supported experimental variables may include:

- Model identifier.
- Prompt template.
- Context-selection strategy.
- Agent configuration.
- Tool permissions.
- Retry policy.
- Temperature or other supported inference parameters.

Only one variable should change at a time when practical. Experiments that change multiple variables must identify those changes explicitly.

### FR-09: Isolated execution

Each benchmark run shall execute in a separate Git worktree or equivalent isolated repository copy.

The execution system must:

- Start from the specified initial revision.
- Apply the task instructions.
- Record the selected model and configuration.
- Capture requests, usage, errors, and duration.
- Enforce execution timeouts.
- Run the specified acceptance tests.
- Capture test output and exit status.
- Preserve generated patches and result metadata.
- Clean up temporary resources according to configured retention rules.

Untrusted generated code must not execute with unrestricted access to user credentials, arbitrary host files, or the developer's full environment.

Benchmark execution should use a restricted environment and explicit permissions.

### FR-10: Benchmark outcome scoring

Each run shall receive a result status:

- Passed.
- Failed.
- Timed out.
- Cancelled.
- Inconclusive.

Test success shall be determined by the configured test command and acceptance criteria, not by the model's self-assessment.

The benchmark report shall show:

- Total cost.
- Input and output tokens.
- Wall-clock duration.
- Number of model calls.
- Retry count.
- Test pass/fail results.
- Exit status.
- Patch or artifact reference.
- Run configuration.

A failed run with lower cost must not automatically be described as an optimization.

### FR-11: Savings calculation

For comparable baseline and alternative runs:

\[
S = C_b - C_a
\]

\[
S_{\%} = \frac{C_b-C_a}{C_b}\times100
\]

Where:

- \(C_b\) = baseline cost.
- \(C_a\) = alternative cost.
- \(S\) = absolute savings.

Savings percentages are undefined when the baseline cost is zero.

A positive cost difference is not sufficient to claim a successful optimization. The system must also consider task correctness.

The product shall distinguish:

1. **Potential savings:** Estimated from an untested recommendation.
2. **Benchmark savings:** Observed in a controlled comparison.
3. **Verified savings:** Observed in comparable runs where the alternative meets the required correctness criteria.
4. **Realized savings:** Measured over subsequent eligible real-world tasks after adoption, with the measurement window and comparison method disclosed.

Where runs are stochastic, report repeat counts and variability. Avoid claiming statistical significance from insufficient observations.

### FR-12: Reporting

Users shall be able to generate a project report summarizing:

- Spend over the selected period.
- Most expensive sessions.
- Successful versus unsuccessful task costs.
- Detected waste categories.
- Top recommendations.
- Benchmark results.
- Verified savings.
- Remaining limitations and unattributed usage.

Reports must include the time period, cost basis, data coverage, and whether values are estimated or actual.

---

## 7. Technical Architecture

### 7.1 Architecture principles

- Local-first data storage.
- Small, independently testable components.
- Deterministic accounting.
- Explainable insights.
- Explicit source provenance.
- Controlled execution of generated code.
- No mandatory cloud account.
- Optional external model analysis with transparent data disclosure.

### 7.2 Proposed architecture

```text
AI Coding Client / Compatible API Client
                  |
                  v
          FastAPI Gateway
                  |
          +-------+--------+
          |                |
          v                v
   Usage Recorder     Request Metadata
          |
          v
   Normalization and Deduplication
          |
          v
       SQLite Store
          |
     +----+----------------------+
     |                           |
     v                           v
Cost and Analytics Engine   Waste Detectors
     |                           |
     +-------------+-------------+
                   |
                   v
           Evidence Assembler
                   |
                   v
         Meta Muse Investigator
                   |
                   v
         Recommendations Store
                   |
                   v
           Benchmark Manager
                   |
                   v
       Isolated Run Environments
                   |
                   v
         Acceptance Test Runner
                   |
                   v
         Results and Savings Engine
                   |
                   v
        React / Next.js Dashboard
```

### 7.3 Recommended stack

| Component | Technology | Responsibility |
|---|---|---|
| Frontend | Next.js, React, TypeScript | Dashboard, insights, benchmark management |
| Backend | Python, FastAPI | API, ingestion, analytics, orchestration |
| Database | SQLite | Local event store and application state |
| Schema validation | Pydantic | Request and response validation |
| Database migrations | Alembic or versioned SQL migrations | Schema evolution |
| Model intelligence | Meta Model API | Trace investigation and recommendations |
| Gateway | FastAPI reverse proxy | Supported API-compatible request capture |
| Execution | Git worktrees and subprocess runner | Reproducible benchmark tasks |
| Tests | pytest plus repository-specific commands | API and benchmark verification |
| Local model telemetry | Ollama API or supported runtime adapter | Local usage and performance where available |

The frontend and backend can run locally. PostgreSQL, cloud synchronization, and a distributed task queue are not required for the first version.

A single-process background worker is sufficient initially, provided long-running benchmark execution does not block normal API requests.

### 7.4 Component responsibilities

**Gateway**

- Accept supported requests.
- Forward them to the configured upstream.
- Preserve compatible request and response semantics.
- Capture metadata and available usage.
- Record failures.
- Avoid logging secrets.
- Never silently change models or prompts.

**Normalizer**

- Convert provider-specific telemetry into a common schema.
- Validate units and token counts.
- Deduplicate records.
- Retain provenance and raw metadata where safe.

**Analytics engine**

- Aggregate spend, token consumption, latency, and failures.
- Attribute requests to tasks and sessions.
- Calculate cost and outcome metrics.

**Insight engine**

- Execute deterministic detectors.
- Assemble evidence bundles.
- Invoke Meta Muse analysis when appropriate.
- Validate structured recommendations.
- Persist findings and their supporting evidence.

**Benchmark manager**

- Create experiments and runs.
- Create isolated repository worktrees.
- Apply the configured model and workflow.
- Enforce execution limits.
- Capture outputs and test results.
- Calculate comparisons.

**Dashboard**

- Present spending and outcome metrics.
- Explain detected inefficiencies.
- Let users launch and inspect benchmarks.
- Show the difference between recommendations and validated results.

---

## 8. Data Model

SQLite is the source of truth for the local MVP. The following logical schema is the starting point; physical migrations may refine field types and indexing.

### 8.1 `projects`

| Field | Type | Purpose |
|---|---|---|
| id | TEXT / UUID | Primary key |
| name | TEXT | Display name |
| repository_path | TEXT | Local repository location |
| default_currency | TEXT | Reporting currency |
| created_at | DATETIME | Creation time |
| updated_at | DATETIME | Last modification |

### 8.2 `sessions`

| Field | Type | Purpose |
|---|---|---|
| id | TEXT / UUID | Primary key |
| project_id | TEXT | Optional project reference |
| external_session_id | TEXT | Source tool session identifier |
| source | TEXT | Gateway, adapter, import |
| started_at | DATETIME | Session start |
| ended_at | DATETIME | Session end, if known |
| outcome | TEXT | Success, failure, abandoned, unknown |
| outcome_source | TEXT | Test, manual, adapter, inferred |
| metadata_json | TEXT | Non-sensitive supplemental metadata |

### 8.3 `tasks`

Represents a discrete engineering task, such as fixing a bug or implementing a feature.

| Field | Type | Purpose |
|---|---|---|
| id | TEXT / UUID | Primary key |
| project_id | TEXT | Project reference |
| session_id | TEXT | Optional source session |
| title | TEXT | Task label |
| description | TEXT | Task instructions or reference |
| task_type | TEXT | Bug fix, feature, refactor, docs, other |
| outcome | TEXT | Passed, failed, unknown |
| outcome_source | TEXT | How success was determined |
| created_at | DATETIME | Creation time |

### 8.4 `usage_events`

The canonical normalized usage ledger.

| Field | Type | Purpose |
|---|---|---|
| id | TEXT / UUID | Internal event ID |
| source_event_id | TEXT | External request ID, if available |
| idempotency_key | TEXT | Deduplication key |
| project_id | TEXT | Optional project reference |
| session_id | TEXT | Optional session reference |
| task_id | TEXT | Optional task reference |
| provider | TEXT | Provider name |
| model_id | TEXT | Model identifier |
| input_tokens | INTEGER / NULL | Input tokens |
| output_tokens | INTEGER / NULL | Output tokens |
| cached_tokens | INTEGER / NULL | Cached token count, if known |
| reasoning_tokens | INTEGER / NULL | Separate reasoning count, if known |
| usage_source | TEXT | Provider, gateway estimate, import |
| status | TEXT | Success, error, timeout, unknown |
| latency_ms | INTEGER / NULL | Measured request latency |
| retry_group_id | TEXT / NULL | Related retry sequence |
| request_fingerprint | TEXT / NULL | Optional privacy-conscious fingerprint |
| started_at | DATETIME | Request start |
| completed_at | DATETIME / NULL | Request completion |
| metadata_json | TEXT | Sanitized provider-specific metadata |

Do not store API keys, authorization headers, or unrestricted raw prompt content in the usage ledger.

### 8.5 `pricing_versions`

| Field | Type | Purpose |
|---|---|---|
| id | TEXT / UUID | Pricing version ID |
| provider | TEXT | Provider |
| model_id | TEXT | Model identifier |
| currency | TEXT | Pricing currency |
| input_price_per_million | REAL / NULL | Input price |
| output_price_per_million | REAL / NULL | Output price |
| cached_input_price | REAL / NULL | Optional cached-input rate |
| pricing_source | TEXT | Source or manual configuration |
| valid_from | DATETIME | Effective date |
| valid_to | DATETIME / NULL | End of validity |
| created_at | DATETIME | Record creation |

Additional provider-specific billing components should be represented explicitly rather than forced into an inaccurate generic formula.

### 8.6 `cost_records`

| Field | Type | Purpose |
|---|---|---|
| id | TEXT / UUID | Primary key |
| usage_event_id | TEXT | Associated event |
| pricing_version_id | TEXT / NULL | Applied pricing |
| estimated_cost | REAL / NULL | Calculated cost |
| reported_cost | REAL / NULL | Provider-reported cost, if available |
| billed_cost | REAL / NULL | Confirmed billing amount, if available |
| currency | TEXT | Currency |
| cost_basis | TEXT | Estimated, reported, billed |
| calculated_at | DATETIME | Calculation time |

### 8.7 `insights`

| Field | Type | Purpose |
|---|---|---|
| id | TEXT / UUID | Primary key |
| project_id | TEXT | Optional project reference |
| session_id | TEXT | Optional session reference |
| task_id | TEXT | Optional task reference |
| detector_type | TEXT | Rule or investigation category |
| severity | TEXT | Informational, low, medium, high |
| status | TEXT | New, reviewed, dismissed, tested |
| title | TEXT | Short description |
| summary | TEXT | Finding summary |
| root_cause_hypothesis | TEXT | Suspected explanation |
| confidence | REAL / NULL | Calibrated confidence, if available |
| estimated_impact | REAL / NULL | Potential impact |
| evidence_json | TEXT | Evidence IDs and measurements |
| recommendation_json | TEXT | Proposed action and validation |
| investigator_model | TEXT / NULL | Model used |
| created_at | DATETIME | Creation time |

### 8.8 `benchmarks`

| Field | Type | Purpose |
|---|---|---|
| id | TEXT / UUID | Primary key |
| project_id | TEXT | Project |
| task_id | TEXT | Benchmark task |
| name | TEXT | Experiment name |
| initial_git_sha | TEXT | Starting repository revision |
| acceptance_config_json | TEXT | Test and success criteria |
| baseline_config_json | TEXT | Baseline configuration |
| created_at | DATETIME | Creation time |

### 8.9 `benchmark_runs`

| Field | Type | Purpose |
|---|---|---|
| id | TEXT / UUID | Primary key |
| benchmark_id | TEXT | Experiment reference |
| variant_name | TEXT | Baseline or alternative |
| model_id | TEXT | Model used |
| config_json | TEXT | Prompt and workflow configuration |
| run_status | TEXT | Queued, running, completed, failed |
| outcome | TEXT | Passed, failed, timed out, inconclusive |
| total_cost | REAL / NULL | Aggregated cost |
| total_tokens | INTEGER / NULL | Aggregated tokens |
| request_count | INTEGER | Model requests |
| retry_count | INTEGER | Retries |
| duration_ms | INTEGER / NULL | Total runtime |
| test_exit_code | INTEGER / NULL | Acceptance test status |
| test_results_json | TEXT | Test summaries |
| patch_path | TEXT / NULL | Stored patch location |
| worktree_path | TEXT / NULL | Temporary execution location |
| started_at | DATETIME / NULL | Start time |
| completed_at | DATETIME / NULL | Completion time |

### 8.10 `benchmark_comparisons`

| Field | Type | Purpose |
|---|---|---|
| id | TEXT / UUID | Primary key |
| benchmark_id | TEXT | Experiment reference |
| baseline_run_id | TEXT | Baseline run |
| alternative_run_id | TEXT | Alternative run |
| cost_delta | REAL / NULL | Baseline minus alternative |
| cost_delta_pct | REAL / NULL | Percentage difference |
| correctness_preserved | BOOLEAN / NULL | Acceptance criteria satisfied |
| comparison_status | TEXT | Potential, measured, verified, inconclusive |
| methodology_json | TEXT | Repeat counts and comparison settings |
| created_at | DATETIME | Creation time |

### 8.11 Relationships

- One project can contain many sessions and tasks.
- A session can contain many usage events.
- A task can be associated with many usage events and benchmark runs.
- Each usage event can have one or more cost calculations across recalculations, with the applicable pricing version retained.
- An insight references one or more events or aggregate measurements.
- A benchmark contains multiple runs.
- A comparison references a baseline run and an alternative run.

Use foreign keys, appropriate indexes, transactional writes, and versioned schema migrations.

---

## 9. API Specification

The following endpoints define the initial backend contract. Exact payloads and error schemas should be finalized during implementation.

### 9.1 Usage and projects

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/v1/usage/events` | Ingest normalized events |
| GET | `/api/v1/usage/events` | Query usage events |
| GET | `/api/v1/usage/summary` | Aggregated usage and costs |
| GET | `/api/v1/projects` | List projects |
| POST | `/api/v1/projects` | Create project |
| GET | `/api/v1/projects/{id}` | Project details |
| PATCH | `/api/v1/projects/{id}` | Update project metadata |

### 9.2 Insights

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/v1/insights/analyze` | Run selected deterministic detectors |
| GET | `/api/v1/insights` | List findings |
| GET | `/api/v1/insights/{id}` | Retrieve finding and evidence |
| POST | `/api/v1/insights/{id}/investigate` | Invoke Meta Muse analysis |
| PATCH | `/api/v1/insights/{id}` | Update review status |
| POST | `/api/v1/insights/{id}/benchmark` | Create benchmark from a finding |

Analysis and investigation requests should be asynchronous if they may exceed normal API latency.

### 9.3 Benchmarks

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/v1/benchmarks` | Create experiment |
| GET | `/api/v1/benchmarks` | List experiments |
| GET | `/api/v1/benchmarks/{id}` | Experiment details |
| POST | `/api/v1/benchmarks/{id}/runs` | Start a run |
| GET | `/api/v1/benchmark-runs/{id}` | Run status and results |
| POST | `/api/v1/benchmarks/{id}/compare` | Compare completed runs |
| POST | `/api/v1/benchmarks/{id}/cancel` | Cancel eligible work |

### 9.4 Reporting

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/v1/reports/project/{id}` | Project cost and outcome report |
| GET | `/api/v1/reports/savings` | Potential and verified savings |
| GET | `/api/v1/health` | Local service health |

### 9.5 API conventions

- Use ISO 8601 timestamps in UTC for stored and returned timestamps.
- Use explicit currency fields.
- Use pagination for event and insight lists.
- Validate request bodies with Pydantic.
- Return structured error responses.
- Use idempotency keys for event ingestion and benchmark creation where appropriate.
- Require a local authentication mechanism or equivalent access restriction for gateway and control endpoints.
- Never expose secrets in API responses or logs.

---

## 10. Insight Engine Design

The insight engine is the product's core differentiator.

### 10.1 Two-stage analysis

**Stage 1 — Deterministic analysis**

Collect and calculate objective signals:

- Repeated request fingerprints.
- Retry amplification.
- Repeated context volume.
- Failed or unverified task expenditure.
- High context-to-output ratios.
- Cost and latency outliers.
- Benchmark differences.

These detectors should run without an LLM.

**Stage 2 — AI investigation**

The investigator receives a bounded evidence bundle and answers:

- What likely caused the observed inefficiency?
- Which evidence supports that explanation?
- What should the developer change?
- What is the smallest useful experiment?
- Which metrics would validate the recommendation?

The model must not decide the underlying numerical totals. It should use precomputed measurements supplied by the backend.

### 10.2 Evidence bundle

An investigation input should contain:

- Investigation ID.
- Relevant event IDs.
- Aggregated metrics.
- Detector outputs.
- Known task outcomes.
- Applicable pricing metadata.
- Allowed request excerpts, if explicitly enabled.
- Data coverage and uncertainty.

### 10.3 Structured output

The model should return a schema-validated object conceptually equivalent to:

```json
{
  "title": "Repeated context during debugging",
  "summary": "Large context blocks recur across related requests.",
  "root_cause_hypothesis": "The workflow may resend unnecessary context.",
  "evidence_ids": ["event-a", "event-b"],
  "recommendation": {
    "action": "Test a targeted-context strategy",
    "expected_effect": "Lower input-token consumption",
    "validation": "Replay the same task and run the same tests"
  },
  "limitations": [
    "Repeated context does not prove that all repeated tokens were avoidable."
  ]
}
```

This is an illustrative contract, not an assertion that a particular investigation has already been performed.

### 10.4 Trust and evaluation

- Validate every referenced evidence ID.
- Reject unsupported numerical claims.
- Keep recommendations separate from measured outcomes.
- Record the model and prompt-template version.
- Track accepted, dismissed, and experimentally validated recommendations.
- Evaluate investigation quality against a small manually reviewed test set.

---

## 11. Benchmarking Methodology

Benchmark quality determines whether TokenPilot can credibly claim savings.

### 11.1 Task definition

Each benchmark task should have:

- A stable initial Git revision.
- A clear task description.
- A defined set of acceptance tests.
- A reproducible environment.
- A maximum execution time.
- A defined model and workflow configuration.

Examples include fixing a known bug, implementing a small feature, refactoring a function without changing behavior, or updating documentation.

### 11.2 Experimental controls

- Use equivalent initial repository states.
- Keep acceptance tests identical.
- Record configuration changes.
- Control timeouts and tool permissions.
- Capture the same categories of telemetry.
- Run multiple trials when model output variability could affect the conclusion.
- Report missing or incomparable data.

Where a task changes shared external state, the runner must provide an isolated or resettable environment.

### 11.3 Primary metrics

**Cost per successful task**

\[
C_{\text{success}} =
\frac{\text{Total cost across eligible runs}}
{\text{Number of successful runs}}
\]

Also report the success rate separately. Cost per successful task must not conceal a poor completion rate.

**Success rate**

\[
R_{\text{success}} =
\frac{\text{Successful runs}}
{\text{Completed eligible runs}}
\]

**Retry amplification**

\[
A_{\text{retry}} =
\frac{\text{Cost of retry requests}}
{\text{Total task cost}}
\]

**Cost reduction**

\[
R_{\text{cost}} =
\frac{C_{\text{baseline}}-C_{\text{alternative}}}
{C_{\text{baseline}}}\times100
\]

**Additional metrics**

- Median and percentile latency.
- Token consumption.
- Number of requests.
- Test pass rate.
- Timeout rate.
- Output or patch quality, where a reliable evaluation method exists.

### 11.4 Comparison classifications

- **Incomparable:** Different task, starting state, acceptance criteria, or insufficient telemetry.
- **Measured:** Cost and runtime have been recorded.
- **Correctness-preserving:** The alternative meets the same acceptance criteria.
- **Verified optimization:** The alternative meets the required criteria and reduces cost under the documented methodology.
- **Inconclusive:** Results are too variable or incomplete to support a decision.

---

## 12. Frontend and User Experience

### 12.1 Main navigation

1. Overview.
2. Projects.
3. Sessions.
4. Insights.
5. Benchmarks.
6. Reports.
7. Settings.

### 12.2 Overview page

Show:
- Recorded spend and cost basis.
- Spend over time.
- Most expensive projects.
- Highest-cost sessions.
- Failed and unverified workflows.
- Retry expenditure.
- Recent actionable insights.
- Latest benchmark results.

### 12.3 Session detail page

Show:
- Session metadata.
- Request timeline.
- Model and provider breakdown.
- Input and output tokens.
- Per-request cost.
- Failures and retries.
- Repeated-context signals where available.
- Outcome and outcome provenance.
- Related insights.

### 12.4 Insights page

Each insight should display:

- A concise finding.
- Severity and confidence.
- Evidence and measurements.
- Potential impact.
- Recommended action.
- Validation procedure.
- Actions to dismiss, investigate, or benchmark.

Do not present a large AI-generated paragraph as a substitute for evidence.

### 12.5 Benchmark comparison page

Show baseline and alternative side by side:

- Model and configuration.
- Total cost.
- Token usage.
- Runtime.
- Request and retry counts.
- Test outcomes.
- Patch references.
- Savings classification.
- Comparison methodology.

Use prominent, unambiguous labels for estimated savings versus measured and verified savings.

---

## 13. Security and Privacy

TokenPilot can encounter sensitive source code, prompts, API credentials, repository metadata, and model responses. Privacy is a core architectural requirement.

### 13.1 Local-first storage

- Keep SQLite data on the developer's machine.
- Do not require an account or cloud database for core functionality.
- Avoid storing raw prompts and responses by default unless needed and explicitly enabled.
- Provide retention and deletion controls.

### 13.2 Credential protection

- Never persist upstream API keys in event records.
- Redact authorization headers and known secrets.
- Use environment variables or the operating system's credential storage where applicable.
- Prevent credentials from entering benchmark logs or generated reports.

### 13.3 External model analysis

When invoking a hosted Meta model:

- Send only the minimum evidence required.
- Disclose whether prompt excerpts or source-code content will be transmitted.
- Offer metadata-only investigation where feasible.
- Allow users to disable content transmission.
- Do not assume local storage means all processing remains local.

### 13.4 Benchmark isolation

- Execute generated code with restricted permissions.
- Avoid inheriting unrestricted host credentials.
- Restrict filesystem and network access where feasible.
- Enforce timeouts and resource limits.
- Treat repository scripts, dependencies, and model-generated commands as untrusted.
- Require explicit approval for potentially destructive operations.

### 13.5 Data integrity

- Preserve event provenance.
- Keep raw and normalized data conceptually distinct.
- Make attribution and pricing changes traceable.
- Validate imported data before it affects financial reports.

---

## 14. Non-Functional Requirements

### Performance

Initial targets for a local MVP:

- Dashboard summary queries: p95 under 500 ms for 100,000 locally stored events on a documented development machine.
- Normalized event ingestion: p95 under 200 ms when the operation does not wait for an upstream model response.
- Standard filtered queries must use pagination and appropriate indexes.
- Long-running investigations and benchmark executions must not block unrelated API requests.

These are engineering targets to validate, not guaranteed performance claims.

### Reliability

- Use transactional persistence.
- Do not lose already-recorded events when an upstream request fails.
- Record ingestion and benchmark errors.
- Make event processing idempotent where possible.
- Recover or mark interrupted benchmark runs after application restart.

### Accuracy

- Use consistent units and explicit pricing versions.
- Do not substitute missing telemetry with zero.
- Keep estimates separate from confirmed charges.
- Never equate missing outcomes with failed tasks.
- Require comparable evidence for savings claims.

### Maintainability

- Use typed schemas and versioned database migrations.
- Separate adapters, analytics, pricing, investigation, and benchmarking.
- Provide deterministic unit tests for calculations.
- Keep model-specific logic behind an abstraction layer.
- Version detector rules and investigation prompts.

### Compatibility

The initial release should target macOS development workflows first if a single operating-system target is needed, while avoiding unnecessary platform-specific assumptions in the API and data model.

---

## 15. Testing and Quality Assurance

### 15.1 Unit tests

Required coverage includes:

- Cost calculation.
- Pricing-version selection.
- Token accounting.
- Deduplication.
- Retry grouping.
- Event attribution.
- Insight thresholds.
- Savings calculations.
- Benchmark result classification.

### 15.2 Integration tests

- Successful and failed gateway requests.
- Missing usage metadata.
- Duplicate events.
- Provider error handling.
- Database persistence.
- Meta model response validation.
- Benchmark execution and cleanup.
- Test result collection.
- Dashboard aggregation.

### 15.3 Benchmark safety tests

- A failed task is never marked as a verified optimization.
- A timeout is not silently recorded as a successful completion.
- A lower-cost alternative that fails acceptance tests is rejected as an optimization.
- Different starting revisions are flagged as incomparable.
- Missing pricing does not generate a fabricated cost.
- Unavailable usage metadata is shown as unknown.
- Repeated context is not automatically assumed to be waste.

### 15.4 Insight quality evaluation

Prepare a small labeled dataset containing:

- Clear retry waste.
- Repeated requests that are legitimate.
- Large context that is necessary.
- Expensive tasks that successfully complete.
- Expensive tasks that fail.
- Incomplete or ambiguous traces.

Measure detector precision on this dataset and review AI recommendations for evidence support, specificity, and usefulness.

---

## 16. Success Metrics

### Product metrics

- Percentage of usage events with reliable project attribution.
- Percentage of events with usable cost data.
- Number of actionable insights generated.
- Percentage of insights accepted as useful by users.
- Percentage of recommendations converted into benchmark experiments.
- Percentage of benchmark comparisons with complete outcome data.
- Number of verified optimizations.

### Technical metrics

- Duplicate-event rate.
- Cost calculation test accuracy.
- Gateway overhead.
- Benchmark completion rate.
- Insight evidence-validation rate.
- Benchmark reproducibility.
- Number of false-positive waste detections in the labeled test set.

### Core outcome metric

**Verified cost reduction on comparable coding tasks, subject to unchanged acceptance criteria.**

TokenPilot should not optimize its success metric around the total number of tokens saved. Lower token consumption is useful only when it preserves the required engineering outcome or produces a demonstrably better trade-off.

---

## 17. Implementation Plan

The initial hackathon scope should be planned around the actual submission deadline, with optional features deferred until the core workflow is reliable.

### Phase 1 — Telemetry foundation

- Implement project and event schemas.
- Build the compatible gateway.
- Capture request usage, latency, failures, and metadata.
- Implement cost calculation.
- Add initial dashboard summaries.

**Exit criteria:** A developer can generate requests and inspect accurate, attributable usage records.

### Phase 2 — Deterministic intelligence

- Implement retry, repeated-request, context, and unsuccessful-task detectors.
- Add session detail views.
- Generate evidence bundles.
- Create an insight review interface.

**Exit criteria:** Every deterministic finding can be traced to recorded evidence.

### Phase 3 — Meta Muse investigator

- Integrate the supported Meta Model API.
- Define a structured investigation schema.
- Validate evidence references.
- Generate actionable recommendations.
- Add investigation failure handling and privacy controls.

**Exit criteria:** The system can explain a detected inefficiency and propose a testable intervention without inventing measurements.

### Phase 4 — Benchmarking

- Define benchmark tasks and acceptance criteria.
- Implement Git worktree isolation.
- Capture per-run usage.
- Execute tests.
- Compare baseline and alternative configurations.

**Exit criteria:** The system can run the same task under two configurations and produce a valid comparison.

### Phase 5 — Optimization proof and demo

- Implement savings classification.
- Connect insights to benchmark creation.
- Polish the benchmark comparison view.
- Test failure scenarios.
- Prepare a repeatable end-to-end demonstration.

**Exit criteria:** A complete workflow from usage ingestion through verified optimization can be demonstrated without relying on fabricated success metrics.

---

## 18. Demo Acceptance Scenario

The MVP should be considered demonstrable when the following scenario works end to end.

1. A developer executes a coding task through the supported gateway.
2. TokenPilot records the requests, usage, latency, failures, and estimated cost.
3. A deterministic detector identifies a plausible inefficiency.
4. A Meta Muse model investigates the evidence and proposes a concrete optimization.
5. The developer launches a benchmark using the original and alternative configurations.
6. Both configurations start from the same repository revision and use the same acceptance criteria.
7. TokenPilot records actual benchmark usage and test outcomes.
8. The dashboard compares cost, runtime, retries, and correctness.
9. The alternative is classified as a verified optimization only if it satisfies the defined criteria.
10. The project report includes the evidence and methodology behind the result.

If the alternative performs worse, TokenPilot must report that honestly. A negative experiment is still useful engineering intelligence.

---

## 19. Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Coding tools expose incomplete usage data | Start with a controlled gateway and clearly label missing fields. |
| Attribution is unreliable | Preserve unattributed events and allow user correction. |
| Provider prices change | Use versioned pricing and explicit calculation provenance. |
| LLM analysis produces unsupported claims | Validate evidence references and calculate metrics deterministically. |
| Recommendations are too generic | Require a concrete action and validation procedure. |
| Benchmark runs are not comparable | Pin initial revisions, acceptance criteria, and relevant configurations. |
| Generated code is unsafe | Use isolated execution with restricted permissions. |
| Model variability makes savings uncertain | Repeat trials and report variability where practical. |
| Hackathon scope expands excessively | Prioritize the complete core loop over additional integrations. |

---

## 20. Final Product Definition

TokenPilot is an AI engineering cost intelligence system that connects model usage to the outcomes of software development.

Its value is not merely showing developers where their money goes. It identifies the behaviors and workflow patterns driving expenditure, explains them using evidence-grounded AI analysis, and gives developers a way to test whether a proposed change actually improves the cost and effectiveness of their work.

The product is successful when a developer can move from an observed cost problem to a validated engineering improvement within the same application.

**The defining capability is the closed loop: observe → explain → experiment → verify → improve.**

Model routing, local inference optimization, team analytics, and broader integrations are extensions of that core—not substitutes for it.
