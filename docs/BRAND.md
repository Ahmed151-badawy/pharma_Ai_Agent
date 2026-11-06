# Doesy, the mascot

Doesy is a white-and-purple robot with a cyan smile and a pill on his chest. He is the face of the assistant: he greets people on
login, answers in the chat, and keeps them company while the app is loading. All assets live in
[`web/assets/doesy/`](../web/assets/doesy) and are shared by the web UI (`web/app.py`) and the desktop client (`gui.py`).

## Palette

| Role | Value |
|---|---|
| Brand purple (buttons, links, user bubbles) | `#6E34D1` (hover `#5B28B5`) |
| Soft purple (pills, selected rows, badge backgrounds) | `#EDE5FF` |
| Eye cyan (accent, `admin` pill) | `#00F9FD` |

Status colours (green, amber, red) are unchanged and always mean what they meant before.

## Which file for which size

The full body (waving arm and sparks) only reads at about 100px and above. Below that, use the head badge.

| Use | File | Display size |
|---|---|---|
| Hero (login, chat empty state) | `doesy-full-256.png` | 130–170px tall |
| Loader | `doesy-full-128.png` | about 54px tall |
| Chat avatar, page headers, empty states, status | `doesy-badge-128.png` | 26–52px |
| Tiny badge (sidebar status) | `doesy-badge-64.png` | 26px or less |
| Head only, transparent | `doesy-head.png` | any |
| Browser tab / window icon | `favicon-32/48/64.png`, `favicon.ico` | 16–64px |
| Touch / app icon | `apple-touch-icon.png` (180), `icon-512.png` | 180–512px |
| Master (cleaned cut-out, full resolution) | `doesy.png` | print / re-export only |

Everything is exported at roughly 2x its display size for sharp HiDPI rendering. The logo lockup is `web/assets/logo.svg`.

## Where he appears

Favicon and window icon, sidebar logo, login, chat welcome, assistant avatar in every reply, a badge in every page header, "all clear"
and empty states, and the sidebar service status (he turns grey and sleepy when the API is offline). While the assistant, a
search or an upload is working, **Doesy pushes a pill along** (`.push` in `web/app.py`; `push_frames()` in `gui.py`). The loop
respects `prefers-reduced-motion`.

## Usage rules

- Do not recolour, stretch or redraw him; use the files above. Keep clear space of about a quarter of his height on all sides.
- Keep copy friendly but plain. Doesy never makes jokes about dosing, expiry, safety warnings or errors involving patients.
- Only one pose exists today (waving). New poses (thinking, celebrating, alert) should be added as new files in the same folder.

## Regenerating the assets

```bash
pip install pillow numpy scipy
python scripts/make_doesy_assets.py path/to/doesy-source.png web/assets/doesy
```

The script removes stray alpha speckle, trims the cut-out, resamples with premultiplied alpha (no halos), masks out the head for the
badges and rebuilds the logo.
