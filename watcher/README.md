# kintaro-watcher

A microservice that polls Kintaro for changes to a project and runs a webhook
if there were any changes since last run.

## Concept

Since Kintaro does not have the ability to run webhooks when content changes,
this microservice will poll Kintaro for changes to a project, then execute a
webhook if there were changes since it last run.

By default, the polling time is about every minute, depending on how long
webhook URLs take to execute.

## Usage

1. Configure the cron, and deploy the app.
1. Share your Kintaro collection with the app's service account.
1. Use the [Google Cloud Console Datastore
   Viewer](https://console.cloud.google.com/datastore/entities/query) to add
   `Watch` entities.

## Webhook URL formats

Webhook URLs can accept the following parameters:

```
project_created            # Time in ms.
project_created_by         # Email address.
project_id                 # Kintaro project ID.
project_modified           # Time in ms.
project_modified_by        # Email address.
repo_id                    # Kintaro repo ID.
translations_up_to_date    # True/False.
```

For example, to execute a Circle CI build, use a webhook URL like the
following. Note that your build environment will also need to be able to access
Kintaro.

```
https://circleci.com/api/v1/project/<username>/<project_name>/tree/<branch_name>?circle-token=<token>
```

## TODO

- Customize the HTTP request method used for webhooks
- An actual user interface for managing webhooks
