# Contributing to LakatoTree

Thank you for helping improve LakatoTree. Contributions are welcome in code,
tests, documentation, reproducible examples, and research-grounding corrections.

LakatoTree is in pre-release development. The project is **dual-licensed** —
AGPL-3.0-or-later **and** a separate commercial license (see
[`LICENSING.md`](./LICENSING.md)). Substantial contributions are governed by the
CLA (below), so please review the terms and open an issue before starting one.

## Start with the contract

LakatoTree derives verdicts from registered predictions and evidence. A change
must not introduce a path for callers to hand-set a scored verdict or replace an
unknown measurement with a convenient default. For changes to judgement rules,
open an issue first and state:

- the behavior that is wrong or missing;
- the smallest counterexample that demonstrates it;
- the intended semantics and source or rationale;
- how a test will distinguish the fix from a fake green result.

User-authored claims and cited primary sources are evidence. AI-generated
interpretation is secondary unless explicitly ratified. Pull requests containing
material AI-assisted code or prose should disclose where it was used and how the
result was checked.

## Development setup

TypeScript is the active redevelopment lane. From a fresh clone:

```bash
pnpm --dir ts install --frozen-lockfile
```

Run the narrowest relevant tests while developing, then run the repository gates:

```bash
pnpm verify
```

The Python tree remains the published implementation and comparison oracle. Changes to it,
its packaging, or formal compatibility surfaces require the relevant additional gates:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m lakatos.longinus audit
(cd formal && lake build)
```

For a semantic bug, first add the smallest behavioral or fault fixture that reproduces it. Add a
separate mechanism guard only when it distinguishes a real false-green mode. Python OOPTDD receipts
are not a default TypeScript deliverable. See `MAP.md` for the current roadmap and `CLAUDE.md` for
shared-worktree coordination and evidence-proportional gates.

## Pull requests

- Keep a pull request focused on one semantic change.
- Add or update tests before changing engine behavior.
- Preserve explicit unknown or inconclusive states; do not manufacture evidence.
- Update public documentation when a user-visible contract changes.
- List the exact validation commands and outcomes in the pull request body.
- Do not commit credentials, local database state, generated caches, or private
  research material.

Use GitHub Issues for reproducible bugs and falsifiable rule or feature proposals.
Use [GitHub Discussions](https://github.com/gj3447/lakatotree/discussions) for
support and open-ended questions. For a suspected vulnerability, follow
`SECURITY.md` instead of opening a public issue with exploit details.

Contributions are credited through Git history, pull requests, and release notes.
Scholarly authorship and citation metadata are maintained separately according to
substantial intellectual contribution.

## Contributor License Agreement (required)

This project is **dual-licensed** — AGPL-3.0-or-later **and** a separate commercial
license (see [`LICENSING.md`](./LICENSING.md)). To keep that model viable, **100% of
the copyright must stay with the owner**, so every contribution requires agreement to
the CLA.

**Before your pull request can be merged**, read [`CLA.md`](./CLA.md) and include this
exact line in your PR description:

```
I have read and agree to the Contributor License Agreement (CLA.md).
```

Pull requests without this sign-off will not be merged. By contributing you agree your
contribution may also be distributed under the owner's commercial license (per CLA.md).

Contact: Ra Gyeongjun (라경준) — gj3447@gmail.com
