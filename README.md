# Anki Leech Actions

Simple addon to better manage leeches by applying bulk actions to troublesome cards.

## Features

- Automatically applies your chosen action whenever your review causes a card to become a leech.
  Can also bulk apply actions on existing leeches.
- Supports deleting, postponing, resetting lapse counts, or simply removing the leech tag from cards.
- Fully configurable by deck name pattern and note type, so each group of cards can behave differently.

> **Heads-up:** Anki's built-in leech behavior can suspend cards on its own. If you prefer to keep reviewing those leeches, adjust the default leech handling inside Anki so it no longer suspends them before using this add-on.

### Differences from other addons

- Leech Toolkit - didn't have the actions I needed and it seemed to be abandoned.

## Usage

1. Configure using `Tools → Anki Leech Actions`.
2. Either bulk apply the rules or continue reviewing as normal.

I currently have two types of notes:

- Notes I definitely need to learn - for these I remove leech tag, reset lapse count and delay by a month.
- Notes I don't care as much about - these I just delete.

I'm learning Japanese, so for me Kanji is the former type and words are the latter.

## Development

Create a virtual environment with your preferred method.
e.g. for conda:

```bash
conda create -n anki-leech-actions python=3.9
```

Activate the environment:

```bash
conda activate anki-leech-actions
```

Install the dependencies:

```bash
pip install -r ".[dev]"
```

Since Anki doesn't install dependencies automatically, we should keep them to a minimum.

Finally, link/copy the `anki_leech_actions` directory to relevant place on your system.
