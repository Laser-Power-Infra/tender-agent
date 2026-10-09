"""One-off: re-embed relevance feedback points stored before `brief_text` was read as the brief.

Those points have brief='' and a vector built from the whole feedback chunk. Re-parse the chunk,
embed the brief alone, and rewrite brief/feedback in place (same point id, no new feedback rows).

Run: uv run python -m scripts.reembed_feedback
"""
from qdrant_client.http.models import PointStruct

from core.config import settings
from relevance.nodes.feedback import BRIEF_KEYS
from vector.embeddings import get_dense
from vector.qdrant import qdrant


def parse(chunk: str) -> dict[str, str]:
    # chunk is "k: v" per line (see embed_feedback); a value never spans lines
    return dict(line.split(": ", 1) for line in chunk.splitlines() if ": " in line)


def main():
    coll = settings.relevance_collection
    fixed, offset = 0, None
    while True:
        pts, offset = qdrant.scroll(coll, limit=100, offset=offset, with_payload=True)
        for p in pts:
            payload = p.payload or {}
            if payload.get("brief"):
                continue
            extra = parse(payload.get("text") or "")
            brief = next((extra[k].strip() for k in BRIEF_KEYS if extra.get(k)), "")
            if not brief:
                continue
            payload["brief"] = brief
            payload["feedback"] = "\n".join(f"{k}: {v}" for k, v in extra.items() if k not in BRIEF_KEYS)
            vec = get_dense().embed_documents([brief])[0]
            qdrant.upsert(coll, points=[PointStruct(id=p.id, vector={"dense": vec}, payload=payload)], wait=True)
            fixed += 1
            print("re-embedded", payload.get("reference_no"))
        if offset is None:
            break
    print(f"done, {fixed} point(s) fixed")


if __name__ == "__main__":
    main()
