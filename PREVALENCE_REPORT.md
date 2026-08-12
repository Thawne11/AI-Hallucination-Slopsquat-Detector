# Slopsquatting Prevalence Study

Real public repos scanned with `slopsquat-scan`, comparing a baseline (control) group against repos with real AI-assisted commits, to see whether phantom dependencies show up in the wild.

| Group | Repos scanned | Successful | With phantom deps | Prevalence |
|---|---|---|---|---|
| baseline | 8 | 8 | 0 | 0.0% |
| ai_assisted | 10 | 10 | 0 | 0.0% |

## baseline
- 194 unique declared dependencies checked across 8 successfully scanned repos
- 0 phantom dependencies found

## ai_assisted
- 337 unique declared dependencies checked across 10 successfully scanned repos
- 0 phantom dependencies found
