
We develop skills for Anthropic and DeepSeek.

We use superpowers skills. We write specifications and plans in English,
following the ASD-STE100 standard.

Directory structure:
- docs - documentation
- docs/research - various research that may be useful later,
  or that has already been applied
- feedback - feedback, examples, advice, errors (not in the repository)
- init-raw-source - old skills used as a basis; we no longer look at them
- TODO - small tasks and fixes of inaccuracies that are easy to fix/implement
- .claude-plugin/plugin.json - file that contains the version of the skill set

We must increase the version (only the minor part for bug/typo fixes and
documentation additions, the major part when new features appear). We record
changes in the Changelog.

Before running `git push` to origin, we check that the changes are reflected
in the Changelog and that the version is updated.

We try to replace the Anthropic status line to show progress,
but if the model cannot display it, this must not be a problem.
