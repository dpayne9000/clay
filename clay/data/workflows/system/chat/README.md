# Clay General Chat + Project Knowledge

General chat loop:

`inventory -> ask -> recall -> select/read project files -> reply -> optional memory write -> repeat`

The reply receives a concise operational guide and the live generated workflow
template from Clay's installed action registry. Exact project questions use a
selective read pass over the current approved workspace. The workflow can
explain Clay and the project extensively, but it does not claim to execute
operations that no action performed.

## Memory model

- `appendTranscript` keeps short immediate conversational continuity.
- `searchMemory` retrieves a few older recollections related to the current subject.
- The reply uses recollections only when relevant; the current message always wins.
- A separate memory decision stores only durable future-useful information.
- Duplicate recollections, transient requests, greetings, guesses, assistant claims, and credentials are skipped.
- `deriveTags` improves later lookup and `writeMemory` persists the normalized record.

## Tense

Runtime prompts use current-turn wording: `CURRENT MESSAGE`, `RECENT CONVERSATION`,
`RELEVANT RECOLLECTIONS`, `Respond ... now`, `Decide whether CURRENT MESSAGE contains ...`.

Training uses the same labels and tense.

Stored memory is normalized as current state when appropriate:
`The user prefers ...`, `The user is building ...`, `The current project decision is ...`.
It does not narrate the chat as `The user said ...`.
