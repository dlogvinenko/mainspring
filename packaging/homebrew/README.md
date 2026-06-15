<!-- SPDX-License-Identifier: Apache-2.0 -->
# Homebrew Packaging Runbook

Mainspring's Homebrew formula is generated from explicit version, URL, and
checksum inputs instead of hand-edited placeholders:

```bash
url=https://github.com/dlogvinenko/mainspring/archive/refs/tags/v1.0.0.tar.gz
mkdir -p dist
curl -fL "$url" -o dist/mainspring-v1.0.0-source.tar.gz

python3 py/homebrew_formula.py \
  --version v1.0.0 \
  --url "$url" \
  --sha256 "$(shasum -a 256 dist/mainspring-v1.0.0-source.tar.gz | awk '{print $1}')" \
  --pyproject pyproject.toml \
  --output ../homebrew-mainspring/Formula/mainspring.rb
```

The generator reads `[project].requires-python` from `pyproject.toml` and maps
that floor to the formula's `python@X.Y` dependency. If the package metadata and
formula cannot be reconciled, generation fails before writing tap metadata.

Before publishing the tap, run `brew update-python-resources mainspring` from
the tap checkout so `rich`, `litellm`, and their transitive Python resources are
vendored into the formula. Then run:

```bash
brew audit --strict --online mainspring
brew install --build-from-source ./Formula/mainspring.rb
brew test mainspring
```

Publishing the tap and proving `brew install <tap>/mainspring` require
maintainer rights on the tap repository and are intentionally outside local CI.
