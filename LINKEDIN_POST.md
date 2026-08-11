I built a small tool to test a supply-chain risk that comes from AI hallucination: "slopsquatting."

The idea: when an LLM writes code, it sometimes imports a package that sounds real but doesn't exist. Attackers have caught on — they register those exact hallucinated names on PyPI/npm with malware inside, betting developers will copy-paste AI-generated code (or let an AI agent auto-install dependencies) without checking.

So I built a detector: it takes code Claude generates for common tasks (PDF parsing, S3 uploads, JWT refresh, WebSocket clients, etc.), extracts every import, and checks each one against the real PyPI/npm registries.

Result on this run: 0 out of 8 generations hallucinated a package — every import (pdfplumber, boto3, requests, ws, etc.) was real. Reporting that straight, not cherry-picking: current frontier models are noticeably better at this than the numbers I've seen in earlier research on the topic.

But "the model didn't do it this time" isn't the same as "the risk is gone." The attack only needs one hallucinated import to slip through once — which is why the fix isn't "trust the model more," it's the same discipline as any untrusted input: verify package names exist, pin dependencies, lock your builds, and never let an AI coding agent auto-install whatever it just imagined.

Code + writeup: [link]

#cybersecurity #AI #supplychainsecurity #appsec
