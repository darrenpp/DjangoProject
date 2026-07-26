# Regulatory AI and ML operating model

The platform's AI is a governed **decision-support layer**, not an autonomous regulator. It sits above Django, PostgreSQL, approved analytics, workflows, and the document repository. It must not receive unrestricted database access, approve a registration, change a legal record, or replace a Registrar, Board, legal, or clinical decision.

## Implemented local capability

- **Authoritative RAG:** Staff answers retrieve from approved platform knowledge (policies, FAQs, fee/pathway guidance, published guidelines, and approved operational sources) and return source links where available.
- **Regulatory AI router:** An ADK-ready declarative supervisor classifies a request for the Data Quality, Registration, Workforce Analytics, Policy/Document, Compliance, or Report agent. Its tool contract is read-only, scoped to the caller's Nursing, Medical, or authorised shared-admin access, and explicitly disallows direct database/LLM access and record changes. A future ADK or gateway integration must enforce this contract before invoking a tool.
- **Staff record assistance:** authorised staff can request bounded individual-record summaries through existing role-scoped, read-only tools. Cross-office access is blocked and personal data is redacted before an answer or history entry is retained.
- **Aggregate workforce ML:** explainable, local planning projections use approved aggregate Nursing and Medical intelligence only. They describe coverage, assumptions, limits, and confidence; they do not expose individual records or make staffing/registration decisions.
- **Data-quality advisory:** staged import records can be scored for completeness, possible duplicate risk, and compliance-review risk. Scores create review suggestions only; they never promote, merge, correct, or delete registry data.
- **Fast response path:** deterministic scoped answers, cached aggregate intelligence, the existing local model/RAG path, and the optional Redis worker keep common staff requests responsive without bypassing governance.

The default local generation model remains a configurable Ollama model. A model change is a controlled deployment decision, not automatic "learning" from user conversations.

## Safe operating workflow

1. Keep source material authoritative. Update policies, FAQs, fees, pathways, and published guidelines through their normal approval process.
2. Rebuild the knowledge index after a material approved-source change:

   ```powershell
   python manage.py build_ai_knowledge_index
   ```

3. Ask focused, office-scoped questions, for example: "For Nursing Council, list the checks before approving an ATP renewal, with sources."
4. Treat each response as decision support. Verify cited sources and complete the normal workflow; do not use an AI response as automatic approval, legal advice, or clinical advice.
5. Review data-quality and workforce outputs in the appropriate queue/dashboard. A human reviewer must validate any action before official records are changed.

## Evaluation and model promotion

Before upgrading the local generation model, evaluate real, non-sensitive staff questions across Nursing, Medical, and Admin scopes. The acceptance set checks correctness, source relevance, privacy/redaction, and cross-scope blocking.

```powershell
# Inspect the configured cases without calling a model.
python manage.py evaluate_staff_ai --dry-run --scope all

# Evaluate a candidate installed Ollama model with an authorised staff account.
python manage.py evaluate_staff_ai --username <staff-username> --ollama-model <candidate-model> --strict
```

`--strict` makes the evaluation fail unless every required check passes. Retain the JSON report and obtain the required operational approval before changing model configuration. Do not train on raw chats, disciplinary information, or raw registry data by default. `REGULATORY_ML_ALLOW_TRAINING` is false by default; any future training needs an approved, redacted dataset and documented model-governance review.

## Aggregate ML planning runs

Create a read-only planning snapshot after approved analytics refreshes:

```powershell
python manage.py run_regulatory_ml_pipeline --scope all --json
python manage.py run_regulatory_ml_pipeline --scope nursing --output ml_evaluations/nursing-planning.json --strict
```

The command never writes registry records, changes workflows, or trains on chats/registry data. `--output` is optional and is constrained to the platform media directory. Schedule it only through an approved job runner and review source coverage and limits before using a forecast in policy or workforce planning.

Check the active local model, RAG, and aggregate-ML safety configuration with:

```powershell
python manage.py ai_model_status
```

## Cache and asynchronous operation

Aggregate ML responses have a bounded local cache (`REGULATORY_ML_CACHE_SECONDS`). For approved background jobs, enable the existing Redis worker configuration and run:

```powershell
python manage.py run_ai_worker
```

The worker is for queued, bounded AI tasks. It does not grant broader data access, replace workflow approval, or authorise training.

## Mandatory safeguards

- Use only authoritative approved sources; ask for and verify citations.
- Preserve read-only, role-scoped access: Nursing and Medical private data remain separated, and professionals access only their own records.
- Redact personal data in AI context, logs, evaluations, and displayed answers unless an authorised bounded record tool explicitly permits a safe field.
- Keep imports staged: validate, score, review, approve, then promote through existing governance.
- Do not feed raw chats, registry records, complaints, disciplinary files, or uploaded certificates into a training dataset by default.
- Make no automatic regulatory, legal, clinical, disciplinary, or licensing decision from an AI/ML output.

## Optional infrastructure - not deployed by this change

The platform is intentionally not claiming that the following infrastructure is running. Each needs separate hosting, security, monitoring, backup, cost, and operations approval:

| Optional component | Potential role |
| --- | --- |
| FastAPI AI gateway | A separately deployed, authenticated service boundary for AI workloads. |
| Qdrant | A production vector database alternative or complement to the local RAG index. |
| Apache Airflow | Scheduled, audited analytics/ML orchestration. |
| Apache Spark | Large-scale historical workforce processing when data volume justifies it. |

Until such infrastructure is approved and operated, use the implemented Django, local RAG/Ollama, aggregate ML, cache, and optional Redis-worker path with the safeguards above.
