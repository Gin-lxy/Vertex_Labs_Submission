# Vertex Labs take-home submission

This directory contains the final material for sections A, B and C, together with the actual conversation export and an offline verification command.

| Section | Main submission | Supporting files |
|---|---|---|
| A | `A/system_prompt.txt`, `A/user_template.txt`, `A/failure_notes.txt` | Four inputs, twelve raw outputs, fixed evaluation cases, saved scores and AI log |
| B | `B/answer.txt`, `B/partner_note.txt` | Reusable analysis harness, CSV, configuration, complete calculations, tests and AI log |
| C | `C/review.md` | Original PR files, proposed revision, explicit assumptions, regression tests and AI log |
| Conversation | `chat/conversation.md` | Equivalent JSON export and a description of privacy redactions |

Section B's headline is Fintech, US$277.67 million, retaining the supplied LedgerLeaf record. The partner note gives the record's influence and exclusion comparison. Section C's original PR is preserved, with the proposed implementation in `C/revision/`.

## Verify

Use Python 3.11. Testing requires pytest; the saved analyses themselves use the standard library. From this directory in PowerShell:

```powershell
python -m pip install -r requirements-test.txt
python -B verify_submission.py
```

Verification checks the twelve saved A responses, runs the unified test suite, regenerates B in a temporary directory and compares the business artifacts, confirms C's original-versus-revised comparison, checks word limits, and inspects files for credentials and personal paths. It writes `verification_report.json`. Saved model responses can be checked without another paid model call.

The short A discussion and B partner note are each below 150 English words; each AI log is below 80 words; the C review is below 200 words, excluding code. The logs describe which work the applicant supplied and which work Codex and the task model performed.
