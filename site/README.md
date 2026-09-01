# The published book

MkDocs with the Material theme, and one plugin that renders the lesson notebooks as pages.

```sh
just setup-site      # install mkdocs, the theme and the notebook plugin
just site            # stage the pages and write the generated files
just site-serve      # the same, then a live preview on localhost:8000
```

## What is written by hand and what is not

`head.yml` is the configuration a person writes. `docs/index.md`, `docs/how-to-read-this.md` and `docs/tiers.md` are the pages a person writes.

`mkdocs.yml` is generated. It is `head.yml` with a navigation tree appended, and the navigation is worked out from the lessons and blueprints that are actually on disk. That is so adding a lesson cannot leave it invisible, and so a lesson that gets removed cannot leave a dead entry behind.

`docs/stylesheets/vocabulary.css` is generated too, from `kxray/vocabulary.py`. A subsystem is the same colour in a diagram, in a widget and on this site, and the way to keep that true is to have one list and read it three times rather than write it three times.

Both of those are committed, and `just site-check` fails when either is out of date. CI runs that check.

## What is staged, and why it is not committed

The lessons live in `lessons/` and the blueprints live in `blueprints/`, beside the code they are about, which is where somebody editing them wants them. MkDocs can only see files underneath `docs_dir`.

So `just site` copies them into `docs/lessons/` and `docs/blueprints/`, and those copies are ignored by git. A file that exists twice in one repository is a file that will disagree with itself, and the copy is the one that would be wrong.

The build output lands in `_build/` and is ignored as well.

## The lesson pages

A lesson page is the committed notebook, rendered with the output it was committed with. Nothing runs when the site is built. Output produced on a build machine is a fact about the build machine, and this book is careful about the difference between those and facts about the kernel.

Every lesson page carries a link that opens the same notebook in Google Colab, on a machine that can actually run it.
