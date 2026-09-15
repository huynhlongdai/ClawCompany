from app.services.vector_search import hash384_embedding, cosine


def test_hash_embedding_is_deterministic():
    a = hash384_embedding("fashion summer dress")
    b = hash384_embedding("fashion summer dress")
    assert a == b
    assert len(a) == 384


def test_cosine_self_similarity():
    a = hash384_embedding("openclaw company agent")
    assert cosine(a, a) > 0.99
