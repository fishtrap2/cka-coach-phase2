import os

# --------------------------
# Model selection
# --------------------------
# This is the default model used by cka-coach for explanatory output.
#
# Recommendation:
# - use a faster/smaller model for interactive dashboard "Explain" clicks
# - use a larger model later only for deeper analysis modes if needed
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

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
