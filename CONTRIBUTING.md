# Contributing

Use Python 3.11+ and keep runtime dependencies small. Run the tests documented in
the README on Linux; ownership/ACL tests require a disposable root environment.
Add regression tests for changes to backup, restore, image selection or locking.

For UI changes, check both Japanese and English at desktop and narrow widths.
Keep translation keys aligned in `web/i18n.js` and render project/log data as text.
Never include real credentials, configuration, logs or infrastructure addresses
in commits or issue attachments.
