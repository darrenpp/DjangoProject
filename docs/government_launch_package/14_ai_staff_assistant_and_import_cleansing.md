# AI Staff Assistant and Import Cleansing Guide

## Purpose

The platform supports a controlled AI layer for two approved purposes only:

1. Staff operational questions for Admin, Registrar, Reviewer, Finance, and Data Quality users.
2. Import filtering and cleansing suggestions before spreadsheet rows are trusted.

Public applicants, graduands, nurses, doctors, CHWs, and other professional users do not receive this staff AI access. They use the normal public AI Helpdesk only.

## Default Mode: Local Offline Assistant

The default setting is:

```text
AI_ASSISTANT_PROVIDER=local
AI_ASSISTANT_EXTERNAL_ENABLED=False
AI_IMPORT_CLEANSING_EXTERNAL_ENABLED=False
```

In this mode the system does not send data outside the server. Staff answers are generated from local rules and live scoped counts. Import cleansing uses local validation rules, aliases, fuzzy matching, missing-field checks, future-date checks, old-date checks, and identifier normalization.

## Optional Mode: OpenAI GPT

OpenAI API use is not treated as a free/offline feature. It requires:

- An OpenAI API key.
- Internet access from the server.
- Approved billing for token usage.
- NDOH ICT approval before any production use.

OpenAI can be enabled only if NDOH ICT approves external API use and the environment variables are configured:

```text
AI_ASSISTANT_PROVIDER=openai
AI_ASSISTANT_EXTERNAL_ENABLED=True
OPENAI_API_KEY=...
OPENAI_MODEL=...
```

Import cleansing through OpenAI remains separately locked:

```text
AI_IMPORT_CLEANSING_EXTERNAL_ENABLED=True
```

This separate switch prevents external GPT use for spreadsheet rows unless ICT deliberately enables it.

## Recommended Free Mode: Ollama Local GPT

For a free live chat model, the recommended first option is Ollama running locally or on an internal NDOH server. Ollama exposes a local API on port `11434`, can run without OpenAI billing, and supports local chat models once those models are downloaded.

Enable only after the runtime and model are approved:

```text
AI_ASSISTANT_PROVIDER=ollama
AI_ASSISTANT_OLLAMA_ENABLED=True
AI_OLLAMA_BASE_URL=http://127.0.0.1:11434
AI_OLLAMA_MODEL=llama3.2:3b
AI_IMPORT_CLEANSING_MODEL_ENABLED=False
```

Import cleansing remains separately locked. If approved, turn it on with:

```text
AI_IMPORT_CLEANSING_MODEL_ENABLED=True
```

Check the model server:

```powershell
.\.venv\Scripts\python.exe manage.py ai_model_status
```

If Ollama is not running or the model is missing, the system falls back to the safe local rule-based assistant instead of crashing.

## Optional Mode: Private Offline GPT

The platform also supports a provider slot for a private GPT-style model server. This is the safer path if NDOH wants offline capability because the model can run inside the approved government network instead of sending prompts to an external API.

Enable only after ICT approves the runtime, hardware, model licence, and security controls:

```text
AI_ASSISTANT_PROVIDER=local_llm
AI_ASSISTANT_LOCAL_LLM_ENABLED=True
AI_LOCAL_LLM_BASE_URL=http://127.0.0.1:11434
AI_LOCAL_LLM_MODEL=approved-local-model-name
```

The local model endpoint is expected to provide an OpenAI-compatible `/v1/chat/completions` API. This keeps the platform neutral: ICT may later approve a local runtime such as Ollama, llama.cpp server, or another internally hosted model gateway without changing staff screens.

## Safety Rules

- AI never approves applications.
- AI never writes directly into live practitioner tables.
- AI never runs raw SQL.
- AI never bypasses Nursing Council and Medical Board office separation.
- AI suggestions must be reviewed by staff before being promoted into live registry records.
- Import rows remain staged, validated, reviewed, approved, then promoted.
- Sensitive information should be minimized before external API use.

## Import Cleansing Preview

Use this command to preview cleansing results without changing the database:

```powershell
.\.venv\Scripts\python.exe manage.py ai_cleanse_import_preview --file path\to\workbook.xlsx --sheet "Sheet1" --rows 25 --scope nursing
```

For CSV:

```powershell
.\.venv\Scripts\python.exe manage.py ai_cleanse_import_preview --file path\to\data.csv --rows 25 --scope nursing
```

Optional JSON output:

```powershell
.\.venv\Scripts\python.exe manage.py ai_cleanse_import_preview --file path\to\data.csv --rows 25 --scope nursing --output docs\reports\ai_import_preview.json
```

## What The Cleanser Checks

- Blank or sentinel values such as `N/A`, `TBA`, `UNKNOWN`, and `-`.
- Registration, practitioner, licence, ATP, receipt, and reference number formatting.
- Province aliases such as `NCD`, `SHP`, `ENB`, and `AROB`.
- Unknown or fuzzy province values that require staff review.
- Gender aliases such as `M`, `F`, `Male`, and `Female`.
- Future dates such as accidental `2050` payment dates.
- Old dates before 2000 that need source verification.
- Rows without usable name fields.
- Rows without usable identifier fields.

## Open Source / Offline Options

If NDOH wants a fully offline GPT-style model, the recommended future pattern is to run an internal model server inside the government network, then connect it behind the same provider interface. Examples of possible offline runtimes include Ollama or llama.cpp-style deployments, subject to ICT security review, hardware capacity, model licensing, and data governance approval.

The current implementation is intentionally provider-neutral so the platform can use:

- Local deterministic rules now.
- Free local Ollama GPT when installed and approved.
- OpenAI API if approved.
- A future internal model server without changing the staff workflow.

## What Staff Must Remember

AI is an assistant, not the registrar. It can explain queues, suggest cleansing actions, and flag suspicious imported data. It must not approve applications, issue licences, alter receipt totals, or promote spreadsheet rows into live registry records without human review and audit logging.

## Official OpenAI References For ICT Review

- OpenAI API pricing: https://openai.com/api/pricing/
- OpenAI API data controls: https://platform.openai.com/docs/guides/your-data
- Responses API reference: https://platform.openai.com/docs/api-reference/responses/create
- Structured Outputs guide: https://platform.openai.com/docs/guides/structured-outputs
- Ollama API reference: https://docs.ollama.com/api
- Ollama OpenAI-compatible local API: https://docs.ollama.com/openai
- llama.cpp OpenAI-compatible server: https://www.mintlify.com/ggml-org/llama.cpp/inference/server
