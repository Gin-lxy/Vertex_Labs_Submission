# Follow-up rules

- Compare `today` and each contact instant after converting both to UTC. A contact is due when elapsed time is at least 336 hours.
- None means there is no contact history. Such deals come first, in input order. Lost contact dates need a separate business status rather than None.
- Open stages are exactly Sourcing and Diligence. Closed - Won and Closed - Lost are excluded before name/contact-field validation. Unknown stages raise ValueError.
- Equal UTC contact instants retain input order. Names are returned without mutation or deduplication.
- `today` is a timezone-aware datetime; omitted or None means one reading of the current UTC clock. `last_contact` is an offset-aware ISO string or None.
- Missing timezone, invalid format/type, UTC conversion failure and future contact instants raise ValueError with a field and cause. Open deals need a nonempty name and an explicit last_contact field.
- Error context uses id, then name, then zero-based input index. The global today argument is validated first using the first input record's context, or an empty-input marker.
- Any invalid input aborts the call rather than returning partial results.
