# Section C: PR review

- P1: An open deal with `last_contact=None` raises TypeError because `datetime.min` is naive; existing tests omit missing contacts.
- P2: `.days > 14` excludes contacts aged 336 to under 360 hours; existing examples are far from the cutoff.
- P2: Sorting ISO strings can reverse UTC chronology and equal-instant input order; the current offset example happens to agree with UTC.
- P2: Unknown stages, future contacts and invalid or naive timestamps lack consistent, contextual ValueErrors; current tests omit invalid data.
- P3: `test_no_shared_state` depends on the wall clock.

Decision: **Merge with changes.** Apply the revised implementation and fixed-time regression tests.

Implementation assumptions: compare UTC instants; include elapsed intervals of at least 336 hours. None means no contact history, comes first and preserves input order. Equal contact instants also preserve input order. Only Sourcing and Diligence are open; both specified closed stages are skipped. Invalid data raises ValueError with an identifier and reason. Lost contact dates require a separate status.

The revised implementation passes all 41 cases. The unchanged original passes nine and fails 32. Both source files are preserved. Added tests are directly runnable using the included conftest.
