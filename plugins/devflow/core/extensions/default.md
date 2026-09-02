# Default domain audit extension

Apply these checks in addition to the common audit core when no specialized domain extension exists:

- Identify domain invariants from the PRD and code, then test whether every state transition preserves them.
- Trace ownership and authorization at system boundaries.
- Trace error propagation and retries across adapters/integrations.
- Verify time, ordering, duplicate delivery, partial failure, and reprocessing behavior where relevant.
- Verify persistence constraints and migration compatibility when data shape changes.
