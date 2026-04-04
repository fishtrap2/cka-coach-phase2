# cka-coach (Phase 1 Prototype)
>
> Vision: Why leave the cluster to read a book or watch a video, shouldn't the cluster teach you inside it?
>
> The idea of cka coach comes from someone who was walking thru the Linux Foundation - CKA course - LFS258
> And two things become crystal (Painpoints from a PM perspective):
> 
>          1) that the LFS258 course and K8S in general is very fragmented and hard to learn AND
>          2) that given the year 2026, why learn to be a CKA w/o also learning some AI fundamentals at the same time.
>
> I came up with the Everything Lives Somewhere (ELS) Model as a way of maintaining a mental model of the system
> instead of trying to hold a dozen layers in your head at the same time. I find it easier to learn this way and included
> an AI model which (in context) explains (constrained to the ELS Model) exactly what is going on inside the student's own cluster.
>
> There are hints of how I did this built inside the application, because I did it from the perspective of a Product
> Manager (and longtime networker and executive) using modern product operating model techniques to buid this (Currently Phase1) prototype.
> It represents easily 50-60 iterations thus far to simply build the first release of a prototype.
> To do this I am wearing many hats:
> 
>      *PM+Designer+Coder+Tester+Version Control+++++*
>
> I'm also attempting to incorporate AI as I go And I also want to be a CKA so I'm working on that too.
> I just thought it would be easier to run thru LFS258 *while* having a working ELS model and agent to help me through.
> 
> Learn Kubernetes *system* the way it actually works — through layers, evidence, and explanation.

![ELS Model](docs/images/els-model.png)

## 🚀 What is cka-coach?

cka-coach is a **Gen2 AI system** for Kubernetes learning.

Instead of just prompting an LLM, it:

1. **Collects real cluster state**
2. **Maps it into the ELS layered architecture**
3. **Uses AI to explain the system clearly in context and thru the ELS model**

This makes it useful for:
- CKA exam preparation
- platform engineering learning
- understanding how Kubernetes actually works under the hood

Every component in Kubernetes “lives somewhere” in this stack.

cka-coach helps you:
- locate components
- understand relationships
- debug from the correct layer

---

## 🖥️ Features

### ELS Console (Dashboard)
- visual layered model of the cluster
- real-time state inspection
- health indicators
![ELS Model](docs/images/ELS.png)

### 🔍 Expand (evidence)
- raw data from the cluster:
  - pods
  - nodes
  - events
  - runtime
  - networking

### 🤖 Explain (AI)
- grounded in deterministic ELS mapping
- explains through multiple lenses:
  - Kubernetes
  - AI / Agents
  - Platform Engineering
  - Product Thinking
![ELS Model](docs/images/Explain.png)

### 🧠 Deterministic + AI (Gen2)
- Python computes the system model
- LLM explains it
- avoids hallucinated architecture

---

## 🏗️ Architecture (Gen2)

cka-coach is built around three layers:

1. **State Collector**
   - gathers structured cluster + node evidence

2. **ELS Core (deterministic)**
   - maps evidence to architecture layers

3. **AI Explanation Layer**
   - explains what is happening

The dashboard shows this architecture so students can understand both:
- Kubernetes
- and how modern AI systems are built
![ELS Model](docs/images/Phase1-Arch.png)

---

## ⚙️ Getting Started

### 1. Clone the repo on your CP node

```bash
git clone <repo-url>
cd cka-coach
git checkout v0.4.0
---
python -m venv venv
source venv/bin/activate

pip install -r requirements.txt
export OPENAI_API_KEY=your_key_here

Start the Dashboard
streamlit run ui/dashboard.py

Then open browser to: (Note: LFS258 has you open up the (in my case GCP VM) FW ALOT so this should work and port 8501 s/b available:
<Your CP external IP>:8501

OR you can consume cka-coach  from CLI:
python src/main.py ask "where does kubelet run?"
