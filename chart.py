"""Turns report.json into a bar chart summarizing hallucination rate per prompt,
suitable for dropping into a LinkedIn post."""

import json
from collections import defaultdict

import matplotlib.pyplot as plt

with open("report.json") as f:
    results = json.load(f)

by_prompt = defaultdict(lambda: {"samples": 0, "hallucinated_samples": 0})
for r in results:
    stats = by_prompt[r["prompt_id"]]
    stats["samples"] += 1
    if r["hallucinated_packages"]:
        stats["hallucinated_samples"] += 1

prompt_ids = list(by_prompt.keys())
rates = [
    by_prompt[p]["hallucinated_samples"] / by_prompt[p]["samples"] * 100
    for p in prompt_ids
]

fig, ax = plt.subplots(figsize=(10, 6))
bars = ax.barh(prompt_ids, rates, color="#c0392b")
ax.set_xlabel("% of generations containing a hallucinated package")
ax.set_title("AI Hallucination -> Slopsquatting Risk by Coding Task")
ax.set_xlim(0, 100)
for bar, rate in zip(bars, rates):
    ax.text(bar.get_width() + 1, bar.get_y() + bar.get_height() / 2,
             f"{rate:.0f}%", va="center")

plt.tight_layout()
plt.savefig("hallucination_rate.png", dpi=200)
print("Wrote hallucination_rate.png")
