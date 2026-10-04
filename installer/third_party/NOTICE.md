# Bundled components

The trial ZIP bundles Astral uv 0.12.12, distributed under MIT or Apache-2.0.
The corresponding license texts are included in this directory.
Source: https://github.com/astral-sh/uv/tree/0.12.12

Python and optional packages are downloaded separately under their own licenses.
The BAAI/bge-m3 model is downloaded only when semantic search is enabled.
Source and model license: https://huggingface.co/BAAI/bge-m3

Personal KB retains the upstream LICENSE and copyright notices.

As of PersonalKB 0.4.0b2, the Windows uv.exe is also tracked in Git so Windows source checkouts can launch directly. The exact executable size and SHA256, verified against the official archive above, are recorded in installer/release.json under uv_binaries. Other platform binaries remain package/build inputs.
