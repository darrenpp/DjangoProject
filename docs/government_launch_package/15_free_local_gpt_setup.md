# Free Local GPT Setup Guide

## Purpose

This guide explains how to run the Staff AI Assistant without paid OpenAI API usage. The platform now supports a free local model provider, with Ollama as the recommended first option.

The assistant remains restricted to staff roles and is used only for:

- Staff operational questions.
- Data-quality guidance.
- Import-cleansing suggestions before live database promotion.
- Report and workflow guidance.

It must not approve applications, issue licences, update receipt totals, or promote imported rows into live records without human review.

## Recommended Free Option: Ollama

Ollama is practical for this project because it can run locally, exposes a simple chat API, and supports an OpenAI-compatible local API. This means the platform can use a live GPT-style model without sending data to a paid external API.

Suggested setup pattern:

```powershell
ollama pull llama3.2:3b
ollama serve
```

Then configure the platform environment:

```text
AI_ASSISTANT_PROVIDER=ollama
AI_ASSISTANT_OLLAMA_ENABLED=True
AI_OLLAMA_BASE_URL=http://127.0.0.1:11434
AI_OLLAMA_MODEL=llama3.2:3b
AI_IMPORT_CLEANSING_MODEL_ENABLED=False
```

Use a small model first so the laptop or server remains responsive. Larger models may answer better but require more RAM, disk space, and CPU/GPU capacity.

## Health Check

After starting the model server, run:

```powershell
.\.venv\Scripts\python.exe manage.py ai_model_status
```

Expected result:

```text
Configured provider: ollama
Active mode: ollama
Ollama is reachable. Installed models:
- llama3.2:3b
```

If Ollama is not running, the command will warn staff and the platform will keep using the local rule-based fallback assistant.

## Local Knowledge Search

For better answers, build a local retrieval index from the platform's approved knowledge records:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe manage.py build_ai_knowledge_index
```

Enable it with:

```text
AI_ASSISTANT_RAG_ENABLED=True
AI_ASSISTANT_RAG_VECTOR_BACKEND=local_json
AI_ASSISTANT_EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
```

Use `AI_ASSISTANT_RAG_VECTOR_BACKEND=chroma` only if ICT wants the Chroma persistent vector store. The assistant will keep working without the vector index, but answers will rely on the existing local rules and keyword search.

## Import Cleansing

Model-assisted import cleansing is deliberately separated from staff chat.

Keep it off during normal testing:

```text
AI_IMPORT_CLEANSING_MODEL_ENABLED=False
```

Only turn it on after ICT approves the model and import data-handling controls:

```text
AI_IMPORT_CLEANSING_MODEL_ENABLED=True
```

Preview a file without changing the database:

```powershell
.\.venv\Scripts\python.exe manage.py ai_cleanse_import_preview --file path\to\data.xlsx --rows 25 --scope nursing
```

## Other Free / Open-Source Options

Ollama is the easiest first integration. Other options can be used later if ICT prefers them:

- llama.cpp server: useful for a lightweight internal model server with OpenAI-compatible endpoints.
- LocalAI: useful when ICT wants an internal OpenAI-compatible gateway for several model types.
- Hugging Face Transformers: powerful but heavier to package and maintain inside a production web system.

Any option must be reviewed for licensing, hardware requirements, security patching, auditability, and whether the model can be safely used with government registry data.

## Security Position

- No OpenAI API is used unless deliberately configured.
- No external model calls are made in the default setup.
- Public applicants do not receive Staff AI access.
- Nursing Council and Medical Board scope checks still apply before AI context is built.
- Model answers are guidance only; official decisions require registrar workflow and audit logs.

## Official References

- Ollama API reference: https://docs.ollama.com/api
- Ollama OpenAI-compatible local API: https://docs.ollama.com/openai
- llama.cpp OpenAI-compatible server: https://www.mintlify.com/ggml-org/llama.cpp/inference/server
# Optional Free/Private Option: LocalAI (OpenAI-compatible)

If the environment already uses LocalAI, switch the assistant provider to `localai`:

```text
AI_ASSISTANT_PROVIDER=localai
AI_ASSISTANT_LOCALAI_ENABLED=True
AI_LOCALAI_BASE_URL=http://127.0.0.1:8080
AI_LOCALAI_MODEL=<installed model id>
AI_LOCALAI_API_KEY=<if auth required>
```

Then run the normal health check:

```powershell
.\.venv\Scripts\python.exe manage.py ai_model_status
```

Expected output (example):

```text
Configured provider: localai
Active mode: localai
LocalAI is reachable. Installed models:
- gpt-4
```

Keep this in the same scope boundary and human-approval controls as other staff AI modes.
