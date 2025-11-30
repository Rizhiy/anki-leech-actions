# Anki Leech Actions

Simple addon to better manage leeches by applying bulk actions to troublesome cards.

## Features

- Automatically applies your chosen action whenever Anki tags a card as a leech.
- Supports deleting, postponing, resetting lapse counts, or simply removing the leech tag from cards.
- Lets you disable automatic handling and rely on the preview-first manual runner when you prefer.
- Fully configurable by deck name pattern and note type, so each group of cards can behave differently.

> **Heads-up:** Anki's built-in leech behavior can suspend cards on its own. If you prefer to keep reviewing those leeches, adjust the default leech handling inside Anki so it no longer suspends them before using this add-on.

## Usage

1. Install or symlink the `anki_leech_actions` folder into your Anki add-ons directory.
2. Use `Tools → Anki Leech Actions` to open the visual rule editor and tailor actions per deck/note type.
3. Continue reviewing cards as usual—whenever Anki applies the leech tag, the configured action runs automatically (delete/reset/delay/reset lapses/remove tag).
4. If you want to manually sweep existing leeches, click **Run actions now** inside that dialog to launch the processing window.
5. The window immediately shows a preview of the actions that would run on every tagged card.
6. If everything looks good, click **Confirm**; otherwise hit **Cancel** to leave things untouched.

## Configuration

Open `Tools → Anki Leech Actions` to launch the rule editor (and find the **Run actions now** shortcut). Each row offers dropdowns for:

1. **Deck** – select a specific deck or choose _Any deck (_)\*.
2. **Note type** – select the exact note type or _Any note type (_)\*.
3. **Action** – choose between _Reset progress_, _Delay card_, _Delete card_, _Reset lapse count_, or _Remove leech tag_.
4. **Delay (days)** – enabled only for _Delay card_ actions to specify how long to postpone the card.

Use **Add rule**, **Remove selected**, and the new **Move up/Move down** buttons to curate and prioritize the list, then press **Save**. Rules are evaluated from top to bottom, and the first match wins. Cards that do not match any rule are skipped.

The **Automatically run rules when cards gain the leech tag** checkbox toggles background processing if you’d rather rely on manual sweeps.

Configuration changes are automatically migrated between versions, so existing installs keep working even if new fields are introduced.

Automatic processing only triggers when the note contains the configured `leech_tag` (defaults to `leech`).

If you prefer editing the raw JSON, open the _Add-ons_ screen, highlight **Anki Leech Actions**, and click _Config_—it now shows the original configuration text.

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
