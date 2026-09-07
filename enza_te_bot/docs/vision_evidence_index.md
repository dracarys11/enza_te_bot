# WING visual evidence index

`tools/build_vision_index.py` scans an external Enza data root without changing
source evidence. It reads images from:

- `wing_runs/*/screenshots/`
- `dataset/evidence/`

It writes only to `$ENZA_DATA_ROOT/index/`:

- `metadata.jsonl`: one row per image, aligned to `vector_id` in FAISS
- `image_embeddings.faiss`: normalized image embeddings in an inner-product index
- `index_state.json`: model, vector dimension, GPU, count, and update timestamp

## RTX 5080 WSL setup

Install the CUDA-enabled PyTorch build appropriate for the WSL driver first.
Then install the model and index dependencies in that environment:

```bash
python -m pip install transformers Pillow faiss-cpu
```

The command deliberately rejects CPU and MPS embedding. Model weights are
downloaded by Transformers on first use, so the node must have the model in its
Hugging Face cache or have network access for the initial build.

## Scan, build, and query

```bash
export ENZA_DATA_ROOT=/data/enza_data
python tools/build_vision_index.py scan
python tools/build_vision_index.py build --model google/siglip-base-patch16-224 --batch-size 64
python tools/build_vision_index.py query "audition battle result screen" --top-k 5
```

Re-running `build` is a no-op when paths and hashes are unchanged. New paths are
embedded and appended. Removed files, changed bytes, a changed model, or an
index/metadata count mismatch triggers a complete rebuild so vector IDs cannot
silently drift from metadata.
