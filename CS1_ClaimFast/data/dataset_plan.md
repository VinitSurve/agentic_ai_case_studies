# ClaimFast - Dataset Plan

## Dataset Size

Total messages: 80

Development dataset: 20
Test dataset: 60

## Claim Type Distribution

| Claim Type | Development | Test | Total |
|---|---:|---:|---:|
| own_damage | 4 | 14 | 18 |
| third_party_liability | 4 | 12 | 16 |
| theft | 3 | 9 | 12 |
| total_loss | 2 | 6 | 8 |
| glass_only | 3 | 9 | 12 |
| not_a_claim | 4 | 10 | 14 |
| Total | 20 | 60 | 80 |

## Message Characteristics

Include:
- Clear and straightforward messages
- Ambiguous messages
- Hinglish messages
- Spelling and grammatical mistakes
- Missing information
- Multiple incidents
- Injury-related messages
- Theft and glass damage confusion
- Non-claim messages
- Approximate repair amounts

## Data Splitting Rules

1. Development data is used for prompt development.
2. Test data is reserved for final evaluation.
3. Test messages must never be used to tune prompts.
4. Use synthetic messages only.
5. Every message must have a manually defined gold label.

## Output Files

- dev.jsonl
- test.jsonl

## Quality Control

- Verify all 80 records.
- Validate JSON structure.
- Check class distribution.
- Check required fields.
- Review ambiguous cases.
