# Literature Review: Preventing cache expansion from temporarily slowing down an application

## Executive summary

Current research into cache management focuses on mitigating the performance penalties—such as latency spikes, memory overflow, and computational complexity—associated with cache expansion and eviction. While caching is essential for maintaining high-speed inference and low-latency response times, the literature reveals a critical tension between aggressive resource optimization and the preservation of system fidelity. Current methodologies range from predictive reinforcement learning [P5] and adaptive budget estimation [P6] to structural algorithmic modifications [P1, P3] and proactive "keepalive" signals [P2]. This report identifies three primary research gaps: the lack of fidelity-aware scaling, the absence of proactive inter-task retention, and the need for holistic, deployment-centric management. Bridging these gaps requires moving from reactive, model-centric optimizations toward multi-objective, system-wide co-design.

## Methods and benchmarks in use

### Methodologies
The technical execution of cache management varies significantly across domains:
* **Predictive and Adaptive Learning:** [P5] utilizes a soft actor-critic reinforcement learning algorithm to manage task offloading and data caching in MEC networks. [P6] employs a lightweight policy network combined with entropy-based thresholding to estimate KV cache budgets.
* **Structural and Algorithmic Modifications:** [P1] introduces a delayed and conditioned caching strategy specifically for diffusion models to optimize the processing pipeline. [P3] utilizes a neural field-based importance sampler paired with a radiance cache acting as a control variate.
* **Defensive and Reactive Strategies:** [P2] implements a client-side "keepalive" mechanism that uses periodic signal transmission to prevent cache eviction in agentic workloads.
* **Systemic Evaluation:** [P4] adopts a structured narrative synthesis to evaluate existing optimization methods across the entire human pose estimation pipeline.

### Benchmarks and Datasets
Evaluation strategies diverge based on the target application:
* **LLM and Language Models:** [P1] uses 7B-scale diffusion models against general language, mathematical, and code-generation benchmarks. [P6] tests across 16 settings using Qwen3 (4B/8B) and Mistral-7B. [P2] focuses on extreme-context scenarios using 40k and 100k token prefixes.
* **Domain-Specific Data:** [P3] employs the Stanford ORB dataset for radiance cache testing in inverse rendering.
* **Systemic/Abstract Frameworks:** [P4] and [P5] do not report specific datasets, focusing instead on systemic frameworks or broader review methodologies.

## How the approaches compare

The primary differentiator among these approaches is the specific trade-off they are designed to manage.

| Paper | Primary Domain | Core Methodology | Key Trade-off |
| :--- | :--- | :--- | :--- |
| **[P1]** | Diffusion Language Models | Delayed/Conditioned Caching | Computational complexity vs. Performance |
| **[P2]** | Agentic Workloads | Client-side Keepalive | Latency vs. Economic cost |
| **[P3]** | Inverse Rendering | Neural Field Importance Sampling | Rendering speed vs. Geometric/Material bias |
| **[P4]** | Human Pose Estimation | Narrative Synthesis | Deployment reliability vs. Benchmarking |
| **[P5]** | UAV-aided MEC | Reinforcement Learning (SAC) | Latency/Energy vs. System cost |
| **[P6]** | Long-context LLMs | Adaptive Budget Estimation | Memory safety vs. Accuracy |

### Synthesis of Comparative Findings
* **Efficiency Gains:** Optimized caching consistently yields significant dividends. [P1] achieves a $O(L^3)$ to $O(L^2)$ reduction in time complexity, while [P6] reduces KV cache size by up to 17.9%. [P2] maintains $\ge$98% cache warmth to secure latency wins.
* **Divergent Priorities:** While LLM-focused papers ([P1, P2, P6]) prioritize speed and memory ceiling management, rendering-focused research ([P3]) prioritizes the recovery of high-quality geometric and material parameters. Similarly, edge-computing research ([P5]) prioritizes multi-objective optimization (latency, energy, and cost) over single-metric gains.

## Open research gaps

### Dynamic Fidelity-Aware Cache Scaling
**Severity: High** | **Evidence: [P1], [P3], [P6]**
Current methods struggle to balance cache size, computational speed, and output accuracy. Aggressive caching to reduce complexity can lead to performance degradation [P1], and low-capacity caches in rendering introduce significant bias [P3]. Existing frameworks like AdaK [P6] focus on memory ceilings rather than maintaining a specific fidelity or accuracy threshold during contraction or expansion.

### Predictive Inter-Task Cache Retention
**Severity: Medium** | **Evidence: [P2], [P5]**
Current strategies are largely reactive or heuristic-based (e.g., LFU/LRU in [P5]). This causes latency spikes and "cold start" costs in agentic workloads [P2] when idle periods trigger cache eviction. There is a lack of proactive mechanisms capable of distinguishing between permanent task termination and temporary human-in-the-loop pauses.

### Deployment-Centric Systemic Cache Management
**Severity: Medium** | **Evidence: [P4], [P5], [P6]**
Research is often model-centric (e.g., KV cache size [P6] or algorithmic complexity [P1]) and fails to account for the holistic reliability required for real-world deployment [P4]. In latency-sensitive edge networks [P5], cache management must account for the entire end-to-end pipeline (acquisition, sensor quality, hardware constraints) rather than just inference-stage memory.

## Suggested research roadmap

1.  **Phase 1: Multi-Objective Fidelity Optimization:** Develop frameworks that dynamically adjust cache precision, density, or lifespan based on real-time error/bias metrics. The goal is to ensure speedups do not cross user-defined quality degradation thresholds.
2.  **Phase 2: Temporal Workload Modeling:** Implement predictive mechanisms that utilize temporal patterns in agentic or edge-computing tasks to distinguish between task completion and pauses, optimizing for both memory footprint and imminent resumption probability.
3.  **Phase 3: End-to-End System Co-design:** Shift toward integrating cache management policies with the entire application pipeline (sensor data acquisition, task offloading, and hardware constraints) to maintain end-to-end reliability in heterogeneous environments.

## References

* [P1] dKV-Cache: The Cache for Diffusion Language Models (2025) — Xinyin Ma, Runpeng Yu, Gongfan Fang
* [P2] Keeping the Cache Warm Pays: Keepalive Economics for Agentic Workloads (2026) — Maxim Khailo
* [P3] Flash Cache: Reducing Bias in Radiance Cache Based Inverse Rendering (2024) — Benjamin Attal, Dor Verbin, Ben Mildenhall
* [P4] Human Pose Estimation for Real-World Deployment: A Review of Methods, Systems, and Applications. (2026) — Lee HA, Zhang Z, Shin SY.
* [P5] Joint Task Offloading and Resource Allocation with Data Caching in UAV-Aided Mobile Edge Computing Networks for Latency-Sensitive Applications. (2026) — Baidya T, Moh S.
* [P6] AdaK: adaptive KV cache budget estimation framework for analyzing long-context large language model inference. (2026) — Shao T.