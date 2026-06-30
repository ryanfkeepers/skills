# Operation Flows

## Add

### Step 3a — Interview via sanity

Invoke `keepers:sanity` with this topic:

> "The standard the user wants to add. Establish: (1) which domain it
> belongs to, (2) its name and prescribed behavior, (3) a correct example
> and a counter-example using `<example>` / `<example-avoid>` tags."

### Step 4a — Check for overlaps

Read the domain's standards doc (e.g., `go/STANDARDS.md`). Scan all
existing entries. If any entry's name or behavior substantially overlaps
with the new standard, flag it:

> **Overlap detected:** "Standard Name" already covers similar ground:
> [quote the existing entry]
> Update the existing standard, or create a new one?

Wait for the user's answer before continuing.

### Step 5a — Handle new domain

If the domain has no existing standards doc, ask:

> **New domain:** How would you describe the `<domain>` domain in one
> sentence? (This description will appear in STANDARDS.md.)

Create `~/.agents/mystandards/<domain>/STANDARDS.md` and add a link to it
in the primary `STANDARDS.md`.

### Step 6a — Write the entry

Append the new standard to the appropriate domain doc using the standard
format. Place it alphabetically by name among existing entries.

---

## Modify

### Step 3b — Identify the standard

Ask the user which domain the standard is in. Read that domain's doc.
List all standard names in that domain and ask which one to modify.

### Step 4b — Interview via sanity

Invoke `keepers:sanity` with this topic:

> "The user wants to modify an existing standard. Current content:
> [paste the full existing entry here]
> Establish what should change: name, behavior, example, or
> counter-example."

### Step 5b — Write the update

Replace the existing entry with the updated content, preserving the
standard format.

---

## Remove

### Step 3c — Identify the standard

Ask the user which domain the standard is in. Read that domain's doc.
List all standard names and ask which one to remove.

Show the full entry and ask for confirmation before deleting.

### Step 4c — Delete the entry

Remove the entry from the domain doc. If the domain doc is now empty,
ask the user whether to remove the domain link from STANDARDS.md too.
