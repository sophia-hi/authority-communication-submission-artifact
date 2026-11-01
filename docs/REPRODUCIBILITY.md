# Reproducibility guide

This guide covers the archived data, reported analyses, and executable prototype. Run commands from the repository root using Python 3.13; the archived analyses used Python 3.13.5. The analysis and prototype dependencies use separate environments.

## Verify the archived records

Follow the [download and extraction instructions](../data/RAW_DATA_RELEASE.md), then run:

```bash
python3 scripts/validate_artifact.py
```

This standard-library validator checks the 3,570-run experimental grid, run identities, file checksums, and recorded model settings. For the four recovered runs, it also checks the links between failed attempts and completed results, recovery chronology, request counts, and recorded costs and token usage. Missing cost and usage values remain marked as unknown.

## Reproduce reported results

Create the analysis environment and run the full reproduction:

```bash
python3 -m venv .venv-analysis
source .venv-analysis/bin/activate
python -m pip install -r requirements-analysis.txt
python scripts/reproduce_analysis.py
```

The command fits score Poisson models M1/M2 and exact-optimal logit models M3/M4, checks the logit implementation, rebuilds Tables 1, A2, and A3, runs four process analyses, and checks reported counts and contrasts. It uses the archived data and rewrites the output CSVs without making provider requests.

The score sample contains 1,428 runs from 102 scenarios. The logit sample contains 1,400 runs from 100 scenarios; scenarios 73 and 85 have optimal outcomes in all 14 endpoint runs and are excluded from logit. Process analyses retain all 102 scenarios. [Model definitions](../analysis/README.md) explain the specifications, samples, standard errors, and organizational comparisons.

## Run a minimal autonomous example

Create the prototype environment:

```bash
python3 -m venv .venv-prototype
source .venv-prototype/bin/activate
python -m pip install -r src/requirements.txt
```

Preview one Mutual task using scenario 1 at rho = 1:

```bash
python src/run_live_demo.py --dry-run
```

The preview displays the task and model settings without making requests or writing files. To execute the task with autonomous agents, set your provider key:

```bash
export AUTHCOMM_OPENROUTER_API_KEY="YOUR_OPENROUTER_KEY"
python src/run_live_demo.py --execute-live
```

Live execution makes paid requests to the configured provider. It uses the task generator, role-specific prompts, calculator, and protocol executor in `src/`. One task runs at a time, with up to two concurrent requests for its agents. A model or provider mismatch stops execution for inspection. New model responses and choices may differ from the archived experiment.

| Option | Selection |
| --- | --- |
| `--family` | A scenario from the original 60; default 1 |
| `--rho` | 0, .25, .50, .75, or 1; default 1 |
| `--organization` | Any of the seven code names in the [design guide](DESIGN.md#organizational-arrangements), or `all`; default `mutual` |
| `--out` | A new or empty output directory; default `src/results_live_demo/` |

For all seven arrangements on the selected task:

```bash
python src/run_live_demo.py --organization all --out src/results_live_all --execute-live
```

The output directory contains `demo_schedule.json`, `execution_summary.json`, `progress.jsonl`, and one `demo__*.json` record per task. These runs use the `autonomous_reviewer_demo` dataset name. Each turn's `request_context.request_payload` saves its instructions, inputs, tools, and request metadata. Within this repository, output directories use the `src/results_live_*` prefix.

Exit code 0 means all scheduled tasks reached a terminal outcome. The JSON records contain each task's status, choices, and score. Exit code 3 indicates an incomplete run or a failure requiring inspection. Existing output files are preserved; choose a new or empty directory for another invocation.

## Inspect the prototype

In the prototype environment, run the scripted walkthrough:

```bash
python src/mock_runner.py --families 1 --rhos 0,1 --out results_mock_reviewer_demo
```

It exercises all seven protocols at two rho values using scripted optimal choices, and writes 14 example runs under `src/results_mock_reviewer_demo/`.

The offline tests cover prompts, tool schemas, arithmetic, protocol state, scoring, data validation, provider error handling, and the autonomous entry point with a substitute API:

```bash
(cd src && python -m unittest discover -s tests -v)
```

## Collection code and model settings

[config.yaml](../src/config.yaml) contains the economic seeds and runtime settings. The client defaults and collection entry points use the following request settings:

| Setting | Value |
| --- | --- |
| Requested model | `openai/gpt-6-luna` |
| Recorded endpoint model | `openai/gpt-6-luna-20260922` |
| Provider route | OpenAI through OpenRouter; fallback disabled |
| Reasoning effort | `low` |
| Temperature | Omitted from the request |
| Maximum output tokens | 16,000 per request |
| API key environment variable | `AUTHCOMM_OPENROUTER_API_KEY` |

The three batch entry points cover the collected panel:

| Entry point | Scheduled runs |
| --- | ---: |
| [`run_420_parallel_stress.py`](../src/run_420_parallel_stress.py) | First 420 runs from the original 60 scenarios |
| [`run_remaining_1680.py`](../src/run_remaining_1680.py) | Remaining 1,680 runs from those scenarios |
| [`run_extension_42.py`](../src/run_extension_42.py) | 1,470 runs from the additional 42 scenarios |

All collected runs use replicate 0. Four tasks in the 1,680-run batch were completed through a documented exceptional recovery after infrastructure failures. The [archive guide](../data/RAW_DATA_RELEASE.md) traces those attempts. The packaged entry points use repository-relative paths; archived records retain their collection-time version identifiers.

With the prototype environment active, check the saved schedules and model routing against the included generators:

```bash
python scripts/verify_collection_schedule.py
```

To verify the original scenario construction and assignment, run `python src/seed_design.py` and `python src/counterbalance_search.py`. The [extension guide](../data/extension_42/README.md) provides the corresponding commands for the additional 42 scenarios.

## Prompt records

The [prompt export](../data/agent_facing_review/AGENT_FACING_TEXT.md) contains stable instructions, initial assignments, action schemas, and runtime notice examples. Historical prompt evidence is stored as follows:

| Record | Contents |
| --- | --- |
| `result.economic_family` | Economic inputs used to render role-specific task materials |
| `result.prompt_integrity` | Instruction and dossier hashes for each role |
| `turns[*].request_integrity` | Hashes of request inputs, tools, and payloads |
| `turns[*].request_context` | Null in all 30,153 saved model turns from the 3,570 final runs |

Full historical request text was not captured. Role-specific material is regenerated by `role_dossier` in [`agent_interface.py`](../src/agent_interface.py) using the economic inputs, rho, organization, and role; `system_instructions` supplies the stable instructions. Regenerated text can be compared with the saved hashes. Request histories can be reconstructed using the executor and the saved model outputs, calculations, messages, and delivery records.
