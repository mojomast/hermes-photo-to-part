# photo-to-part plugin

This directory is what Hermes installs:

```bash
hermes plugins install mojomast/hermes-photo-to-part/plugin --no-enable
```

Version 0.1.22. The repository README, changelog, security notes, evals, and tests live one directory up and are not part of this install. From this directory, `hermes plugins doctor .` reports the six `photo_part_*` tools.

Hermes Desktop 0.23 or newer loads `desktop/plugin.js` as an optional Part studio pane. It reads `/api/plugins/photo-to-part/` from `dashboard/plugin_api.py`. The pane is not a tool. Older Hermes builds ignore those files and keep the six tools.
