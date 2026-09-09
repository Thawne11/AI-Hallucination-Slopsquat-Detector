# Does hallucination precede registration?

Whether a hallucinated package name was invented by a model *before* somebody registered it. That ordering is what separates slopsquatting from ordinary typosquatting, and it is usually assumed rather than measured.

## Registration rate by candidate set

| Set | Registered | Checked | Rate |
|---|---|---|---|
| hallucinated | 0 | 10 | 0.0% |
| variants | 2 | 48 | 4.2% |
| control | 11 | 120 | 9.2% |

## Registered candidates

| Name | Set | First release | After model release? | Risk |
|---|---|---|---|---|
| `json2schema` | control | 2023-06-17 | no | MEDIUM 38 |
| `json-csv` | control | 2013-07-12 | no | LOW 10 |
| `json-yaml` | control | 2016-01-15 | no | MEDIUM 45 |
| `parserconfig` | control | 2021-08-31 | no | LOW 15 |
| `async-http` | control | 2015-05-01 | no | MEDIUM 38 |
| `yaml-cache` | control | 2017-05-09 | no | MEDIUM 45 |
| `client-router` | control | 2013-08-08 | no | MEDIUM 45 |
| `limit-logger` | control | 2022-06-21 | no | MEDIUM 28 |
| `batchupload` | control | 2017-06-16 | no | MEDIUM 30 |
| `token-limit` | control | 2026-06-29 | yes | MEDIUM 20 |
| `proxy-server` | control | 2014-09-26 | no | MEDIUM 38 |
| `jstopdf` | variants | 2019-03-08 | no | MEDIUM 48 |
| `node-grpc-client` | variants | 2018-09-06 | no | MEDIUM 20 |

## The result is not evidence, and here is the arithmetic

The hallucinated set returned 0 registrations. That is **not** a finding. At the control base rate of 9.2%, the chance of seeing zero hits in 10 draws is **38%** -- so this outcome is exactly what you would expect if hallucinated names were registered no differently from any other plausible name.

To detect even a *doubling* of the base rate would take roughly **226 distinct hallucinated names** per group. This corpus has 10. The experiment is underpowered by more than an order of magnitude, and knowing that number is the actual result here: it converts "we should generate a bigger corpus" from an instinct into a requirement.

## What the control set did establish

About **1 in 11 plausible-sounding package names is already registered** (9.2% of 120 checked). That baseline did not exist before and is useful on its own: any claim that hallucinated names get squatted has to beat it, and the namespace is far more crowded than an intuition would suggest.

Every registered candidate found here predates both model releases, so none of them show the hallucination-then-registration ordering. They are ordinary packages whose names a model drifted towards -- itself worth noting, since it means hallucinations often land near real but obscure names rather than in empty space.


## Caveats that would change the number

- **The control set may be biased towards existing names.** It is built by recombining common tokens, which produces obvious names like `proxy-server` and `json-csv` that were likely claimed years ago. A fairer control would match the hallucinated set's distinctiveness, not just its vocabulary.
- **Model release dates stand in for training cutoffs**, which are not precisely published. The real cutoff is earlier, so anything registered after release was certainly not in training data. This biases against finding an effect rather than towards one.
- **Two models, both small and local.** Names that larger or more widely-used models hallucinate are the ones actually worth squatting, and none of those are represented here.

