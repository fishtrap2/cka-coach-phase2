import streamlit as st
import sys
import os
# Ensure src/ is on path
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "src"))
from state_collector import collect_state
from els_mapper import map_to_els
from agent import ask_llm
st.set_page_config(layout="wide")
st.title("🧠 CKA Coach — ELS Live Dashboard")
# Refresh button
if st.button("🔄 Refresh Cluster State"):
    st.experimental_rerun()
# Collect state
with st.spinner("Collecting cluster state..."):
    state = collect_state()
    els = map_to_els(state)
# Layout
cols = st.columns(2)
for i, (layer, data) in enumerate(els.items()):
    col = cols[i % 2]
    with col:
        st.subheader(layer)
        # Show truncated data (avoid overwhelming UI)
        st.text(data[:1500] if data else "No data")
        # Explain button
        if st.button(f"Explain {layer}", key=layer):
            with st.spinner("Thinking..."):
                explanation = ask_llm(
                    f"Explain what is happening in {layer}",
                    context=data
                )
                st.json(explanation)
