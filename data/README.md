# Experimental data

The dataset contains **3,570 completed runs**: 102 scenarios × five rho values × seven organizational arrangements. Each scenario is identified by `family_id`.

## Files in this folder

| File or folder | Purpose |
| --- | --- |
| [`combined_exploratory_3570_index.json`](combined_exploratory_3570_index.json) | Main run index, with the path and SHA-256 of each final JSON record |
| [`analysis_ready_3570.csv`](analysis_ready_3570.csv) | One-row-per-run analysis dataset |
| [`combined_exploratory_3570_summary.json`](combined_exploratory_3570_summary.json) | Descriptive summaries by organization and rho |
| [`collection_schedule_3570.json`](collection_schedule_3570.json) | Collection schedule and model routing for all runs |
| [`recovery_lineage.json`](recovery_lineage.json) | Attempt links and file hashes for the four recovered runs |
| [`agent_facing_review/`](agent_facing_review/) | Stable instructions, action schemas, and runtime notice examples |
| [`extension_42/`](extension_42/) | Selection and assignment records for the additional 42 scenarios |

The `combined_exploratory_2100_with_recovery_index.json` and corresponding summary describe the original 60-scenario subset used by the extension runner.

## Download the JSON records

Follow the [archive instructions](RAW_DATA_RELEASE.md) to download and extract the records into this folder. The ZIP contains 3,570 final records and 21 supporting records for four tasks recovered after infrastructure failures. The supporting files comprise eight original failed-attempt records and thirteen technical extracts.

Final records contain economic inputs, model responses, agent messages, actions, calculator calls, outcomes, and resource usage. Prompt and request hashes are also retained. Full historical request text was not captured (`request_context` is null); the [prompt-record guide](../docs/REPRODUCIBILITY.md#prompt-records) explains how task materials are regenerated and checked.

## Costs and usage

The recorded API cost across all attempts totals **USD 71.163407345 in known charges**. This is a subtotal: 67 runs include at least one failed request with unavailable cost or usage. Missing amounts remain marked as unknown. Recovery accounting includes the failed attempts and the completed result for each recovered task.
