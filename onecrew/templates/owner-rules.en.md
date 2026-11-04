# The product owner's rules (OneCrew reads this file)

The advisor judges only by the lines below. One rule per line, coded R1..R6. Edit them to your own working agreements.

R1. While a feature is in development, build DEBUG only; build RELEASE only when development has ended, the tests pass and the product owner has tried it on a real device, as a separate delivery step.
R2. Each job sends the product owner exactly two messages: "Request for approval" and "Request for acceptance", each in the 5-item template below, plus the section "Decisions I made that you did not ask for".
R3. Every deliverable (code, mockup, document, build) goes through a v2 contract.
R4. Read-only diagnostics under about 5 commands, and the product owner's own verbs, sit outside v2 but must be logged.
R5. Any other work outside v2 needs the product owner's agreement first.
R6. Do not send "Request for acceptance" for a user-interface feature before it has run on a real device.

## Message template (at most 6 lines)

1. Request: the work that was asked for, in the product owner's own words.
2. What the user will see: the visible result.
3. How you accept it: the steps the product owner takes to check it.
4. Not doing: what is deliberately left out.
5. Risks: what could go wrong and how it is guarded against.

End of message: "Decisions I made that you did not ask for" (each decision with its alternative and its cost; write "none" if there are none).
