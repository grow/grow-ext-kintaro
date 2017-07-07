# grow-ext-kintaro

[![Build Status](https://travis-ci.org/grow/grow-ext-kintaro.svg?branch=master)](https://travis-ci.org/grow/grow-ext-kintaro)

Kintaro Content Server extension for Grow. Kintaro is a private, headless CMS
hosted at
[kintaro-content-server.appspot.com](https://kintaro-content-server.appspot.com).
It can be used to manage arbitrary structured data, and using this extension,
that arbitrary structured data can be consumed in Grow.

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
  project@env.prod: ~  # Set `project` to null in prod to build only published content.
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

## Kintaro quick intro

Kintaro is a headless CMS, where content can be managed independently of site structure. The content in Kintaro can then be downloaded into a Grow project, and then adapted in various ways.

![](https://user-images.githubusercontent.com/646525/27766028-ab20235c-5e77-11e7-9593-385cb3dedf16.png)

### General process

1. Visit Kintaro ([kintaro-content-server.appspot.com](https://kintaro-content-server.appspot.com)).
1. Choose your an existing project, or - if you have access - start a new project.
1. Create **Schemas**. This is where you specify content structure for all content in the system – from small, atomic nested content, to entire pages.
1. Create **Collections**. This is where you specify all main content types in the system.
1. Add **Documents** to each **Collection**.
1. Configure `podspec.yaml` to bind Kintaro collections to Grow collections.
1. Run `grow preprocess` to download content from Kintaro to Grow.

### Notes and style guide

- Names should be singular (for Collections, Schemas, and Fields). For example, if you have a repeated field for blog post tags, the field name should be **Tag** (not Tags).
- Reusable content should be placed into its own Collection, and then embedded within Documents via **ReferenceFields**.
- Kintaro does not support multiple schemas per collection, so if you would like to use Kintaro to produce individual pages with different structures, it is best to create one collection per page type. The convention to use here is to name single-page collections named like **PageFoo** and **PageBar**.

A sample repository might look like the following. The idea is to be able to easily infer the taxonomoy of a website by reading the names of collections. In this example, we have a three-page site (**Index**, **About**, and **Gallery**), with four different types of partials and two other atomic pieces of content (**Card** and **Link**).

```
Card
Link
PartialHero
PartialTwoCol
PartialThreeCol
PartialCards
PageIndex
PageAbout
PageGallery
```

### Translations

Kintaro supports field translation. Simply mark a field as **"translatable"** within the schema editor and the field will be available for translation. When content is synchronized to Grow, the field name is suffixed with `@` – indicating it should be extracted for translation. Content managed in Kintaro can then be extracted per the normal translation process with Grow – leveraging PO files and external translators.

### Draft vs. published

Kintaro supports draft and published content. By using Grow's YAML syntax that varies on the environment name, you can specify when to pull draft content and when to pull published content from Kintaro. Note that the way to indicate to Kintaro that we want published content is to set `project` to `~` (`None`). So, if you wanted to only ever see published content, you would set `project: ~`.

The sample configuration below shows how to display draft content on the development server and in staging, and published content in production (e.g. when using a deployment target named `foo`).

```
# Conditionally pull draft or published content for `grow deploy foo`.
# podspec.yaml

preprocessors:
- kind: kintaro
  repo: example-repo-id
  project: example-project-id
  project@env.prod: ~  # Set `project` to null in prod to build only published content.
  [...]

deployments:
  foo:
    env:
      name: prod  # For env.prod above.
      [...]
```

### Partials

In Grow, **partials** are a way to build pages by including a series of modules
in a specific order and then rendering templates in order. For example, a page
might be built by rendering a hero, a two-column section, and a body section.
Each partial is a different unit of content (in YAML) and a corresponding
template.

You can bind a schema to a partial through various approaches. One technique
illustrated in the example is to keep a mapping of Kintaro schema name to Grow
partial name within a collection's `_blueprint.yaml` and then iterating over
the fields in a document, rendering partials as found.

In a collection's `_blueprint.yaml`:

```
schemas_to_partials:
  sectionHero: hero
  sectionTwoColumn: two-column
  sectionBody: body
```

In a template rendering a document:

```
{% for field in doc.fields.get('$meta').schema.schema_fields %}
  {# Determine whether the field corresponds to a partial. #}
  {% set basename = doc.collection.schemas_to_partials.get(field.name) %}

  {# If the schema name is not mapped to a partial, skip. #}
  {% if not basename %}
    {% continue %}
  {% endif %}

  {# Render the partial with the field values in {{partial}}. #}
  {% with partial = doc.fields.get(field.name) %}
    {% include "/views/partials/" ~ basename ~ ".html" with context %}
  {% endwith %}
{% endfor %}
```

As new schemas are added to Kintaro, simply add an appropriate mapping in
`_blueprint.yaml` (or elsewhere) to determine the corresponding partial.

This repository contains a complete example in:

- `/content/Page/...documents...`
- `/views/partials.html`
- `/views/partials/...templates...`
