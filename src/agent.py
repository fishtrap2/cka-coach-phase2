# src/agent.py
import os
import yaml
from openai import OpenAI  # or whichever LLM client you are using

client = OpenAI()  # make sure your client is configured

# --------------------------
# Load ELS Model
# --------------------------
BASE_DIR = os.path.dirname(os.path.dirname(__file__))

def load_els_model():
    path = os.path.join(BASE_DIR, "src/schemas", "els_schema.yaml")
    with open(path, "r") as f:
        return yaml.safe_load(f)

# --------------------------
# System Prompt
# --------------------------
SYSTEM_PROMPT = """
You are a Kubernetes expert assistant.
Use the ELS (Expanded Layered Stack) model to reason about layers, controllers, kubelet, pods, and container runtimes.
Provide structured JSON output including:
- layer
- explanation
- commands
- next_steps
"""

# --------------------------
# Prompt Builder
# --------------------------
def build_els_prompt(question: str, els_model: dict, context: str = "") -> str:
    prompt = f"""
You are a Kubernetes expert assistant.

You MUST use the provided ELS (Expanded Layered Stack) model to reason.

ELS MODEL:
{els_model}

INSTRUCTIONS:
1. Identify which layer(s) are relevant
2. Explain interactions between layers
3. Provide debug commands from the model
4. If debugging, walk top-down through layers
5. Be explicit about API boundaries

QUESTION:
{question}
"""
    if context:
        prompt += f"\n\nCLUSTER CONTEXT:\n{context}"

    prompt += """

Return your answer as JSON with:
- layer
- explanation
- commands
- next_steps
"""
    return prompt

# --------------------------
# Main ask_llm function
# --------------------------
def ask_llm(question: str, context: str = "") -> str:
    """
    Sends a question to the LLM along with optional cluster context.
    """
    try:
        # Load the ELS model
        els_model = load_els_model()

        # Build the prompt
        prompt = build_els_prompt(question, els_model, context)

        # Call the LLM
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
        )

        return response.choices[0].message.content

    except Exception as e:
        return f"LLM error: {str(e)}"


