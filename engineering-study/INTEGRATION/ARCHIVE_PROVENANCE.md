# Archive and alternate-file provenance

This note records what repository history and archive directory listings establish. Archives were listed in place; they were not extracted or executed. Git history was read only.

## Committed archive contents

| Artifact | Observed contents | What it represents |
|---|---|---|
| `jfiles-repaginado.tar.gz` | `JFiles.py`, `jfcore.py`, `jfiles-picker`, `INSTALAR-SELETOR.md`, changelog, and JFiles tests | A packaged snapshot of the JFiles repagination/chooser work, not another installed JFiles program. |
| `jrun.tar.gz` | `JRun.py`, `jrcore.py`, changelog, and `tests/test_jrcore.py` | Snapshot of the JRun command-launcher implementation. |
| `jwm-logs.tar.gz` | `JWM.py`, `jlog.py`, `tests/test_jlog.py`, changelog | Historical snapshot associated with JWM logging work. |
| `chessyou-0.2.tar.gz` | Added in commit `d07a203`, removed in `0350234` | A prior packaged ChessYou release artifact; current source package is the `chessyou/` directory. |

The `tar -tzf` listing confirms filenames only. It does not prove the archive matches current HEAD byte-for-byte, its intended retention policy, or whether a release process still consumes it.

## Git history and duplicate-looking root files

At the checked-out commit `df6750e` (`little cat walking around the bar`), the prior commit `1e643f1` introduced `JBar (2).py`, `JWM (2).py`, and `jtheme (2).py`, along with the two archives `jfiles-repaginado.tar.gz` and `jrun.tar.gz`. The current `HEAD` modifies `JBar.py` and adds `jcat.py` plus its tests. The current index reported the three “(2)” files as changed/deleted by pre-existing user edits.

Names with a suffix are not automatically runtime modules: normal startup references `JWM.py`; the main desktop imports `JBar.py`; theme consumers import `jtheme.py`. The alternate files are tracked historical/parallel copies in the parent revision but, in the current user working tree, two are deleted and one is modified. This study preserves that working tree and does not infer intent from the suffix.

The current `jpopup.py`, `jpopup (2).py`, and popup tests are untracked user files in the supplied checkout. Their content was examined as part of the component chapter, but they are not represented by the checked-out Git commit. Findings about them are therefore “working-tree facts,” not facts about `HEAD` or the remote branch. Before attributing such behavior to a release, compare the working tree with the intended commit.

## Reproducible provenance commands

Read-only commands used for this pass:

```sh
git status --short
git log --oneline --all --decorate -12 --name-status
tar -tzf jfiles-repaginado.tar.gz
tar -tzf jrun.tar.gz
tar -tzf jwm-logs.tar.gz
```

No archive was unpacked; no source or project file was changed by the history investigation. Git status also showed pre-existing edits/deletions and untracked popup files. The only study-created files are within `engineering-study/`.

## Maintainer questions left open

- Are archives intended as release artifacts, historical snapshots, or temporary backup files?
- Should “(2)” variants be retained as explicit experiments, renamed, or eventually removed? This study makes no recommendation to change them without knowing their intended role.
- Is the current untracked popup implementation intended to become tracked source, remain experimental, or be replaced?
- Does any external release/install workflow consume these archives or the ChessYou 0.2 package?
