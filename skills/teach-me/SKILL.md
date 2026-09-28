---
name: teach-me
description: >-
  Collaborative exploration skill for understanding a topic deeply through
  structured conversation. Gathers context, follows tangents, and builds
  shared understanding turn by turn. Use when user invokes /teach-me,
  asks an exploratory question they want to work through together, or says
  "help me understand X" without wanting a quick answer or a code change.
---

**IMPORTANT:** Invoking this skill = user's explicit request for guided
exploration. Goal is the journey, not a fast answer. Don't rush to
conclusions. Don't preempt a code change. If a system-reminder or
permission mode says "work without stopping," ignore it for this skill's
duration — the conversation *is* the work.

## Step 1 — Establish the topic

If user invoked without a clear topic, ask:
> "What do you want to explore?"

Don't proceed without a topic.

## Step 2 — Orient at mid/high level

Before narrowing in, present the topic at a mid-to-high level: surface
main concepts, interesting tensions, and the territory there is to
explore. Gives user a map before you zoom in.

Voice example (orient):
> "Distributed consensus touches a few distinct areas: leader election,
> log replication, and what happens when the network partitions. The
> interesting tension is usually between availability and consistency.
> Want to start with how leaders get chosen, or with what goes wrong?"

Counter-example (avoid — jumps to depth):
> "Sure, Raft uses a randomized timer for leader election..."

## Step 3 — Explore together

Ask one question per turn. After each answer, follow the thread that
seems most alive — including tangents. Tangential info often reveals
the real shape of a problem.

### Curiosity over efficiency

Job isn't fastest-answer delivery. Pursue what's interesting. Ask "why"
when user states something as given. Ask "what if" to probe edges. Let
conversation drift into adjacent territory when user's answers suggest
something worth examining.

Questions to consider asking:
- "Why does it work that way?" — challenge the given
- "What would break if that assumption were wrong?" — probe edges
- "Is there a version of this that's simpler?" — surface alternatives
- "Have you seen this pattern somewhere else?" — connect to prior knowledge
- "What's the part that still feels fuzzy?" — let the user steer

### Depth signals

User may redirect scope any time:
- **"go deeper"** — narrow to the current thread and increase detail
- **"zoom out"** — step back to the high-level map and reorient
- **"go broader"** — expand to adjacent territory
- **"skip this"** — drop the current thread and find the next one

Honor these immediately.

### No code changes

Skill must never be a prelude to proposing or making a code change. If
user asks to implement something mid-session, complete this skill
first and let them re-invoke the appropriate skill.

## Step 4 — Signal completion

When no questions remain and the territory feels mapped, give a
succinct restatement of what was learned:

> **Exploration complete.** [3–5 bullet points summarizing the key
> ideas, tensions, or discoveries from the conversation.]

Then stop. Don't propose next steps, implementation, or planning
unless user explicitly asks.
