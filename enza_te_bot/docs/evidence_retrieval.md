# Evidence retrieval

`tools/query_evidence.py` turns the existing visual index into a read-only
historical evidence lookup. It embeds one current screenshot with the exact
model recorded in `index/index_state.json`, searches the aligned FAISS index,
and joins each result to its `metadata.jsonl` row.

```text
Screenshot
    |
    v
SigLIP embedding
    |
    v
FAISS

Screenshot
    |
    v
Retriever
    |
    v
Historical Evidence Package
    + trajectory
    + failure
    + state
    |
    v
Decision Agent
```

The retriever does not grant action authority or change runtime policy. It
returns only fields present in indexed metadata. Missing trajectory, failure,
state, run, or timestamp values are JSON `null`; no values are inferred.

## Usage

```bash
export ENZA_DATA_ROOT=~/data/enza_ai
python tools/query_evidence.py \
  --image /path/to/current.png \
  --top-k 5
```

The command loads these existing files:

- `$ENZA_DATA_ROOT/index/image_embeddings.faiss`
- `$ENZA_DATA_ROOT/index/metadata.jsonl`
- `$ENZA_DATA_ROOT/index/index_state.json`

CUDA is mandatory because the query screenshot must use the same SigLIP image
embedding path as index construction. The command fails closed when CUDA,
the query image, index files, model ID, vector alignment, or dimensions are
missing or inconsistent.
