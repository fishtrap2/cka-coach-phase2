import os

# --------------------------
# Model selection (From OpenAI itself)
# --------------------------
# This is the default model used by cka-coach for explanatory output.
# CKA-COACH (as of v.0.4.0 or "Phase1")  has a few distinct layers:
#
# --> User interaction layer — CLI / Streamlit dashboard
# --> Reasoning layer — answer Kubernetes questions, explain concepts, compare options
# --> Retrieval layer — search indexed docs / notes / YAML / KB content
# --> Structured output layer — generate clean tables, hints, exam-style answers, JSON
# --> Optional agent/tool layer — inspect cluster state, run kubectl-derived workflows, summarize outputs
#
# Given that split, different models fit different jobs.
#
#Best overall architecture choice
#
#For a production-quality CKA Coach, I would use:
#
#      gpt-5.4 as the main reasoning model
#      gpt-5.4-mini for faster/cheaper interactive UI turns
#      text-embedding-3-small or text-embedding-3-large for RAG / semantic search
#      gpt-4.1 or gpt-4.1-mini when you want strong instruction following and predictable structured output without paying for full reasoning
#      gpt-4o only if you want image or screenshot understanding, such as analyzing Kubernetes diagrams, dashboards, or screenshots of terminal output/UI states
#
# Recommendation:
# - use a faster/smaller model for interactive dashboard "Explain" clicks
# - use a larger model later only for deeper analysis modes if needed
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.4")

# --------------------------
# Prompt size control
# --------------------------
# We intentionally cap how much context is sent to the model.
#
# Why:
# - reduces latency
# - lowers cost
# - improves focus
# - avoids drowning the model in repeated cluster text
MAX_CONTEXT_CHARS = int(os.getenv("MAX_CONTEXT_CHARS", "1800"))
