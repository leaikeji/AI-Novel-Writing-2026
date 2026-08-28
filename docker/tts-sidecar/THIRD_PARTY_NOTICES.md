# Third-party notices and current redistribution boundary

This file is an engineering inventory, not legal advice or final production
redistribution approval.

| Component | Frozen version/revision | Observed license boundary |
| --- | --- | --- |
| MOSS-TTS-Nano source | `cc7bdf19c7639c0870dab22045a33b442760f6be` | Apache-2.0 source metadata; source is not copied into this dependency image |
| MOSS-TTS-Nano-100M-ONNX | `f52645cb467506d8e18e746ddd59482685b74e58` | Model repository metadata says Apache-2.0; weights are not copied into the image |
| MOSS-Audio-Tokenizer-Nano-ONNX | `ceff0d0749bfb3fa2d61149794ec6feef0d1e1ae` | Model repository metadata says Apache-2.0; weights are not copied into the image |
| FFmpeg | 9.0.1 / source SHA-256 `cf38e0e…f635` | Narrow static LGPL-2.1-or-later build; GPL, version3, nonfree, network and autodetect disabled; license files are copied from the fixed source build |
| PyTorch / Torchaudio | 2.7.0 | BSD-style upstream licensing; exact wheels are selected by `requirements.lock` hashes |
| ONNX Runtime | 1.24.3 | MIT; exact aarch64 wheel selected by hash |
| Transformers | 4.57.1 | Apache-2.0; exact wheel selected by hash |
| SoundFile / libsndfile | 0.14.0 / bundled wheel runtime | SoundFile BSD-3-Clause; bundled libsndfile retains its LGPL obligations |
| GNU OpenMP runtime | fixed Debian `20260825T000000Z` snapshot | GCC Runtime Library Exception applies; exact runtime hash is verified |

The complete Python closure is installed with `pip --require-hashes` from
`requirements.lock`; installed distribution metadata remains in the image.
Before registry publication, the project still requires a final license archive
and redistribution review, including the FFmpeg source signature/PGP chain and
model-weight distribution rights. Voice presets and private reference recordings
are outside this image and outside T1-DEP approval.
