import os
from openai import OpenAI
from els import load_els_model
els_model = load_els_model()
# Initialize OpenAI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def build_els_prompt(question: str, els_model: dict, context: str = "") -> str:
    SYSTEM_PROMPT = f"""
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

def ask_llm(question: str, context: str = "") -> str:
    """
    Sends a question to the LLM along with optional cluster context.
    """

    try:

        # 🔥 NEW: load your model
        els_model = load_els_model()

        # 🔥 NEW: build enriched prompt
        prompt = build_els_prompt(question, els_model, context)

        if context:
            prompt += f"\n\nCluster Context:\n{context}"

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


