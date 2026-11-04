def retrieve(col, question, groups, k=5, threshold=None, exclude_docs=()):
    """Top-k chunks for a question, searching ONLY chunks whose group is in `groups`.

    The group filter is part of the vector query (condition D), so chunks from other groups are
    never scored, returned or seen by the caller. `exclude_docs` removes quarantined documents the
    same way. `threshold` drops chunks whose cosine distance is above it. Returns a list of dicts,
    closest first. No groups means no results.
    """
    if not groups:
        return []
    where = {"group": {"$in": list(groups)}}
    if exclude_docs:
        where = {"$and": [where, {"doc_id": {"$nin": list(exclude_docs)}}]}
    res = col.query(query_texts=[question], n_results=k, where=where)
    hits = []
    for cid, text, meta, dist in zip(
        res["ids"][0], res["documents"][0], res["metadatas"][0], res["distances"][0]
    ):
        if threshold is None or dist <= threshold:
            hits.append({"chunk_id": cid, "text": text, "distance": dist, **meta})
    return hits
