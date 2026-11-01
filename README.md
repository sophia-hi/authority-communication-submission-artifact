# Research artifact: authority and communication among AI agents

This repository accompanies the study of how authority, communication, and commitment shape decisions in AI-agent organizations. It provides an executable prototype of seven organizational arrangements, the recorded experiment, and code to reproduce the paper's statistical and process analyses.

In each task, two branches choose pricing policies to maximize company profit. The arrangements vary agents' information, communication permissions, decision rights, and whether a communicated choice is binding. The dataset contains **3,570 completed runs: 102 economic scenarios × five levels of interdependence (rho) × seven organizational arrangements**. Scenarios are identified as `family_id` in the data. The [experimental design](docs/DESIGN.md) describes the seven arrangements and how the scenarios were constructed.

## Contents

| Folder | What you will find |
| --- | --- |
| [`src/`](src/) | Task generator, agent prompts, organizational protocols, experiment runners, and demonstrations |
| [`data/`](data/) | Run index, analysis dataset, collection schedule, prompt templates, and scenario selection records |
| [`analysis/`](analysis/) | Regression code, coefficients, organizational comparisons, and Tables 1, A2, and A3 |
| [`mechanism-analysis/`](mechanism-analysis/) | Process analyses tracing messages, calculations, and submitted decisions |
| [`scripts/`](scripts/) | Data validation and analysis reproduction commands |
| [`docs/`](docs/) | Experimental design and detailed reproduction instructions |

## Download the code and data

Clone this repository or select **Code → Download ZIP** on GitHub. Run the commands below from the repository folder using Python 3.13; the archived analyses used Python 3.13.5.

The full raw records are available for download from [GitHub Release v1.0.0](https://github.com/sophia-hi/authority-communication-submission-artifact/releases/tag/v1.0.0). Download `authority_communication_records_3570.zip` and place it in the repository folder, then check the download and extract it:

```bash
shasum -a 256 -c data/authority_communication_records_3570.zip.sha256
unzip -o authority_communication_records_3570.zip -d data
```

The archive contains one JSON result record for each of the 3,570 completed runs, plus 21 supporting records documenting four runs recovered after infrastructure failures. [Archive contents and provenance](data/RAW_DATA_RELEASE.md) explains the record types, technical extracts, and source hashes.

## Verify the data and reproduce the results

First, validate the extracted records:

```bash
python3 scripts/validate_artifact.py
```

This checks the complete experimental grid, file checksums, recorded model settings, and the failure and resource records for the four recovered runs.

Then create the analysis environment and reproduce Tables 1, A2, and A3 and the four process analyses:

```bash
python3 -m venv .venv-analysis
source .venv-analysis/bin/activate
python -m pip install -r requirements-analysis.txt
python scripts/reproduce_analysis.py
```

Reproduction uses the archived data and requires no API key or model calls. The command rebuilds the output CSVs and checks the reported counts and contrasts. The main tables are:

- [Table 1: decision score](analysis/score/table_1_score.csv)
- [Table A2: exact-optimal decisions](analysis/optimal/table_A2_optimal.csv)
- [Table A3: selected organizational comparisons](analysis/table_A3_selected_comparisons.csv)

Supporting outputs are in [`analysis/`](analysis/) and [`mechanism-analysis/`](mechanism-analysis/). See the [model specifications](analysis/README.md) for fixed effects, standard errors, and contrasts, and the [process definitions](mechanism-analysis/README.md) for coding and links to individual runs.

## Explore the prototype

Use a separate environment for the prototype dependencies:

```bash
python3 -m venv .venv-prototype
source .venv-prototype/bin/activate
python -m pip install -r src/requirements.txt
```

### Scripted walkthrough

This example exercises all seven protocols for one scenario at rho = 0 and 1. It uses scripted optimal choices to demonstrate the decision rules and scoring, producing 14 example runs without a model call:

```bash
python src/mock_runner.py --families 1 --rhos 0,1 --out results_mock_reviewer_demo
```

Results are written to `src/results_mock_reviewer_demo/`.

### Autonomous agent run

Preview one Mutual task, in which two agents communicate and each chooses its own branch's policy:

```bash
python src/run_live_demo.py --dry-run
```

To execute it, set `AUTHCOMM_OPENROUTER_API_KEY` to your provider key and run:

```bash
python src/run_live_demo.py --execute-live
```

Live execution makes paid model requests using the recorded model settings. New choices may differ from the archived experiment. Results and full request text are saved under `src/results_live_demo/`. Use `--organization all` to run all seven arrangements, or choose a family, rho, and organization. The [autonomous example guide](docs/REPRODUCIBILITY.md#run-a-minimal-autonomous-example) explains these options and the output files.

The [reproducibility guide](docs/REPRODUCIBILITY.md) also provides collection-schedule checks and offline protocol tests.

## Analysis scope

The study is exploratory and was not preregistered. The main regressions use rho = 0 and 1. The score models include 1,428 runs from all 102 scenarios; the exact-optimal logit models include 1,400 runs from 100 scenarios, excluding two with no within-scenario outcome variation. All five rho levels are available in the archive.

The process analyses describe how calculations, communication, and decisions unfold within runs. Submission order is defined by protocol round, with same-round submissions treated as concurrent. [Process evidence](mechanism-analysis/README.md) documents these definitions and their descriptive interpretation.
