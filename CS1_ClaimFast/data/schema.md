# ClaimFast Dataset Schema

## Record Structure

Each JSONL line represents one insurance message and its
manually assigned gold labels.

## Fields

| Field | Type | Allowed Values |
|---|---|---|
| id | string | Unique message ID |
| message | string | Original synthetic message |
| claim_type | string | own_damage, third_party_liability, theft, total_loss, glass_only, not_a_claim |
| urgency | string | high, medium, low |
| policy_number | string/null | Policy identifier |
| incident_date | string/null | YYYY-MM-DD |
| location | string/null | Free text |
| vehicle_reg_no | string/null | Uppercase, no spaces |
| estimated_amount_inr | integer/null | Amount in INR |
| injury_reported | boolean/null | true, false, null |
| police_report_filed | boolean/null | true, false, null |
| notes | string | Internal annotation |

## Example Record

{
  "id": "MSG001",
  "message": "My car was hit by a bike near Andheri. The rider got injured.",
  "claim_type": "third_party_liability",
  "urgency": "high",
  "policy_number": null,
  "incident_date": null,
  "location": "Andheri",
  "vehicle_reg_no": null,
  "estimated_amount_inr": null,
  "injury_reported": true,
  "police_report_filed": null,
  "notes": "Synthetic accident message with injury."
}

## Important Rules

1. Every record must contain all fields.
2. Missing information must be represented by null.
3. IDs must be unique.
4. Dates must follow YYYY-MM-DD.
5. Vehicle registration must be uppercase without spaces.
6. Notes must never be included in the model's final JSON response.
7. Gold labels must be reviewed before evaluation.
