# grow-ext-kintaro

(WIP) Kintaro Content Server extension for Grow.

## Usage

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
