---
name: prove
description: >-
  Prove a specific factual claim, or answer a specific question, in a short
  direct pass backed by concrete evidence -- read the source, cross-check every
  claim with the adversarial-validator sub-agent, and return a cited answer.
  Use when the user requires concrete proof rather than a plausible-sounding
  answer. Not for open-ended planning, audits, or code review.
---

# Prove

Correctness over speed. The point of this skill is a short, direct lookup that
still comes with real proof -- not a hedge, not a research project.

## Default posture

Assume the question is answerable from one or two files plus a confirming check.
Most are. Only escalate (see below) if the investigation itself tells you
otherwise.

## Workflow

1. **Locate.** Find the material that bears on the question -- Grep/Glob the
   repo, read the relevant files, docs, or specs. Start from whatever index the
   project offers (README, CLAUDE.md, doc index) when the layout is unfamiliar.
2. **Ground truth.** For each claim your answer will make, find the external
   proof -- a file:line, an API spec, a config value -- before you write the
   claim down. Prefer the source over any description of the source: docs,
   comments, and READMEs are caches and go stale. When a doc is your only
   reference, say so and treat the claim as weaker.
3. **Escalate if the shape changes.** If steps 1-2 reveal the question actually
   branches -- three or more independent leads, unclear relationships across
   components, no single place answers it -- stop following the tree in this
   short pass. Tell the user in one line that the question is broader than
   expected, then widen the search (parallel `Explore` sub-agents, one per lead)
   rather than depth-first grinding.
4. **Draft** the answer using the four-part format below.
5. **Validate.** Send the draft to the `adversarial-validator` sub-agent as one
   claim per sentence of the answer that asserts a fact. Per claim, give it the
   answer text, any internal reference (a prior tool result, a doc you read),
   any external reference (file:line, URL), and any assumption the claim leans
   on. The validator is domain-agnostic -- brief it purely on the claim, never
   on this project's context.
6. **Loop.** Anything the validator does not return as `CONFIRMED` --
   `INCONSISTENT` or `UNPROVEN` -- must be fixed: correct the claim, go find
   better proof, or drop it from the answer. Re-validate after every fix.
   Repeat until every claim is `CONFIRMED`. The user sees only the final,
   validated answer; do not report the iteration count.
7. **Output** in the four-part format.

## Answer format

Always exactly these four sections, in this order:

1. **Answer** -- concise, direct.
2. **Assumptions** -- scope or terminology you assumed rather than asked about.
3. **Sources consulted** -- what you read to reach the answer: doc pages, README
   sections, prior tool results. Note where a source is a description of the
   code rather than the code itself.
4. **External proof** -- the file:line, repo path, or URL that verifies each
   part of the answer.

Keep 3 and 4 separate even when they overlap. A source you read is not thereby
proof; the split is what makes an answer resting only on documentation visible
as such.

**Example (do this):**
> **Answer:** `mcp-svc` authenticates inbound calls with the shared JWT
> middleware from `shared-utils`, not its own auth code.
> **Assumptions:** "authenticates" means request-level auth, not the service's
> own outbound token acquisition.
> **Sources consulted:** `mcp-svc/README.md` (auth section -- description, not
> code), `shared-utils/authutils/` package listing.
> **External proof:** `mcp-svc/middleware/auth.py:18` imports
> `authutils.RequireJWT`, defined at `shared-utils/authutils/middleware.go:40`.
> No other auth path in `mcp-svc/middleware/`.

**Counter-example (avoid):**
> mcp-svc handles auth via the shared library, as documented in the README.

No file, no line, no way for the user to verify it themselves.

## Escalating to a wider pass

**Example (do this):** User asks "does this schema change break the API
consumers?" -- you open the schema, see three services consume the generated
artifacts, and whether it breaks depends on which fields each one reads. That
is a branching investigation: say so in one line, then fan out one sub-agent per
consumer.

**Counter-example (avoid):** Treating "what does this service do" as branching
just because it imports two other packages. The direct answer is one paragraph
from one file. Do not manufacture an escalation the question does not need.

## Validator loop details

Invoke via the `Agent` tool with `subagent_type: adversarial-validator`. Do not
pass a `model` override -- the agent is pinned to Haiku in its own frontmatter
and must always run on it. Give it, per claim:

- the answer text being asserted
- the internal reference (prior tool result, doc path) if any
- the external reference (file:line, URL) if any
- any assumption the claim leans on

See `agents/adversarial-validator.md` for the full rubric -- in short: no proof
means unproven, disagreement between the answer and its references means
inconsistent, and proof that only alludes to the answer without establishing it
also means unproven. Only `CONFIRMED` claims may ship in the final answer.
