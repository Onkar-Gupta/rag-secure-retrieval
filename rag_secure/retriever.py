from rag_secure import db


def retrieve(col, conn, question, groups, k=5, threshold=None):
    """Top-k chunks for a question, searching ONLY chunks the user may see.

    The group filter is part of the vector query (condition D), so chunks from other groups are
    never scored, returned or seen by the caller. Quarantined documents are excluded the same way.
    The quarantine list is read here from the database, not passed in, so a caller cannot forget it.
    `threshold` drops chunks whose cosine distance is above it. Returns a list of dicts, closest
    first. No groups means no results.
    """
    if not groups:
        return []
    where = {"group": {"$in": list(groups)}}
    blocked = db.quarantined_docs(conn)
    if blocked:
        where = {"$and": [where, {"doc_id": {"$nin": blocked}}]}
    res = col.query(query_texts=[question], n_results=k, where=where)
    hits = []
    for cid, text, meta, dist in zip(
        res["ids"][0], res["documents"][0], res["metadatas"][0], res["distances"][0]
    ):
        if threshold is None or dist <= threshold:
            hits.append({"chunk_id": cid, "text": text, "distance": dist, **meta})
    return hits
