# ClaimFast - Labelling Guide

## 1. Purpose

This guide defines how insurance messages should be classified
and how information should be extracted.

All messages must be labelled consistently.

## 2. Claim Types

Allowed values:

- own_damage: Damage to the policyholder's own vehicle.
- third_party_liability: Damage or injury involving another party where an actionable claim against an identifiable responsible third party is established.
- theft: Vehicle or vehicle components stolen.
- total_loss: Vehicle explicitly declared or confirmed as a total loss.
- glass_only: Damage limited to vehicle glass.
- not_a_claim: Message is not reporting an insurance claim.

## 3. Urgency

Allowed values:

- high: Injury reported OR vehicle is undrivable and unsafe.
- medium: Claim needs attention but does not meet high urgency.
- low: Minor damage or non-urgent claim.

## 4. Extraction Rules

| Field | Labelling rule |
|---|---|
| policy_number | Extract exactly as mentioned; otherwise null |
| incident_date | Use YYYY-MM-DD; otherwise null |
| location | Extract the mentioned location; otherwise null |
| vehicle_reg_no | Uppercase, without spaces; otherwise null |
| estimated_amount_inr | Integer amount in rupees; otherwise null |
| injury_reported | true, false or null |
| police_report_filed | true, false or null |

## 5. Important Rules

1. Never invent missing information.
2. Use null when information is unavailable or unknown.
3. Any reported injury means high urgency.
4. Vehicle registration must be uppercase without spaces.
5. Convert dates only when the date is unambiguous.
6. Do not assume a police report was filed just because police are mentioned.
7. Distinguish theft of vehicle components from glass-only damage and personal property carefully.
8. A request for a renewal certificate is not an insurance claim.
9. Record ambiguous cases for manual review.

## 6. Quality Control

- Every message must have a complete gold label.
- Use synthetic or anonymised messages.
- Keep development and test datasets separate.
- At least 20 labels should be independently reviewed.

## 7. Output

Each labelled message must contain:

claim_type
urgency
policy_number
incident_date
location
vehicle_reg_no
estimated_amount_inr
injury_reported
police_report_filed
notes

## 8. Edge Cases and Tie-Breaking Rules

### Rule A: Personal Belongings Stolen from a Vehicle
1. Theft of personal belongings (such as a laptop bag, sunglasses, wallet, phone, or sports gear) from a vehicle is not vehicle theft under auto policy coverage.
2. If the only vehicle damage is broken glass, classify the vehicle damage as `glass_only`, even if personal belongings were stolen.
3. Classify as `own_damage` if additional vehicle body, panel, paint, or mechanical damage exists.
4. Use `theft` when the vehicle itself or an automotive vehicle component (e.g., wheels, battery, catalytic converter, stereo, mirrors) is stolen, even if glass is also damaged.

### Rule B: Hit-and-Run and Third-Party Incidents
1. If another vehicle caused damage but its driver or vehicle is unidentified and no actionable third-party claim is established (hit-and-run by an untraced party), classify the insurance claim as `own_damage`.
2. Use `third_party_liability` when the message establishes an actionable claim involving an identifiable or otherwise established responsible third party (e.g., other driver admitted fault, vehicle registration recorded, driver detained, joint police report filed, or policyholder caused damage/injury to a third party).
*(Note: This is a dataset labelling convention for this case study project, not a statement of universal insurance law.)*

### Rule C: Suspected vs. Confirmed Total Loss
1. If a vehicle is merely suspected, believed, or reported as potentially being a total loss (e.g., local mechanic says it could be, or surveyor says it may be a total loss pending formal assessment), classify as `own_damage`.
2. If the vehicle is explicitly declared, confirmed, or written off as a total loss or constructive total loss by an insurance surveyor, workshop, or insurer, classify as `total_loss`.

### Rule D: Injury and Police Report Evidence Standards
1. Use `true` only when bodily injury or police report/FIR filing is explicitly affirmed.
2. Use `false` only when the message explicitly establishes negative evidence (e.g., "no injuries", "nobody was hurt", "did not file police complaint", "no FIR").
3. Use `null` when the information is unstated, ambiguous, or unconfirmed. Police presence or contact at the scene does not automatically mean a formal complaint was filed.

### Rule E: Multiple Incidents, Dates, and Amounts
1. If a message describes multiple incidents, classify according to the primary current incident being reported.
2. If the incident date lacks a year or is relative ("yesterday", "last night"), use `null` unless the calendar date can be established unambiguously from context.
3. If an amount is approximate, extract the stated approximate integer amount in INR.
4. Never infer a location from registration numbers, policy prefixes, or outside world knowledge; if a location is not explicitly stated in the message text, extract `null`.
