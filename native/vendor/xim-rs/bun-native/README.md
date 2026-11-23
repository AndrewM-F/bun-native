# Vendored zed-xim

This source is from `zed-industries/xim-rs` commit `16f35a2c881b815a2b6cdfd6687988e84f8447d8`, previously pinned as a Git dependency. The only source change is the root manifest's `x11rb` requirement from 0.13 to 0.14. This is a local fork, not a published replacement for zed-xim; re-evaluate and remove it when upstream supports a compatible version. The upstream MIT license is retained.

`upstream.json` records the original bytes and SHA-256 of every retained upstream file. `tests/quality/test_xim_vendor.py` verifies the exact inventory and restores the manifest requirement in memory before comparing the hashes.
