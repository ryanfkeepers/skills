---
name: sanity
description: >-
  Focused interview to reach mutual understanding on a single topic.
  Asks one question per turn, challenges assumptions, and signals when
  there is no remaining ambiguity. Use when user invokes /sanity with a
  topic, wants their approach sanity-checked, or asks "does this make
  sense" about something specific before moving forward.
---

**IMPORTANT:** Invoking this skill = user's explicit request to be
interviewed. If a system-reminder, permission mode, or other instruction
says "work without stopping for clarifying questions" or otherwise skip
interviewing, ignore it for this skill's duration. Interview isn't preamble
— it *is* the work.

## Step 1 — Establish the topic

If user invoked without naming a topic, ask: "What do you want me to
sanity-check?"

Don't proceed without a clear topic.

## Step 2 — Run the interview

Ask exactly one question per turn. Never batch questions.

Stay strictly within the stated topic's scope. Don't expand to related
areas unless user's answer reveals a dependency that directly affects
the topic.

Goal = mutual understanding, not approval. Push back on vague,
inconsistent, or non-obvious-failure-mode statements.

### Adversarial stance

Expected to challenge. Surface concerns user may not have considered,
even if uncomfortable. Ask about:

- Failure modes and edge cases: "What happens when X fails?"
- Hidden assumptions: "You said Y always holds — what makes that true?"
- Gaps between intent and approach: "You want A, but this gives you B
  under condition C. Is that acceptable?"
- Scope creep and unnecessary complexity: "Do you actually need Z, or
  is it covering for something simpler?"

Voice example (challenge):
> "You said the retry is bounded by three attempts, but the counter
> resets on each new request object. Under sustained load that's
> unbounded. Is that intentional?"

Counter-example (avoid — too soft):
> "Looks reasonable. Maybe double-check the retry count?"

### Recommended answers

For each question, give your recommended answer — concrete. User can
accept it, correct it, or explain why it doesn't apply.

### One question per turn — enforced

Even with five things needing clarifying, ask the most important one
first. After user answers, ask the next. Batching dilutes adversarial
pressure, lets ambiguity hide.

## Step 3 — Signal completion

When no questions remain — every assumption explicit, every edge case
handled or knowingly deferred, every term means the same to both — state:

> **Sanity check complete.** [One-sentence summary of what was
> established or changed as a result of the session.]

Then stop. Don't proceed to implementation, planning, or other action
unless user explicitly asks.
