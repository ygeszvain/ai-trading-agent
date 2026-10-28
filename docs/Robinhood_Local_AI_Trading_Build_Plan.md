# Robinhood Local AI Trading Product Build Plan

**Prepared for Randy — October 26, 2026**  
**Purpose:** A product specification and engineering handoff for Codex.  
**Initial deployment:** One owner, one local installation, one dedicated trading account.  
**Initial authorization:** Build and test software using fixtures and simulated money. Live trading remains disabled.

## 1. Recommended decision

Build a local research and trading system that uses LM Studio for language-model inference, a separately deployed application for continuous operation, and Robinhood's official external-agent MCP integration for brokerage access.

Use Codex as the software engineer. Do not make a general-purpose coding session the unattended trading engine. The trading application needs durable state, a deterministic risk engine, an order ledger, reconciliation, monitoring, and a controlled learning pipeline.

The initial investment approach should be low-frequency, long-only trading in a small approved universe of liquid, unleveraged US-listed ETFs. Research can operate continuously; new orders initially operate only during regular market sessions. Expand to individual equities, event-driven strategies, or additional assets only after separate validation.

The objective is **positive economic returns after trading and operating costs, within an owner-approved loss and exposure envelope**, evaluated against appropriate benchmarks. Autonomy and learning are engineering capabilities; neither establishes a profitable trading edge.

**Recommended progression:** offline simulator → local model integration → historical research → forward paper trading and broker shadowing → supervised live pilot → bounded autonomous trading → controlled strategy adaptation.

This specification recommends a design. No brokerage account, hardware, entitlement, model installation, trading capital, or profitable strategy has been verified for this project.

## 2. Verified platform facts and remaining unknowns

The following are public-documentation findings verified on October 26, 2026. Recheck them during implementation and before live activation.

| Subject | Verified fact | Engineering implication |
| --- | --- | --- |
| Robinhood external integration | Robinhood documents external-agent onboarding through Streamable HTTP MCP at https://agent.robinhood.com/mcp/trading. [S1] | Implement a broker adapter against the supported interface. |
| Account access | External agents can read information across Robinhood accounts, while trading is restricted to the dedicated account. [S1] | Apply an additional account allowlist and redact unrelated accounts before model access. |
| Approval defaults | Robinhood says approvals default on for built-in agents and off for external MCP accounts; MCP approval access is still rolling out. Some orders can require approval regardless. [S2] | Enforce application controls independently and inspect the actual broker setting. |
| Current trading scope | Current documentation covers long equities, options, and crypto. It lists equity review, placement, and cancellation tools. [S2] | Discover the authenticated tool schemas; enable equities only for version one. |
| Built-in automation | Robinhood's current Agents page labels Agent Loops “Coming soon.” [S3] | Own scheduling in this application. Do not depend on a promised rollout. |
| Codex local inference | Official OpenAI documentation supports OSS mode with LM Studio as the local provider. [S4] | Codex can use local inference for development; verify the installed CLI. |
| LM Studio runtime | LM Studio documents OpenAI-compatible Responses, tool use, and schema-constrained chat output. [S5–S7] | Use explicit capability tests for the selected model and server version. |
| LM Studio authentication | LM Studio supports API tokens; its documentation says authentication is not required by default. [S8] | Bind locally and enable supported authentication before handling financial data. |

**Important distinction:** Robinhood's in-app model picker and a locally hosted LM Studio model are different integration paths. The reviewed sources do not establish that Robinhood's in-app picker accepts an arbitrary localhost model endpoint. Use an external application connected through MCP for the local-model design.

**Do not assume:** an official paper brokerage account, historical tick-data depth, specific rate limits, client-order idempotency, streaming fills, refresh-token longevity, unattended authorization renewal, fractional limit-order support, protective-order support, or access to built-in Agent Apps from an external client. Discover and document each capability. An order-review tool is not a paper brokerage.

If an essential capability is absent, preserve the adapter interface and continue simulation. Document the limitation before proposing a different broker. Never substitute unofficial Robinhood scraping or credential-based reverse-engineered APIs.

## 3. Product outcome and first-version scope

### Primary user outcome

The owner can supervise a locally running system that gathers permitted information, evaluates a small number of investment strategies, proposes or executes allowed orders, explains its evidence, measures economic results, and improves through a traceable evaluation process.

### Version one includes

- A single-owner local dashboard and command-line interface.
- A local LM Studio connection with no automatic cloud-model fallback.
- Historical replay and forward paper trading using an internal simulator.
- A broker gateway that can later connect to Robinhood through official authentication.
- A source registry, provenance records, and point-in-time data queries.
- One simple numerical strategy plus cash and passive comparison portfolios.
- Structured research summaries with source links and an explicit abstain option.
- A deterministic portfolio and order risk engine.
- A durable decision journal, order state machine, fill ledger, and reconciliation.
- A strategy experiment registry with frozen champions and evaluated challengers.
- Operator controls, alerts, incident recovery, and reproducible evaluation reports.

### Deferred scope

Options, short selling, margin borrowing, leveraged or inverse funds, crypto, futures, event contracts, extended-hours orders, high-frequency trading, autonomous code deployment, online reinforcement learning with live capital, public SaaS access, and management of other people's money.

The architecture may accommodate additional asset adapters later. That does not authorize enabling those assets.

### Success has two separate meanings

**Operational success:** Orders and account state remain controlled and auditable through outages, retries, model failures, and restarts.

**Investment success:** Forward results show a credible advantage after costs, against appropriate benchmarks, with acceptable risk and uncertainty.

An operationally excellent product may discover that its strategies have no investable edge. Staying in cash or simulation is an acceptable outcome.

## 4. Optimize the right objective

Do not use “maximize profit” as the sole prompt or reward. Unconstrained profit optimization can favor leverage, concentration, excessive turnover, or hidden tail risk.

Use this priority order:

1. Satisfy account permissions, owner policy, data requirements, and portfolio constraints.
2. Estimate returns and costs using validated numerical methods.
3. Prefer candidates with robust forward or out-of-sample results.
4. Optimize a predeclared risk-adjusted objective within the feasible set.
5. Abstain when expected advantage is insufficient or evidence is unreliable.

Maintain two economic views:

- **Strategy net P&L:** Trading gains, distributions, and cash income, less applicable trading fees, spread, slippage, and other attributable execution costs.
- **Product net P&L:** Strategy net P&L less allocated data, compute, energy, hosting, and other operating expenses.

Track pre-tax results and tax-related information separately. A tax estimate requires owner-supplied assumptions; it is not a substitute for tax advice.

For actual trading, fill prices already incorporate spread and execution slippage. Attribute these costs against a reference price for analysis; do not subtract them a second time from the actual cash ledger. Record explicit fees and income once. Report time-weighted returns for strategy comparisons and money-weighted returns where owner cash flows make that view useful.

Capital scale matters. As an illustration, USD 100 per month of recurring operating expense equals 12% of USD 10,000 of capital per year, or 1.2% of USD 100,000, before taxes or compounding. These are hypothetical costs, not vendor quotes. Track development effort and hardware depreciation separately so a small apparent trading edge is not mistaken for a viable business.

The research score can combine net excess return, drawdown, downside risk, turnover, and uncertainty penalties. Freeze its definition before tuning. Do not let the model change the score after observing results.

Compare against both:

- A passive benchmark appropriate to the selected instruments and time horizon.
- A benchmark matched to the strategy's actual exposure, volatility, and cash allocation.

A strategy holding 75% cash should not be judged only against a fully invested equity portfolio. Report absolute returns and risk-matched comparisons together.

## 5. Architecture and trust boundaries

Use one repository and a modular application. Keep privileged execution in a separate process and security context from research.

~~~mermaid
flowchart TD
    D["Permitted data sources"] --> I["Ingestion and provenance"]
    I --> P["Point in time store"]
    P --> A["Local analysis and numerical signals"]
    A --> T["Typed trade intent"]
    T --> R["Deterministic risk and authorization"]
    R --> E["Execution gateway"]
    E --> B["Robinhood MCP"]
    B --> L["Order and fill ledger"]
    L --> C["Reconciliation and monitoring"]
    C --> R
    P --> V["Research and evaluation"]
    L --> V
    V --> G["Strategy promotion gate"]
    G --> A
~~~

All inference in the analysis box uses the configured local model. Research and execution can operate without an LLM when the relevant workflow is deterministic.

### Development plane

Codex edits source, runs tests, builds documentation, and prepares reviewable changes. It uses synthetic or sanitized fixtures. Its environment does not contain live broker tokens or access to the privileged executor socket.

### Research plane

The research worker can retrieve approved information, read sanitized data, run bounded experiments, and propose structured strategy revisions. It has no broker-write tools, arbitrary shell tool, unrestricted SQL tool, or authority to change live policy.

### Execution plane

The executor holds the broker authorization. It accepts typed, authorized requests from a narrow interface, repeats risk checks, reserves capacity, submits supported orders, and reconciles outcomes. It does not execute generated code or follow free-text instructions.

### Control plane

Owner-authenticated controls manage mode, approved capital, account and symbol allowlists, policy versions, strategy activation, pauses, and authorization expiry. The model cannot use this interface.

### Monitoring plane

A watchdog supervises process health, reconciliation age, data freshness, authorization, exposure, and outstanding orders. Protective monitoring must continue even when research or the local model is unavailable.

Separate processes are the minimum implementation boundary. Use separate operating-system users or container permissions for execution where practical. A collection of prompts in one privileged process does not enforce separation.

## 6. Recommended implementation stack

| Layer | Initial choice | Reason |
| --- | --- | --- |
| Core language | Supported Python release, pinned for the project | Numerical research and typed service implementation |
| Environment | uv and a committed lockfile | Reproducible dependency resolution |
| API and validation | FastAPI and Pydantic | Narrow typed control and application interfaces |
| Application persistence | PostgreSQL with SQLAlchemy and migrations | Durable jobs, ledger state, reservations, and transactional locks |
| Historical analytics | Parquet and DuckDB | Efficient local time-series research |
| Numerical models | NumPy, pandas or Polars, scikit-learn | Transparent baselines and conventional predictive models |
| Model access | HTTP adapter to LM Studio | Keeps the application independent of a model vendor |
| Broker access | Supported MCP client library behind a Robinhood adapter | Authentication and schema-driven integration |
| Orchestration | Explicit state machines and persistent jobs | Bounded behavior and recoverable workflows |
| Dashboard | FastAPI templates with minimal browser JavaScript | Fast single-owner delivery |
| Packaging | Local services; Docker Compose for infrastructure where useful | Simple deployment without orchestration overhead |
| Quality | pytest, property tests for invariants, type checks, linting | Meaningful coverage of money and failure paths |
| Telemetry | Structured redacted logs, metrics, trace IDs | Diagnosis and auditability |

Do not add Kubernetes, Kafka, a fleet of independent debating agents, a vector database, or a complex agent framework to the first milestone. Add infrastructure only when measured requirements justify it.

Use Decimal or integer money units for cash, quantities, fees, and order calculations. Define rounding and precision by instrument. Numerical feature computation may use floating point, with explicit conversion before money calculations.

The OpenAI Python client can be used as a protocol-compatible HTTP client for LM Studio; that does not require routing requests to OpenAI. A small direct HTTP adapter is also acceptable. Check actual endpoint compatibility rather than assuming all OpenAI features exist locally.

## 7. Repository structure and application interfaces

The following is a proposed layout, not an existing repository.

~~~text
README.md
AGENTS.md
pyproject.toml
uv.lock
.env.example
config/
  simulation.yaml
  live.template.yaml
  source_registry.yaml
docs/
  product_spec.md
  architecture.md
  capability_matrix.md
  data_contracts.md
  risk_policy.md
  evaluation_protocol.md
  operator_runbook.md
  decision_log.md
src/trading_agent/
  config/
  contracts/
  ingestion/
  data/
  llm/
  research/
  features/
  strategies/
  portfolio/
  risk/
  execution/
    broker_interface.py
    simulator.py
    robinhood_mcp.py
    reconciliation.py
  learning/
  jobs/
  audit/
  monitoring/
  api/
  cli/
tests/
  unit/
  property/
  integration/
  replay/
  adversarial/
  fixtures/
migrations/
reports/
~~~

Define interfaces before implementing provider-specific behavior:

- **MarketDataProvider:** historical bars, quotes, corporate actions, instrument identity, data coverage, and freshness.
- **DocumentProvider:** source documents with availability metadata, revisions, usage rights, and entity mappings.
- **LLMProvider:** capability probe, structured extraction, bounded research synthesis, and usage/latency telemetry.
- **Strategy:** deterministic feature inputs, target portfolio output, version, required datasets, and eligibility.
- **RiskEngine:** policy and state inputs; allow, reject, or reduce decisions with machine-readable reasons.
- **BrokerAdapter:** capabilities, account snapshot, orders, fills, review where supported, submission, cancellation, and reconciliation.
- **ExperimentRunner:** immutable dataset manifest, configuration, splits, candidate versions, and metrics.
- **PromotionPolicy:** permitted change class, evidence checks, authorization, activation, and rollback.
- **Notifier:** operational alerts with delivery status and no trading authority.

Internal interface names are application design choices. They are not claims about exact Robinhood endpoint or argument names.

## 8. Data strategy and the meaning of all available information

Interpret “all available information” as **all permitted, useful, timely information that demonstrably improves decisions within budget**. Adding sources without evaluating availability, cost, and incremental value can make results worse.

Start with price, liquidity, account state, corporate actions, and calendar data. Add text and alternative data through measured experiments.

| Data family | Proposed source or route | Main use | Priority and constraint |
| --- | --- | --- | --- |
| Account, positions, orders, fills | Official broker interface | Reconciliation and tradable capacity | Required for any live mode |
| Bars, quotes, spreads, liquidity | Verified broker coverage or one licensed vendor | Features, fills, execution controls | Required; establish history and entitlements |
| Instruments and corporate actions | Broker plus licensed reference data | Splits, dividends, symbol changes, delistings | Required for credible historical results |
| Exchange calendar and halts | Trusted calendar/reference sources and broker state | Session control and halt handling | Required |
| SEC filings and structured facts | SEC EDGAR APIs [S9] | Financial changes, material events, company research | Add after numerical baseline |
| Economic series and historical vintages | FRED and ALFRED routes [S10] | Regime features and macro context | Use vintage-aware data |
| Company announcements | Official investor-relations pages | Event verification | Respect published availability and permitted use |
| News and earnings material | Licensed provider or verified broker entitlement | Event classification and risk context | Store timestamps and document rights |
| Options activity and analyst estimates | Licensed provider, if separately authorized | Additional context for later equity strategies | Validate access, lag, costs, and contribution |
| Public disclosures and alternative data | Lawful, licensed sources | Test specific hypotheses | Disclosure time matters more than event date |
| Social sentiment | Authorized API/feed | Weak corroborating signal | Optional, manipulation-prone, never sole trade trigger |

Do not assume a Robinhood Agent App subscription includes external API access, historical export, model-training rights, or redistribution rights.

### Source registry

Each source must declare owner, base domain, authentication method, allowed operations, symbols covered, data frequency, expected lag, rate limits, monthly cost, storage rights, model-processing rights, retention, outage behavior, and point-in-time suitability.

Never purchase data or create subscriptions automatically. The initial paid-data budget is zero until an owner approves a provider and spending cap.

### Data contract

Store, where applicable:

- Source ID, document/event ID, instrument ID, and symbol valid at the time.
- Event time, publication time, provider dissemination time, first observed time, ingestion completion time, and revision time.
- Original timezone, normalized UTC timestamps, sequence numbers, and market session.
- Raw content or licensed reference, content hash, source URL, and license/retention flags.
- Original values, later corrections, quality flags, missingness, and parsing version.
- Whether historical availability is observed, provider-verified, or reconstructed.

For live decisions, information is available only after the system has actually received and processed it.

For historical backfills, retain the true present-day ingestion time. A separately evidenced historical availability timestamp may support replay. Never backdate first-observed timestamps to manufacture a historical record. Mark reconstructed lag assumptions and downgrade conclusions when original dissemination cannot be established.

### Storage and point-in-time controls

1. Preserve raw observations and revisions without overwriting their history.
2. Normalize instrument identities, timestamps, units, and quality checks.
3. Build features with an explicit as-of cutoff.
4. Store the exact input manifest for every decision and experiment.
5. Filter retrieved documents by availability before passing them to the LLM.
6. Enforce cutoffs in query code, not by asking the model to ignore future information.

Use unadjusted prices for actual execution and ledger reconciliation. Define adjusted series consistently for features and total-return research. Avoid counting dividends both in an adjusted return series and again as cash income.

Use filing acceptance/dissemination time rather than the financial period end. Use originally available macroeconomic releases rather than later revised values. Model public-trade disclosures from their publication time rather than the earlier transaction date.

### Data additions require an ablation

For every new feed, compare the same strategy with and without that information. Record changes in return, risk, turnover, coverage, latency, and cost. Remove feeds that do not earn their operational and financial burden.

## 9. LM Studio and Codex setup

### Two distinct local-model uses

**Development:** Codex can use a model served by LM Studio to write and test software.

**Production runtime:** The trading application independently calls LM Studio to analyze source material. It does not need an interactive Codex session to stay open.

The model and context used for coding can differ from those used for research. Both may run on the same machine if resource limits and latency tests pass.

### Verified setup pattern

The following reflects the documented interfaces, but Codex must verify installed versions and supported flags before changing local configuration. [S4–S7]

~~~bash
lms server start --port 1234
codex --oss --local-provider lmstudio -m "<EXACT_LOADED_MODEL_ID>"
~~~

Choose an already installed model ID rather than silently initiating a large download. Load and configure the model in LM Studio first. Keep the inference endpoint on loopback unless a private authenticated network is explicitly configured.

Suggested application settings:

~~~dotenv
LLM_PROVIDER=lmstudio
LM_STUDIO_BASE_URL=http://127.0.0.1:1234/v1
LM_STUDIO_MODEL_ID=
LM_STUDIO_API_TOKEN=
LLM_ALLOW_CLOUD_FALLBACK=false
TRADING_MODE=simulation
LIVE_TRADING_ENABLED=false
~~~

These are proposed application configuration keys, not existing product settings. Store real tokens in an appropriate secret store or protected runtime injection mechanism. The example file contains blanks only.

LM Studio documents that Codex uses the Responses endpoint. The application can use schema-constrained chat completions where the selected local model passes compatibility tests. Do not assume that support for one endpoint proves support for another.

### Model selection and hardware

Do not choose a financial model based on parameter count or marketing alone.

Benchmark two or three locally feasible candidates on:

- Extraction accuracy from filings and news.
- Structured-output validity and tool-argument accuracy.
- Citation fidelity and distinguishing evidence from inference.
- Abstention when evidence is absent or conflicting.
- Resistance to instructions embedded in retrieved material.
- Coding and test performance for the development profile.
- Peak memory, context length, tokens per second, first-token latency, and sustained thermal load.

LM Studio's Codex documentation provides gpt-oss-20b as one example. That is a compatibility starting point, not evidence of trading skill. [S5]

Record model ID, weight hash, model license, quantization, context setting, server version, sampling settings, and prompt hash. Verify that storage and commercial-use terms fit the intended use.

A laptop is suitable for development and initial research. Unattended trading needs a reliable always-on host, stable networking, protected storage, clock synchronization, and tested restart behavior. Measure existing hardware before recommending a purchase.

### Startup compatibility checks

- Confirm the expected local host and reject accidental cloud URLs.
- Discover loaded model identifiers.
- Probe the required endpoint with a harmless schema request.
- Verify authentication without logging credentials.
- Measure timeout and memory behavior.
- Reject unknown model/version changes until reevaluated.
- Test that cloud fallback is disabled.

A failed model call blocks new model-dependent intents. It must not disable deterministic monitoring, order reconciliation, or previously authorized protective actions.

## 10. Analysis workflow and typed decisions

Use bounded stages rather than an open-ended autonomous conversation.

1. **Select candidates:** A numerical screener identifies instruments within the approved universe.
2. **Assemble evidence:** Retrieve a bounded set of relevant, timely, permitted records.
3. **Extract facts:** The local LLM produces structured events, source references, uncertainty, and conflicts.
4. **Compute signals:** Numerical code computes features, estimates, and portfolio targets.
5. **Challenge the thesis:** A structured review looks for missing evidence and invalid assumptions.
6. **Produce an intent:** The strategy emits a typed target or an explicit HOLD.
7. **Evaluate risk and authorization:** Deterministic code decides whether any executable order is allowed.
8. **Execute and reconcile:** Only the gateway interacts with broker write tools.

These are logical roles. The first release does not require multiple independently running LLM agents.

The LLM should help interpret language and organize evidence. It should not calculate authoritative account balances, create prices, size orders from prose, or treat its own stated confidence as a calibrated probability.

### Example decision contract

~~~json
{
  "schema_version": "1",
  "intent_id": "generated-by-application",
  "decision_at_utc": "2026-10-26T14:00:00Z",
  "expires_at_utc": "2026-10-26T14:01:00Z",
  "account_alias": "approved-agent-account",
  "instrument_id": "fixture-instrument",
  "action": "HOLD",
  "target_weight": "0.00",
  "strategy_version": "baseline-v1",
  "model_version": "configured-local-model-hash",
  "data_snapshot_id": "immutable-snapshot-id",
  "evidence_ids": ["source-record-id"],
  "rationale_summary": "Available evidence does not establish sufficient advantage.",
  "invalidation_conditions": ["required-data-missing"],
  "forecast": null,
  "risk_policy_version": "paper-policy-v1"
}
~~~

Use strict schemas, forbid additional fields, validate enums and Decimal ranges, and reject absent required evidence. Identity, time, policy, and account bindings are supplied or verified by the application rather than trusted from model output.

Store concise rationale and source evidence for audit. Do not depend on hidden model reasoning or require private chain-of-thought logs.

Set maximum retrieval requests, documents, model calls, context length, runtime, and retries per research job. Exhausting a budget produces HOLD or an incomplete research record.

## 11. Strategy research roadmap

### Baselines first

Implement cash and a passive portfolio, including the actual or conservatively modeled cash yield and instrument distributions. Use the same capital, evaluation periods, and cost conventions as the active strategy.

### First strategy

Implement one transparent trend or momentum strategy with volatility-based exposure constraints on a small paper ETF universe.

The hypothesis is that persistent multi-session movement may contain useful information after costs. Treat that as a testable hypothesis, not an assumed market property.

Specify before tuning:

- Instrument eligibility and historical universe construction.
- Price/return definitions and missing-data handling.
- Lookback candidates, rebalance schedule, and holding horizon.
- Position and aggregate exposure limits.
- Entry, exit, no-trade, and cash conditions.
- Estimated transaction costs and turnover budget.
- Benchmarks, splits, evaluation metrics, and rejection criteria.

Use a small prespecified parameter grid. Do not mine hundreds of variants until one looks profitable.

### Later experiments

- Mean reversion in a separately defined universe and regime.
- Numerical forecasts using linear or tree-based models.
- Macro or volatility regime conditioning.
- Filings or earnings event classification after point-in-time stock data is available.
- News-based risk filters before news-driven directional trading.
- A constrained combination of already validated strategies.

Start LLM output as a research annotation or risk-context feature. Compare it against an otherwise identical numerical strategy. If it does not improve forward decisions, retain the LLM for research and reporting while keeping trading deterministic.

### Avoid initial online reinforcement learning

Market rewards are delayed, noisy, nonstationary, and affected by selection and execution. A live account is an expensive and poorly controlled training environment.

Reinforcement learning can be a later offline research track with a realistic simulator, explicit risk constraints, independent evaluation, and a substantial reason to prefer it over simpler methods. It is not a first-release requirement.

## 12. Self-learning with bounded authority

Self-learning should mean **measurable, versioned improvement from new evidence**.

| Mechanism | What changes | Initial permission |
| --- | --- | --- |
| Operational memory | Incident notes, evidence quality, execution observations | Automatically append verified records |
| Outcome tracking | Matured labels, P&L attribution, prediction errors | Automatic with correction history |
| Parameter research | Thresholds and lookbacks in experiments | Automatic within compute and trial budgets |
| Predictive-model fitting | Offline statistical model weights | Research only |
| Strategy allocation | Weights among previously approved strategies | Disabled initially; later bounded by a preapproved envelope |
| Local LLM adaptation | Fine-tuning or adapters | Separate research project |
| Live code, risk policy, tools, assets, or capital | Application behavior and financial authority | Owner-reviewed change required |

Writing a journal does not update model weights. Fine-tuning is different from parameter optimization. The dashboard must identify which learning mechanism is active.

### Learning loop

1. Capture the exact evidence, decision, strategy version, and available portfolio state.
2. Reconcile actual fills and costs.
3. Wait until the specified forecast or holding horizon has matured.
4. Calculate outcomes and attribution, including HOLD decisions and failed opportunities.
5. Detect data quality problems and regime changes.
6. Generate a bounded number of challenger hypotheses.
7. Evaluate challengers with the frozen protocol.
8. Forward-test qualified challengers in shadow mode.
9. Promote only through the permitted change class and evidence gate.
10. Continue monitoring the prior champion and retain a rollback path.

Examples of useful learning include discovering that a news provider is too late, that a feature loses value after costs, or that a strategy should be disabled in a particular validated regime.

Do not infer that the last losing trade proves the strategy is wrong. Do not infer that a recent win validates a new rule.

### Labels and counterfactuals

Define labels by horizon, price convention, cost model, and availability. A five-session return is unavailable until that horizon completes.

Distinguish actual realized outcomes, marked hypothetical outcomes, and modeled counterfactuals. A rejected trade's simulated profit is not a realized missed gain. Include delisted instruments, losing positions, no-trade decisions, and incomplete observations.

### Champion and challenger policy

Freeze the live champion's code, dependencies, prompts, model, features, and parameters for each evaluation window.

A promotion package includes:

- Hypothesis and permitted change class.
- Exact code/configuration diff.
- Dataset and model manifests.
- All attempted trials, including failures.
- Split definitions and frozen objective.
- Historical and prospective results with uncertainty.
- Risk and operational regression results.
- Turnover, cost, and capacity estimates.
- Activation authorization and rollback target.

Initially, every promotion to live requires owner approval. A later release may automatically promote narrowly defined parameter or allocation changes inside an already approved envelope. That authority must be explicitly enabled, expire, and leave risk policy and capital unchanged.

Automatically pausing a failing strategy is allowed by a preapproved rule. Inventing and activating a replacement strategy is a separate authority.

## 13. Risk policy and simulation defaults

The values below are **illustrative engineering defaults for paper testing**. They are not personalized investment limits or a recommendation to commit capital. Live limits require owner approval and may need to be tighter.

| Control | Paper starting value | Required behavior |
| --- | --- | --- |
| Paper capital | USD 100,000 | Clearly labeled simulated money |
| Live capital authorization | USD 0 | No live submissions possible |
| Permitted assets | Approved long-only unleveraged equities/ETFs | Reject all other asset classes |
| Account and symbol allowlists | Empty until configured | No implicit “all accounts” or “all symbols” |
| Maximum position | 5% of sleeve NAV | Include existing and pending exposure |
| Maximum gross exposure | 25% of sleeve NAV | Long-only net exposure cannot exceed gross |
| Maximum positions | 5 | Reserve slots for pending entries |
| Maximum single order | 2% of sleeve NAV | Smaller than target size; no unbounded slicing |
| Maximum pending entry exposure | 5% of sleeve NAV | Count every unfilled buy |
| Minimum cash | 75% of sleeve NAV | Do not credit pending sale proceeds prematurely |
| Daily planned turnover | 10% of sleeve NAV | Protective exits use separately defined exceptions |
| Daily loss trigger | 1% of sleeve NAV | Freeze new risk and attempt cancellation of outstanding entries |
| Trailing drawdown trigger | 5% from cash-flow-adjusted high-water mark | Pause strategy and require a review |
| Maximum entry spread | 15 basis points | Fresh executable quote required |
| Maximum quote age | 5 seconds | Expired or delayed quotes block orders |
| Maximum portfolio/order-state age | 10 seconds | Unknown state blocks additional risk |
| Maximum modeled participation | 0.1% of relevant traded volume | Use a documented volume window |
| Order type | Share-based limit, DAY | Only when authenticated capability permits |
| Maximum working entry age | 60 seconds | Request cancellation; remain reserved until confirmed |
| Maximum entry order count | 10 per session | Failed/canceled attempts still consume a bounded budget |

Define sleeve NAV using the approved account and capital scope, including cash, marked positions, accrued items where available, and reconciled liabilities. Adjust loss calculations for external flows. Track both account equity and strategy-attributable results.

These percentages are consistent with a deliberately low-exposure paper portfolio. Exposure can exceed a target through price movement. Freeze increases and use the preapproved rebalance policy; do not silently widen the limits.

Additional requirements:

- Check account eligibility, instrument tradability, minimum quantity, precision, settlement restrictions, buying power, and applicable day-trading rules using current broker information.
- Do not hardcode a remembered regulatory threshold or assume account treatment.
- Size from current verified prices and conservative cost estimates.
- Reserve cash for pending buys at a worst permitted fill price plus applicable costs.
- Treat sells as reducing exposure only when supported by actual holdings and reconciled order state.
- Apply correlated-instrument and sector caps when the universe expands.
- Reject zero, negative, nonfinite, or inconsistent prices and quantities.
- Block new risk on unresolved broker discrepancies, expired authorization, stale data, excessive clock skew, unknown tool schemas, or failed audit writes.
- Never average down or increase size because the model wants to recover a loss.

A loss trigger is a control trigger, not a guaranteed maximum loss. Gaps, halts, failed cancellations, outages, and overnight moves can exceed the threshold. A stop-market order can slip and a stop-limit order can fail to fill.

### Entry controls and protective actions are different

A spread or daily-entry-count restriction should not accidentally prevent an authorized risk-reducing exit. Define a narrow protective-action policy with its own price, state, and execution requirements.

The default response to a risk breach is to block new exposure, attempt to cancel entry orders, reconcile, and alert. Do not automatically liquidate every holding unless that emergency policy has been separately approved and tested.

When disconnected, the application cannot guarantee cancellation or protection. Outstanding broker orders and existing holdings remain real exposures.

## 14. Robinhood gateway and execution correctness

### Capability discovery

Use the official endpoint and a maintained MCP client. Follow the authenticated server's discovery and supported authorization flow. MCP authorization guidance covers metadata discovery, OAuth protections, and resource-bound tokens. [S11]

The owner completes broker authentication through the broker's approved flow. Never request a password, MFA code, authorization code, or access token in a coding prompt or chat.

Record a sanitized capability matrix covering account identity, permissions, tools, schemas, order types, quantities, sessions, review behavior, approvals, pagination, rate limits, error semantics, and reconciliation methods.

The public equity-tool examples are review_equity_order, place_equity_order, and cancel_equity_order. Confirm actual names and argument schemas through authenticated discovery. [S2]

Do not grant every discovered tool to the model. Unknown tools remain denied until classified and reviewed.

### Broker-adapter contract

The adapter must return:

- Account identity bound to the approved local alias.
- Timestamped cash, buying power, positions, and open orders.
- Normalized order status with the raw broker status retained.
- Stable broker order and fill identifiers where supplied.
- Partial-fill quantities, prices, fees, and corrections.
- Explicit capabilities and structured, classified errors.

Retries must distinguish safe reads from mutations. Apply backoff and rate-limit handling to reads; mutations require a state-specific retry policy.

### Order lifecycle

Maintain persistent states such as:

~~~mermaid
stateDiagram-v2
    [*] --> Proposed
    Proposed --> Rejected
    Proposed --> AwaitingApproval
    Proposed --> Authorized
    AwaitingApproval --> Authorized
    AwaitingApproval --> Expired
    Authorized --> Reserved
    Reserved --> SubmissionPending
    SubmissionPending --> Acknowledged
    SubmissionPending --> Unknown
    Acknowledged --> PartiallyFilled
    Acknowledged --> Filled
    Acknowledged --> CancelPending
    PartiallyFilled --> Filled
    PartiallyFilled --> CancelPending
    CancelPending --> Cancelled
    CancelPending --> Filled
    Unknown --> Reconciling
    Reconciling --> Acknowledged
    Reconciling --> Filled
    Reconciling --> ManualReview
~~~

Broker rejection, expiration, and corrected-fill branches must also be handled. A canceled order may already have a partial fill. A cancellation request is not a cancellation confirmation.

### Submission sequence

1. Obtain fresh positions, buying power, open orders, and quotes.
2. Validate intent expiry, active strategy version, policy, authorization, and account.
3. Calculate the delta from actual holdings, not from the last desired target.
4. Transactionally reserve worst-case cash and exposure.
5. Persist an order intent and submission attempt before the network call.
6. Use broker review when supported, then revalidate anything that became stale.
7. Submit only through the approved gateway path.
8. Persist the broker response and status.
9. Reconcile fills, positions, fees, and order state.
10. Release reservations only as confirmed state permits.

If Robinhood returns a broker approval requirement, preserve it. An application approval cannot override it.

For application-supervised live mode, the approval must bind to the exact account, instrument, side, quantity or target, price constraints, strategy, policy, and expiry. Material changes invalidate approval.

### Idempotency and unknown outcomes

Use a unique local intent key, database uniqueness constraints, serialized account writes, leases, and fencing tokens. These reduce local duplicate submissions.

If the broker supports a client-order idempotency key, use it and verify its documented semantics. If not, do not claim exactly-once execution.

A timeout after submission means the broker may have accepted the order. Mark the result UNKNOWN, retain reservations, query authoritative broker state, and block conflicting submissions. If the outcome cannot be determined safely, require operational review rather than guessing or blindly retrying.

### Reconciliation and exclusive ownership

Only one executor may write to the dedicated account at a time. Disable competing built-in agents, external agents, or scripts on that same account during the pilot.

Treat unexpected manual trades, external deposits, corporate actions, missing orders, and unknown positions as state changes requiring reconciliation. Do not automatically reverse an owner's manual action.

Broker-confirmed state is authoritative for holdings and fills. The local ledger must preserve differences and corrections through append-only events, not rewrite history to make reports match.

## 15. Evaluation and backtesting protocol

### Historical protocol

- Acquire sufficient history to include multiple market conditions; five years is a research target where lawful coverage and instrument history permit.
- Construct the eligible universe using information available at each historical date.
- Include delistings, symbol changes, distributions, and realistic survivorship handling.
- Use chronological walk-forward splits, never random row splits for a temporal trading claim.
- A starting research template is 24 months training, 6 months validation, and 6 months testing, advancing by 6 months where data permits.
- Reserve a final untouched recent holdout outside model and parameter selection.
- Purge training labels whose outcomes overlap later evaluation windows and define any embargo from the label and execution horizon.
- Fit scalers, imputers, feature selection, and calibration using training data only.
- Limit and record all trials, including failed runs and discretionary changes.

The split template is a starting design. Sample size, instrument histories, regime coverage, and signal frequency determine whether it is adequate.

### Critical LLM hindsight issue

A model trained after a historical trading date may already know later earnings, price movements, corporate failures, or economic events. Restricting retrieved documents to the historical date does not remove knowledge stored in its weights.

Therefore:

- Historical LLM-driven trading results can be contaminated even with correct data timestamps.
- Use models with an appropriate documented training cutoff when available.
- Anonymization or masking is a diagnostic, not proof of eliminating leakage.
- Label historical LLM studies as exploratory when contamination cannot be excluded.
- Give preregistered prospective paper/shadow results greater weight.
- Separate text-extraction accuracy from evidence of profitable trading decisions.

### Fill simulation

Replay events in order. An observation cannot generate a fill before it was available to the strategy.

For daily-bar research, a close-based signal ordinarily becomes eligible at a later tradable event; it cannot receive that same closing price without a justified executable design.

Model spread, fees, latency, slippage, volume participation, price gaps, rejected orders, partial fills, and unfilled limits. A bar touching a limit does not prove an order would have filled. When order-book or queue information is unavailable, apply conservative assumptions and disclose the limitation.

Use the same order and risk interfaces in simulation and live execution. Keep the simulator's cash and inventory conservation rules exact.

### Metrics

| Category | Required measures |
| --- | --- |
| Returns | Net total return, absolute net P&L, benchmark excess return, exposure-matched excess return |
| Risk | Maximum drawdown, volatility, downside deviation, expected shortfall, concentration |
| Efficiency | Turnover, exposure, cash allocation, cost per decision, product operating cost |
| Trade behavior | Average win/loss, payoff ratio, holding period, fill rate, no-trade rate |
| Forecasts | Calibration, error by horizon and regime, coverage, abstention quality |
| Execution | Implementation shortfall, quote age, partial fills, rejection and cancellation rates |
| Reliability | Reconciliation lag, unknown orders, downtime, rejected invalid intents |
| Uncertainty | Time-aware confidence intervals, regime sensitivity, trial count and selection effects |

Win rate alone is not an objective. Annualized Sharpe estimates from short, sparse, or dependent samples can be misleading.

### Comparisons and stress tests

Compare cash, passive investment, numerical strategy without an LLM, LLM-assisted variant, and each additional data feature through ablations.

Test at least:

- Historical volatility spikes and broad declines available in the dataset.
- Two to three times modeled execution costs.
- Delayed or absent news and quotes.
- Overnight gaps and halted instruments.
- Alternative but plausible parameter choices.
- Lower liquidity and reduced execution capacity.
- Source corrections and incomplete data.
- Removal of the best-performing short subperiod.

Use block-based resampling where appropriate to preserve temporal dependence. Report uncertainty and economic relevance rather than choosing a single impressive backtest.

### Promotion standards

Prespecify minimum evidence and practical improvement before evaluating candidates. A reasonable initial research rule is to require positive net excess performance after realistic costs, acceptable drawdown, robustness across multiple windows, and an improvement interval sufficiently separated from zero to justify the change. If data cannot support that conclusion, keep the candidate in research.

A minimum of 30 trading sessions of paper/shadow operation can test reliability. It does not establish profitability. A low-frequency strategy may require months and substantially more independent decisions for an investment conclusion.

Maintain separate gates for software reliability, broker integration, and trading evidence. Passing one does not imply passing the others.

## 16. Persistence and audit model

Use migrations and enforce uniqueness and foreign-key relationships.

| Entity | Essential records |
| --- | --- |
| source_registry | Provider, permitted operations, latency, rights, cost, retention |
| instruments | Stable identity, historical symbols, asset class, precision, eligibility |
| raw_observations | Source reference, timestamps, payload hash, revision relationships |
| feature_snapshots | As-of cutoff, source IDs, feature version, input manifest |
| research_runs | Model/prompt versions, evidence, outputs, timing, failure reason |
| strategy_versions | Code/configuration hashes, required data, owner or system authorization |
| decisions | Intent, HOLD or action, targets, rationale, evidence, expiry |
| risk_evaluations | Policy version, state snapshot, pass/fail reasons, calculated limits |
| authorizations | Mode, account, scope, capital cap, expiry, owner identity, digest |
| reservations | Cash, inventory, exposure, order slot, lifecycle, fencing token |
| order_intents | Unique local key, desired action, approval and policy bindings |
| submission_attempts | Request digest, timing, response, unknown status |
| broker_orders | Broker ID, normalized and raw status, cumulative fills |
| fills | Stable fill ID, quantity, price, fees, corrections |
| ledger_events | Cash, position, income, expense, corporate-action entries |
| portfolio_snapshots | Broker and local views, reconciliation status |
| labels | Horizon, maturity, observed vs modeled outcome, corrections |
| experiments | Hypotheses, every trial, splits, dataset and artifact manifests |
| promotions | Evidence, authorization class, activated version, rollback |
| incidents | Trigger, exposure, response, acknowledgment, resolution |

Store timestamps in UTC and retain source timezones. Use America/New_York for exchange-calendar logic and America/Chicago as the default owner display timezone, editable without changing the underlying timestamps.

Audit records must identify which model, data, strategy, policy, and authorization produced an order. Recorded model outputs are the authoritative audit artifact; exact regeneration may differ across hardware or inference implementations even with the same seed.

Apply license retention and personal-data rules. Append-only audit design does not override a source's deletion obligations. Retain lawful hashes, metadata, and derived records when full content cannot be kept.

## 17. Runtime schedule and operational behavior

| Activity | Initial cadence | Conditions |
| --- | --- | --- |
| Source ingestion | Source-appropriate updates | Rate limits and freshness SLAs |
| Daily research | Before the relevant session | Uses only available information |
| Portfolio decisions | One scheduled decision after the first 30 minutes of the regular session | No intraday strategy churn by default |
| Working-order monitoring | Approximately every 5–10 seconds if permitted | Adapt to verified broker limits |
| Portfolio and health checks | At a bounded cadence appropriate to exposure | Independent of LLM availability |
| End-of-session reconciliation | After the regular session plus broker processing allowance | Resolve orders and accounting differences |
| Outcome labeling | When each horizon matures | No premature labels |
| Challenger experiments | Nightly or weekly within resource budgets | No automatic live activation initially |
| Owner digest | Once per trading session | Concise results, exposure, exceptions, next action |

Use exchange calendars, early closes, holidays, and daylight-saving rules. Do not use fixed UTC offsets or assume the host's timezone matches the market.

Starting version one outside regular hours should run research and monitoring, with no new orders. Multi-day holdings create overnight exposure and require an explicitly selected holding policy.

### Operational modes

- **Simulation:** Synthetic or historical events; no broker connection needed.
- **Paper:** Current permitted data; internal simulated orders only.
- **Shadow:** Compare hypothetical decisions with read-only broker state; no submissions.
- **Supervised live:** Owner approves each application intent, subject to any broker approval requirement.
- **Bounded autonomous live:** Approved strategy may act within a time-limited authorization and unchanged envelope.
- **Paused:** New exposure blocked; monitoring and approved protective actions continue.
- **Reconciliation required:** No conflicting orders until authoritative state is restored.

Activation requires all of mode, live-enabled flag, nonzero approved capital, correct account, allowlists, valid policy, active strategy, healthy reconciliation, and an unexpired owner authorization. A single environment variable must not be sufficient.

### Pause and recovery

Provide distinct controls for:

- Pause new trading.
- Cancel outstanding entry orders.
- Perform an approved reduction or liquidation.
- Revoke broker authorization through the official broker controls.

Label these actions separately. A local pause does not remove existing orders or holdings.

After a crash or restored backup, reconcile before allowing new exposure. Initial live pilots require explicit resume after a restart or incident. A later unattended restart policy may be approved only after the behavior is tested and bound to an unexpired authorization.

Automatic health recovery may restart processes. It may not silently reenable expired authority, reset a drawdown high-water mark, or convert paper mode into live mode.

## 18. Dashboard and owner experience

Keep the interface focused on decisions and control.

1. **Overview:** Mode, account alias, allocated capital, cash, positions, orders, exposure, P&L, benchmark comparison, data age, broker connection, and latest successful reconciliation.
2. **Research:** Candidate, evidence links, verified facts, inferred thesis, conflicting information, and why the system traded or abstained.
3. **Approval queue:** Exact intent details, worst permitted exposure, costs, price constraints, expiry, and authorization status.
4. **Learning:** Champion, challengers, trial history, results, uncertainty, promotion status, and rollback.
5. **Operations:** Pause controls, outstanding broker orders, incidents, health, alert delivery, and recovery checklist.
6. **Settings:** Approved account, universe, capital, risk policy, inference profile, sources, spend limits, and authorization duration.

Display simulated and live results with unmistakable mode labels. Always show realized and unrealized P&L separately and identify delayed data.

A chat-like interface may answer read-only questions or draft a proposal. It must route any financial action to the same typed approval and risk path. Do not let natural-language chat become a second execution channel.

Do not require an owner to read implementation logs to understand current exposure. Show what happened, why it mattered, and the required action.

## 19. Security, privacy, and product boundaries

- Use official OAuth/MCP flows and a secret store appropriate to the host.
- Keep broker tokens outside model prompts, source control, generated reports, crash traces, and the coding environment.
- Authenticate the dashboard; bind locally or use an owner-approved private network.
- Enable supported LM Studio API authentication. Validate its compatibility with the chosen client.
- Request the least broker permission available. If the broker provides broader read scope, minimize downstream disclosure locally.
- Treat all retrieved pages, filings, PDFs, social posts, and tool descriptions as untrusted input.
- No retrieved instruction may change policy, tools, accounts, credentials, or capital.
- Use allowlisted tool names and arguments. Do not rely solely on tool “read-only” annotations.
- Separate source-fetching network access from executor network access.
- Enforce outbound destination restrictions where practical and protect against arbitrary URL fetching or local-file access.
- Pin dependencies and review provider/client updates that affect authorization or order behavior.
- Encrypt host storage and backups. Test restore and token revocation procedures.
- Use sanitized fixtures rather than real account data in tests and CI.
- Do not expose the application as a public trading service in version one.

Local inference reduces model-provider data exposure. It does not mean all processing is offline: brokerage calls, data feeds, software updates, and optional telemetry still involve networks. Document actual data flows.

For personal trading, confirm account eligibility, current terms, approved automation access, and data licenses before live use. Before offering the product to others, obtain appropriate legal review of advisory, broker, custody, marketing, and data-redistribution obligations in the intended jurisdictions. Do not build onboarding or revenue assumptions on an unverified exemption.

## 20. Test plan and acceptance evidence

Financial execution warrants meaningful tests. Favor invariants and failure simulation over tests that merely repeat implementation details.

### Accounting and portfolio invariants

- Cash and inventory reconcile with fills and distributions.
- A sell cannot create a short position.
- Duplicate fill events do not duplicate cash or inventory.
- Partial fills preserve the correct remaining reservation.
- Open buys cannot spend the same cash twice.
- Corporate-action and fee corrections remain auditable.
- All portfolio limits account for current positions and pending orders.
- Protective actions cannot accidentally increase exposure.

### Execution and concurrency tests

- Crash before submission, during submission, after broker acceptance, and before local acknowledgment.
- Timeout with unknown broker outcome.
- Retry after delayed broker history.
- Two workers competing for the same account.
- Lease expiry and stale-worker submission attempt.
- Partial fill followed by cancel/fill race.
- Authentication expiry, revoked access, broker rate limits, and schema changes.
- Unexpected manual order or account cash flow.
- Market close, holiday, early close, halt, and gap.

### Model and source tests

- Malformed JSON, extra schema fields, invalid symbols, invented prices, absent evidence.
- Instructions embedded in a news article requesting an order or credential disclosure.
- Conflicting timestamps, duplicated stories, revised data, and unlicensed content.
- Model unavailable, out of memory, too slow, or changed unexpectedly.
- Attempted cloud fallback or unexpected outbound inference request.
- Correct abstention when inputs or expected edge are inadequate.

### Recovery and operator tests

- Pause blocks new risk while monitoring continues.
- Cancel-all-entries reports confirmations and unresolved orders.
- Authorization expiry remains enforced through restarts.
- Restored backup cannot replay previously submitted orders.
- Reconciliation failure raises a visible incident.
- Alert failure is itself visible.
- An owner can identify current exposure and outstanding orders without logs.

Each milestone produces a concise test report, known limitations, and reproducible commands. Do not use a live order to prove a unit test or use successful paper fills as proof of real execution quality.

## 21. Implementation milestones for Codex

Effort estimates below are planning assumptions for one experienced engineer assisted by Codex. They exclude procurement, access delays, and the time needed to demonstrate a trading edge. A functional research/paper product may take roughly 6–10 engineering weeks; credible forward evidence may take substantially longer.

### M0 Environment and feasibility

**Description:** Establish the actual build environment and integration constraints.

**Requirements:** Inspect the target repository, applicable AGENTS.md, runtime, available hardware, installed Codex/LM Studio versions, model availability, and current official documentation. Make a decision log and capability checklist. Use read-only inspection and public documentation; do not authenticate to a financial account.

**Acceptance criteria:** Architecture, repository plan, dependency strategy, local-inference test procedure, unknowns, and milestone backlog are concrete and reviewable. Paper mode is the documented default.

**Consequences / Boundaries:** No account linking, credentials, paid feeds, hardware purchases, model downloads, production changes, or live actions. Preserve unrelated files.

**Estimate:** 1–2 engineering days.

### M1 Offline application and simulator

**Description:** Deliver the first working end-to-end slice.

**Requirements:** Configuration validation, typed contracts, database migrations, deterministic numerical strategy, synthetic replay, risk checks, reservations, order state machine, fill accounting, journal, minimal dashboard, and reports.

**Acceptance criteria:** A clean checkout can run a documented offline demo. The demo produces decisions, simulated orders, a portfolio ledger, and a benchmark report. Cash, inventory, duplicate-event, limit, restart, and unknown-order tests pass. Live submissions are structurally unavailable.

**Consequences / Boundaries:** Fixtures only; no broker secrets or calls. Do not implement a fake success response in a live adapter.

**Estimate:** 1–2 engineering weeks.

### M2 Local model and evidence workflow

**Description:** Add useful local language analysis without financial authority.

**Requirements:** LM Studio adapter, capability probe, strict extraction schemas, source references, document cutoff enforcement, prompt-injection tests, bounded calls, and model-version capture.

**Acceptance criteria:** Valid structured output or explicit failure/HOLD; no order tools available to the model; no cloud fallback. Measured latency and extraction accuracy are reported on a fixed fixture set.

**Consequences / Boundaries:** Do not download new weights or alter global Codex settings silently. Continue the offline path if no compatible local model is installed.

**Estimate:** About 1 engineering week.

### M3 Historical data and research protocol

**Description:** Produce an honest baseline evaluation.

**Requirements:** One approved market-data adapter or imported licensed dataset, instrument/corporate-action handling, point-in-time queries, walk-forward splits, costs, benchmarks, trial registry, and ablations.

**Acceptance criteria:** Reproducible report with dataset manifest, chronological validation, realistic fill assumptions, uncertainty, and explicit leakage limitations. Performance can be negative.

**Consequences / Boundaries:** No paid subscription without an approved budget. No claiming current LLM historical performance proves an edge.

**Estimate:** 1–2 engineering weeks after usable data is available.

### M4 Broker gateway and shadow operation

**Description:** Connect safely to actual broker state when the owner initiates onboarding.

**Requirements:** Official authentication, sanitized schema discovery, account binding, read filtering, current quotes/positions/orders, reconciliation, and gateway classification of mutations.

**Acceptance criteria:** Read-only shadow mode works. Disallowed tools and accounts are rejected by code. The actual capability matrix and broker approval behavior are documented. Submit and cancel operations remain disabled in this mode.

**Consequences / Boundaries:** Account authorization is an owner action, not an instruction for Codex to handle credentials. Never submit a “test” trade or alter broker settings.

**Estimate:** Several days to 1 engineering week, subject to access and API behavior.

### M5 Forward paper validation and operations

**Description:** Test the full workflow on newly arriving information.

**Requirements:** Frozen strategy, real-time or correctly labeled delayed data, internal simulated execution, daily reconciliation, incident drills, cost attribution, and owner dashboard.

**Acceptance criteria:** At least 30 trading sessions for operational observation, zero unresolved critical execution-control defects, and a prospective performance report. Extend observation when the number of independent decisions is inadequate.

**Consequences / Boundaries:** This period does not automatically authorize live trading. No optimizing against the final test sample or resetting poor history.

**Estimate:** Operational observation overlaps engineering work; minimum elapsed market time exceeds six calendar weeks in many schedules.

### M6 Supervised live pilot

**Description:** Validate broker behavior with explicitly approved limited capital.

**Requirements:** Owner-approved account, universe, capital, limits, per-intent approvals, broker requirements, secrets isolation, monitoring, incident runbook, and tested revocation.

**Acceptance criteria:** Broker-confirmed orders and fills reconcile, observed execution costs are measured, limits remain enforced, and no unknown order is ignored. The owner reviews the results before changing autonomy.

**Consequences / Boundaries:** Building this milestone is not authorization to fund the account, enable live mode, or place any order. No automatic capital increases.

**Estimate:** Several engineering days plus a separately chosen observation period.

### M7 Bounded autonomous operation

**Description:** Remove routine per-intent application approval within an established envelope.

**Requirements:** An unexpired owner authorization, frozen approved champion, tested account isolation, broker-compatible approval settings, exception alerts, independent monitoring, and rollback.

**Acceptance criteria:** The system can operate through scheduled sessions without per-trade owner intervention while enforcing every approved constraint. Any broker-required approval is preserved. Adverse conditions pause new risk.

**Consequences / Boundaries:** Autonomy cannot widen capital, universe, permissions, loss limits, or activation scope. Expired authority does not renew itself.

**Estimate:** About 1 engineering week after previous gates pass.

### M8 Controlled learning and adaptation

**Description:** Automate research and selected previously approved adjustments.

**Requirements:** Matured labels, experiment registry, frozen evaluation protocol, challenger shadowing, promotion packages, drift monitoring, and rollback.

**Acceptance criteria:** Every active change has a version and an authorization chain. Failed candidates cannot influence the champion through hidden prompt or memory edits. Automatic promotions, if enabled, stay within an explicitly approved change class.

**Consequences / Boundaries:** No self-modifying live code, self-issued authority, online LLM training with account access, or exploration using live capital.

**Estimate:** 1–2 engineering weeks initially; ongoing research remains open-ended.

## 22. Configuration contract

This is a proposed starting configuration for Codex to implement and validate. All live fields remain inert.

~~~yaml
app:
  environment: development
  mode: simulation
  display_timezone: America/Chicago
  exchange_timezone: America/New_York

llm:
  provider: lmstudio
  base_url: http://127.0.0.1:1234/v1
  model_id: null
  allow_cloud_fallback: false
  max_calls_per_research_job: 4
  max_documents_per_job: 12
  job_timeout_seconds: 120
  auth_token_secret_ref: null

broker:
  provider: simulator
  robinhood_mcp_url: https://agent.robinhood.com/mcp/trading
  approved_account_id: null
  allowlisted_tool_schema_digest: null

live:
  enabled: false
  approved_capital_usd: "0"
  owner_authorization_ref: null
  authorization_expires_at: null
  require_application_approval_per_intent: true
  resume_after_restart: false

paper:
  initial_cash_usd: "100000"
  synthetic_fixture_universe:
    - TEST_A
    - TEST_B

universe:
  live_instrument_allowlist: []
  allow_short_sales: false
  allow_margin_borrowing: false
  allow_options: false
  allow_crypto: false
  allow_leveraged_or_inverse_funds: false
  allow_extended_hours: false
  allow_fractional_orders: false

risk:
  policy_version: paper-policy-v1
  max_position_nav_fraction: "0.05"
  max_gross_nav_fraction: "0.25"
  max_positions: 5
  max_order_nav_fraction: "0.02"
  max_pending_entry_nav_fraction: "0.05"
  min_cash_nav_fraction: "0.75"
  max_planned_daily_turnover_nav_fraction: "0.10"
  daily_loss_pause_nav_fraction: "0.01"
  trailing_drawdown_pause_fraction: "0.05"
  max_entry_spread_bps: "15"
  max_quote_age_seconds: 5
  max_account_state_age_seconds: 10
  max_clock_offset_seconds: 1
  max_participation_fraction: "0.001"
  max_entry_orders_per_session: 10
  entry_cancel_request_after_seconds: 60
  default_order_type: limit
  default_time_in_force: day
  emergency_liquidation_enabled: false

learning:
  enabled: true
  live_auto_promotion_enabled: false
  max_challenger_trials_per_week: 20
  allowed_live_change_classes: []
  require_matured_labels: true

costs:
  paid_data_budget_usd_per_month: "0"
  allow_paid_subscriptions: false
  operating_cost_reporting_enabled: true
~~~

TEST_A and TEST_B are synthetic identifiers and must never resolve to live instruments. Missing required live values must fail startup in live mode. Unknown keys should be rejected or explicitly versioned.

Add source-specific, instrument-specific, and strategy-specific controls only as those modules are implemented. Do not let environment variables supplied by an LLM bypass owner authorization.

## 23. Consequences / Boundaries for all Codex work

These instructions apply to every build task and should be included in the repository's AGENTS.md.

- Make small, reviewable, reversible changes scoped to the current milestone.
- Read applicable repository instructions and inspect existing work before editing.
- Preserve unrelated files and existing behavior unless a requirement explicitly changes it.
- Use fixtures, simulation, and paper mode by default.
- Never place, cancel, or modify a real order as a development test.
- Never fund accounts, transfer assets, enable margin, change broker approvals, or increase capital.
- Never request or expose passwords, MFA codes, tokens, account numbers, or sensitive logs.
- Keep live broker credentials and execution privileges out of the coding environment.
- Do not use unofficial broker APIs, scraped sessions, credential replay, or browser workarounds.
- Do not install random third-party MCP servers or grant broad tools to the model.
- Do not enable cloud inference, paid feeds, subscriptions, or large downloads without explicit authorization.
- Do not deploy, merge into a protected branch, or change production unless separately instructed.
- Do not silently alter strategy objectives, risk policies, test splits, or failed results.
- Do not claim profitability from a backtest, a short pilot, or model self-reported confidence.
- If a financial or security assumption is unresolved, block dependent live behavior and continue independent offline work.
- Use current primary documentation to resolve protocol uncertainty; never invent tools, fields, flags, or account capabilities.
- On unclear mutation outcomes, preserve state and investigate; do not repeat the mutation blindly.
- Stop at the milestone's boundary with a reviewable result, test evidence, limitations, and the next dependency.
- A roadmap describing a future live stage does not authorize that stage's financial actions.

## 24. Decisions the owner will eventually need to make

Codex can begin M0 and M1 without these answers. Record unresolved values rather than guessing.

| Decision | Starting assumption | Gate affected |
| --- | --- | --- |
| Personal use or public product | Personal use only | Distribution and legal architecture |
| Hardware and installed model | Inspect read-only; do not buy/download | Local inference performance |
| Trading horizon | Daily decisions, multi-session holdings | Data, labels, costs, strategy |
| Initial asset class | Liquid unleveraged ETFs, long-only | Universe and risk |
| Approved live capital | Zero | Any live action |
| Acceptable loss and drawdown | Paper examples only | Live authorization |
| Broker eligibility and access | Unverified | Broker connection/live deployment |
| Data provider and budget | Fixtures/imports; zero paid budget | Historical and forward datasets |
| Overnight exposure | Requires explicit policy before live | Holding and protection behavior |
| Degree of learning autonomy | Research automatic; live promotion manual | Adaptation authority |
| Alert channel | Local dashboard initially | Unattended operation |
| Authorization duration | No active live authorization | Autonomous activation |

Do not block offline implementation to obtain these answers prematurely. Present a concrete configuration and evidence when a decision becomes necessary.

## 25. First runnable slice and definition of done

The first build should demonstrate:

1. Start the application in simulation mode.
2. Load a deterministic synthetic event stream.
3. Generate a numerical signal or HOLD.
4. Apply portfolio and order limits.
5. Reserve capacity and simulate an order/fill lifecycle.
6. Reconcile cash and inventory.
7. Persist an auditable decision and ledger.
8. Display the result and benchmark comparison.
9. Restart without duplicating orders.
10. Reject every attempted transition to live execution.

This slice does not need a profitable strategy, a paid feed, a broker login, or an LLM. It creates the control and measurement foundation needed to judge later intelligence.

A milestone is complete when its acceptance criteria pass, its relevant failure paths are tested, its behavior is documented, and its unresolved limitations are visible.

The full product is ready for bounded autonomous use only after the owner has approved live scope and the applicable operational, integration, and investment-evidence gates are satisfied. If investment evidence remains inadequate, the complete product can remain a research and paper-trading system.

## 26. Copy-ready Codex kickoff prompt

Save this plan in the target repository as docs/Robinhood_Local_AI_Trading_Build_Plan.md, then give Codex the following prompt. The prompt deliberately starts with M0 and M1 rather than authorizing the entire live roadmap.

~~~text
Build the first offline slice of a local AI trading product using
docs/Robinhood_Local_AI_Trading_Build_Plan.md as the governing specification.

Business objective
Create a single-owner system that can eventually research and trade through
Robinhood's official external-agent MCP integration, use LM Studio for local
inference, and improve through evaluated strategy experiments. Optimize
measured economic returns within approved constraints. Do not assume an
investment edge exists.

Current scope
Implement M0 and M1 only. Read the complete plan and applicable AGENTS.md files.
Inspect the existing repository and working tree before editing. Preserve
existing changes. If there is no application, establish the proposed modular
Python structure with the smallest suitable dependency set.

Deliver a complete offline vertical slice:
- Strict configuration with simulation as default and live capital at zero.
- Typed data, decision, policy, order, fill, and ledger contracts.
- Synthetic market fixtures and one simple deterministic strategy plus HOLD.
- Cash and passive benchmark calculations with explicit conventions.
- Deterministic risk checks including existing and reserved exposure.
- Transactional reservations and a persistent order state machine.
- Simulated partial fills, cancellations, duplicate events, and unknown outcomes.
- Cash/inventory reconciliation and a durable audit trail.
- Minimal local dashboard or CLI report.
- Database migrations, reproducible setup, and a documented offline demo.
- Meaningful tests for accounting, limits, retries, concurrency, and restart.
- Explicit failures for every attempted live-mode activation.

Document actual environment facts, architecture decisions, unresolved
capabilities, and the next milestone. Use small reviewable changes. Run the
checks appropriate to these components and report their results honestly.

LM Studio and Robinhood
Do not assume a particular local model is installed. Record the intended
LM Studio adapter and local-only inference constraints for M2. Keep the
Robinhood implementation as an explicitly unavailable adapter until its
approved milestone. Do not fake successful broker calls or attach live
broker-write tools to the coding agent.

Consequences / Boundaries
This request authorizes software implementation and offline tests only.
Do not connect to a financial account, handle live credentials, place/cancel
orders, move money, enable live mode, change broker settings, buy data,
subscribe to services, download model weights, expose a public service,
deploy production changes, or modify unrelated files.
Do not use unofficial Robinhood APIs or browser automation workarounds.
Keep cloud inference disabled.
Do not widen risk limits or change evaluation objectives to make tests pass.
If a fact or interface is uncertain, consult current primary documentation,
record the uncertainty, and block only the dependent work.
If a mutation outcome is unknown, investigate before retrying.
Stop after M0 and M1 are implemented and verified; leave a concrete handoff
for M2 and identify any owner decisions needed later.

Completion response
Summarize what works, what changed, tests run and results, remaining limitations,
exact offline run commands, and the next milestone. Make no profitability claim.
~~~

### Prompt pattern for later milestones

For each later milestone, specify its description, requirements, acceptance criteria, dependencies, and the same Consequences / Boundaries. Identify whether the instruction authorizes only code implementation or also a particular external action. Never infer financial authorization from a request to implement code.

## 27. Primary sources

All sources below were reviewed on October 26, 2026. Platform behavior, rollout, and account access can change. Public documentation does not establish the owner's account-specific eligibility.

- **[S1] Robinhood — Onboarding an external agent.** Official MCP endpoint, client onboarding, account access, and dedicated-account context.  
  https://robinhood.com/us/en/support/articles/onboarding-an-external-agent/

- **[S2] Robinhood — Trading with your agent.** Current trading scope, approval behavior, tool catalog, and broker controls.  
  https://robinhood.com/us/en/support/articles/trading-with-your-agent/

- **[S3] Robinhood — Agents.** Built-in agent experience, external MCP access, and current Agent Loops rollout wording.  
  https://robinhood.com/us/en/agents/

- **[S4] OpenAI — Advanced Configuration.** OSS mode, local-provider selection, and Codex configuration.  
  https://learn.chatgpt.com/docs/config-file/config-advanced

- **[S5] LM Studio — Codex integration.** Local Codex setup and Responses endpoint compatibility.  
  https://lmstudio.ai/docs/integrations/codex

- **[S6] LM Studio — Tool Use.** Model-requested functions and application-managed tool execution.  
  https://lmstudio.ai/docs/developer/openai-compat/tools

- **[S7] LM Studio — Structured Output.** JSON-schema-constrained chat completions and model capability considerations.  
  https://lmstudio.ai/docs/developer/openai-compat/structured-output

- **[S8] LM Studio — Authentication.** API tokens and authentication settings.  
  https://lmstudio.ai/docs/developer/core/authentication

- **[S9] US Securities and Exchange Commission — EDGAR APIs.** Official submissions and XBRL data access.  
  https://www.sec.gov/search-filings/edgar-application-programming-interfaces

- **[S10] Federal Reserve Bank of St Louis — FRED API.** FRED/ALFRED series, release, and vintage-data routes.  
  https://fred.stlouisfed.org/docs/api/fred/

- **[S11] Model Context Protocol — Authorization.** Current official HTTP authorization specification.  
  https://modelcontextprotocol.io/specification/latest/basic/authorization

All architecture, milestones, example limits, budgets, research protocols, and estimated effort in this plan are proposed engineering choices rather than statements that the referenced platforms provide those controls.

