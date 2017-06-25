# grow-ext-kintaro

[![Build Status](https://travis-ci.org/grow/grow-ext-kintaro.svg?branch=master)](https://travis-ci.org/grow/grow-ext-kintaro)

Kintaro Content Server extension for Grow. Kintaro is a private, headless CMS
hosted at kintaro-content-server.appspot.com. It can be used to manage
arbitrary structured data, and using this extension, that arbitrary structured
data can be consumed in Grow.

## Concept

This extension binds Grow collections to Kintaro collections and Grow documents
to Kintaro documents. In other words, when a Kintaro document changes, it
changes in Grow as well. This allows stakeholders to edit content in Kintaro,
and developers to build Grow pages consuming Kintaro content without writing
any specialized code or vastly changing their development approach.

Each time a page is rendered, content from Kintaro is injected into the
corresponding document's fields. Each time a site is built, the Kintaro
preprocessor runs to update all content locally prior to the full build step.

When documents are deleted from Kintaro, those documents are also deleted in
Grow.

## Usage

### Initial setup

1. Create an `extensions.txt` file within your pod.
1. Add to the file: `git+git://github.com/grow/grow-ext-kintaro`
1. Run `grow install`.
1. Add the following section to `podspec.yaml`:

```
extensions:
  preprocessors:
  - extensions.kintaro.KintaroPreprocessor

preprocessors:
- kind: kintaro
  repo: example-repo-id
  project: example-project-id
  inject: true  # If true, content is injected with each page render.
  bind:
  - collection: /content/ExampleCollection1/
    kintaro_collection: ExampleCollection1
  - collection: /content/ExampleCollection2/
    kintaro_collection: ExampleCollection2
```

When documents are downloaded from Kintaro, the basename used for the document
corresponds to the document's Kintaro document ID. For example, an integration
with Kintaro might leave you with the following collection:

```
/content/ExampleCollection/
  _blueprint.yaml
  52532525326332.yaml
  59235872386116.yaml
  ...
```

As usual, your `_blueprint.yaml` file will control the serving behavior of
content within this collection.
