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
observation, state, phase, run, or timestamp values are JSON `null`; no values
are inferred. Observation state is attached only when the observation directly
names the image as its primary screenshot, pre-click screenshot, or post-click
screenshot.

Both stored and query vectors are normalized in float32 before inner-product
search, making `IndexFlatIP` scores cosine similarities. Query loading validates
the stored vector norms. Scores outside `[-1, 1]` by more than `1e-4` fail
closed; harmless floating-point overshoot inside that tolerance is clamped.
Indexes without the `l2_float32` state marker must be rebuilt once.

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

## Offline evaluation

The evaluation harness samples indexed images deterministically and uses them
as queries:

```bash
python tools/evaluate_evidence_retrieval.py \
  --sample-size 100 \
  --top-k 5 \
  --output docs/evidence_retrieval_evaluation.md
```

It reports rank-1 exact self retrieval, non-self same-run, same-phase/state,
and failure-association hit rates, plus non-self similarity statistics and
representative cases. Association rates include only queries whose metadata
contains the relevant label.
