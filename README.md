# grow-ext-kintaro

(WIP) Kintaro Content Server extension for Grow.

## Concept

This extension binds Grow collections to Kintaro collections and Grow documents
to Kintaro documents. In other words, when a Kintaro document changes, it
changes in Grow as well. This allows stakeholders to edit content in Kintaro,
and developers to build Grow pages consuming Kintaro content without making
any changes.

Each time a page is rendered, content from Kintaro is injected into the
corresponding document's fields. Each time a site is built, the Kintaro
preprocessor runs to update all content locally prior to the full build step.

## Usage

### Initial setup

1. Create an `extensions.txt` file within your pod.
1. Add to the file: `git+git://github.com/grow/grow-ext-kintaro`
1. Run `grow install`.
1. Add the following section to `podspec.yaml`:

```
extensions:
  preprocessors:
  - ext.kintaro.KintaroPreprocessor

preprocessors:
  - kind: kintaro
```

### Bind Grow collections -> Kintaro collections

Binds an entire Grow collection to a Kintaro collection.

```
# /content/<collection>/_blueprint.yaml

kintaro:
  repo: RepoID
  collection: CollectionName
  auto_project: true  # Optional.
  project: ProjectID  # Optional.
```

### Bind Grow documents -> Kintaro documents

Binds a single Grow document to a document in Kintaro. When a collection is
bound to Kintaro, the `kintaro_id` field is automatically added for each
document's front matter.

```
# /content/<collection>/<doc>.<ext>

kintaro_id: <kintaro id>
```
