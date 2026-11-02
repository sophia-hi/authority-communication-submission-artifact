# Download and verify the experimental records

Download `authority_communication_records_3570.zip` from [Release v1.0.1](https://github.com/sophia-hi/authority-communication-submission-artifact/releases/tag/v1.0.1) and place it in the repository root. Check the download, extract it, and validate the records:

```bash
shasum -a 256 -c data/authority_communication_records_3570.zip.sha256
unzip -o authority_communication_records_3570.zip -d data
python3 scripts/validate_artifact.py
```

## Archive contents

The ZIP contains **3,591 JSON files**: 3,570 completed-run records and 21 supporting records for four recovered tasks.

| Record type | Count | Contents |
| --- | ---: | --- |
| Final result records | 3,570 | One completed observation per scenario–rho–organization combination |
| Failed-attempt records | 8 | Original records of the first and second attempts for four tasks |
| Confirmed-failure extracts | 4 | Failure status, attempt history, and recovery links |
| Inspection-resolution extracts | 8 | Technical decisions following each failed attempt |
| Recovery-authorization extract | 1 | Scope, timestamp, and prior-record links for the four recoveries |

The final sample comprises 420 records from the first batch, 1,676 regular completions and four recovered completions from the second batch, and 1,470 records from the extension. The 21 supporting records document the attempt history of those four recovered observations.

## Recovery sequence

The recovered tasks are Mutual at scenario 18 / rho .75, scenario 22 / rho .75, scenario 47 / rho .75, and scenario 56 / rho .50. Each follows this sequence:

1. The first attempt stopped after a provider server-overload error. The four `inspection_history/*__inspection_001.json` records contain 44 model responses in total, including four failed responses with unavailable cost or usage.
2. The permitted whole-task retry stopped after connection errors. Each `inspection_history/*__inspection_002.json` record contains six API attempts and no model response. Inspection then confirmed infrastructure failure.
3. An exceptional recovery was authorized for the four incomplete tasks. Each completed recovery fills its original scheduled observation. Resource accounting includes both failed attempts and the completed recovery.

## File provenance and hashes

All 3,570 final records and eight failed-attempt records preserve their original bytes. The thirteen other recovery records are published as **technical extracts**. They retain technical decisions, failure evidence, timestamps, resource totals, and hash links, while omitting operational identities, free-text notes, and references to the collection-wide progress log.

Each extract's `publication` field lists its `source_sha256` and `omitted_fields`. Field paths with dots identify nested fields, such as `inspection_resolution.note`. The [recovery manifest](recovery_lineage.json) records these details and the SHA-256 of each distributed file.

| Hash field | What it identifies |
| --- | --- |
| `recovery_lineage.json`: `sha256` | The distributed file, used for download verification |
| Extract `source_sha256` | The unmodified source from which the extract was prepared |
| Index `original_failed_record_sha256` and [`recovery_record_hashes.json`](recovery_record_hashes.json) | The original confirmed-failure records referenced by the recovery chain |

The validator checks distributed-file hashes, source-hash links, run identities, attempt chronology, and recorded resource totals. To run the recovery checks on their own:

```bash
python3 scripts/verify_recovery_lineage.py
```

Unavailable provider cost and usage remain marked as unknown. The [data overview](README.md#costs-and-usage) explains the known cost subtotal.
