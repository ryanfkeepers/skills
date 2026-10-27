# Writing narrative.json

The page has two prose tabs, **Analysis** (what the numbers say) and **Suggestions** (what to do about it). You
write both after reading the `build_data.py` summary. `render.py` embeds them; every figure is drawn by the
template from `data.json`, so you pick figure keys and write the words. Numbers in prose must come from the
summary or `data.json`, never from memory or the example file.

## Shape

```json
{
  "analysis": {
    "title": "A claim, not a topic",
    "lede": "Two sentences: what is true, and what is unusual about it.",
    "sections": [{ "title": "A claim", "paras": ["<html>"], "figs": ["ranks"] }],
    "aside": { "title": "How far to trust this", "items": ["<html>"], "next": "Next: {{go:suggestions|what to do about it}}." }
  },
  "suggestions": { "...": "same shape; aside is 'How to tell it worked'" }
}
```

Strings are trusted HTML (`<code>` for package paths). Link to a tab with `{{go:<tab>|link text}}`; tabs are
overview, analysis, suggestions, scorecard, forest, dsm, matrix, graph, bundle, churn. `render.py` rejects
unknown figure keys and tab links. A tab is omitted from the page if its part is missing from the file.

## Figure keys

| key | shows | needs | omitted automatically when |
|---|---|---|---|
| ranks | subject's rank among peers on six measures | 2+ peers at or above min size | subject unranked |
| share | per entry point, share of imports used by another entry point | entry points | none detected |
| use | called / init-only / eliminated packages per binary | Go linker data | `meta.has_used` is false |
| hub | largest package against the runner-up on LOC, fan-out, churn | 2+ code packages | |
| misfit | packages least at home in their directory | | no package qualifies |
| hidden | co-changing pairs with no import edge | churn | churn unavailable |
| depth | mean package depth per unit | 2+ units | single unit |
| core | packages used by many entry points (shared core) | entry points | |
| deep | most deeply nested packages | | |

Do not write a section whose claim depends on data the run lacks (check `meta.has_used`, `meta.has_churn`,
`meta.has_abstractness`, `meta.notes`). A figure that renders empty leaves a section with only prose.

## Style

- Blog layout, not a numbered list: 5 to 8 sections, each a claim as the title, one tight paragraph, one figure.
- The lede and first section answer "how tangled is it, compared with what". Say plainly when the package graph
  is ordinary and the problem is elsewhere, or the reverse. Let the numbers pick the story; the example file is
  one story, not a template to fill.
- Compare against peers, never against an absolute bar: the literature gives no threshold that separates clean
  from tangled. Say how many peers there are.
- Name the caveat that applies where it applies (size-driven measures when the subject is far larger than its
  peers, D in Go, linker conservatism, a short churn window). The closing aside lists the ones that matter.
- Suggestions follow from the analysis, ordered by payoff, each tied to a figure, and the closing aside says how
  to tell it worked using measures on the page. Recommend structure, not a rewrite; the page is evidence for a
  conversation, and no code in the analysed repo is touched.
- Describe what the data shows, not intent. A package nobody calls is "never called by this binary", not "dead".

`example-narrative.json` is a complete worked example from one run (the earn service in Veeam-VDC/control-plane-backend).
