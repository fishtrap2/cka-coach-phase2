import os


#OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5")
MAX_CONTEXT_CHARS = int(os.getenv("MAX_CONTEXT_CHARS", "1800"))

# Keep explanation deterministic-ish for technical coaching
OPENAI_TEMPERATURE = float(os.getenv("OPENAI_TEMPERATURE", "0.2"))
