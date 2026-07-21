# Contributing to LakatoTree

Thank you for helping improve LakatoTree. Contributions are welcome in code,
tests, documentation, reproducible examples, and research-grounding corrections.

LakatoTree is in pre-release development. A project license has not yet been
selected, so please review the repository terms and open an issue before making
a substantial contribution.

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

LakatoTree requires Python 3.10 or newer. From a fresh clone:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[dev]'
```

Run the narrowest relevant tests while developing, then run the repository gates:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m lakatos.longinus audit
```

If a change affects the formal kernel, also run:

```bash
cd formal && lake build
```

Engine-behavior changes follow RED-first development and require both a defect
guard and a positive mechanism guard. They also require an OOPTDD receipt under
`ooptdd_receipts/<ID>/` that drives the real implementation and contains a
negative oracle. See `CLAUDE.md` for the shared-worktree coordination rules used
by repository agents.

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
