# Contributing

Contributions, accessibility improvements and new translations are welcome.

1. Create a feature branch; do not commit any real TV keys, tokens, passwords or diagnostic logs containing secrets.
2. Keep the **TEST** path read-only, including before and after errors.
3. Reuse upstream projects instead of copying and relicensing their source. Update `CREDITS.md` and security documentation if changing a pinned third-party revision.
4. Every TV modification must be explicitly selected and confirmed. No blanket service removal, no `rm -rf` of TV application directories, no automatic root attempt.
5. Localize new prompts into all JSON files under `locales/`. English is the reference language and fallback.
6. Run `python3 -m unittest discover -s tests -v` and `bash -n install.sh` before a pull request.
7. If you test on real hardware, record the exact model, webOS/SDK version, firmware, and whether the change survived reboot; never claim compatibility with all TVs.

For root-related issues please also read the original project's documentation at https://github.com/throwaway96/slopbro and give appropriate credit to its authors.
