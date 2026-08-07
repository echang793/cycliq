import community
import db


def second_account(client):
    """A separate TestClient session so two members can interact."""
    from fastapi.testclient import TestClient

    import server

    other = TestClient(server.app)
    other.post("/api/auth/signup", json={"email": "other@example.com", "password": "correct horse battery"})
    return other


def test_contact_details_are_stripped():
    assert "@" not in community.scrub("dm me at jane@example.com")
    assert "[removed]" in community.scrub("call me on +1 415 555 0132")
    assert "[removed]" in community.scrub("find me on instagram.com/whoever")
    assert community.scrub("  my cramps are awful  ") == "my cramps are awful"


def test_post_carries_handle_not_email(signed_in):
    me = signed_in.get("/api/me").json()["user"]
    post = signed_in.post(
        "/api/community/posts", json={"topic": "cycle", "body": "Day 2 and I am wrecked."}
    ).json()["post"]
    assert post["handle"] == me["handle"]
    assert "@" not in post["handle"]
    assert post["mine"] is True


def test_user_id_is_never_returned(signed_in):
    signed_in.post("/api/community/posts", json={"topic": "pcos", "body": "Anyone else?"})
    body = signed_in.get("/api/community/posts").text
    assert "user_id" not in body


def test_unknown_topic_rejected(signed_in):
    assert signed_in.post(
        "/api/community/posts", json={"topic": "astrology", "body": "hi"}
    ).status_code == 400
    assert signed_in.get("/api/community/posts?topic=astrology").status_code == 400


def test_replies_and_counts(signed_in):
    post_id = signed_in.post(
        "/api/community/posts", json={"topic": "ttc", "body": "Cycle 4 of trying."}
    ).json()["post"]["id"]
    other = second_account(signed_in)
    other.post(f"/api/community/posts/{post_id}/replies", json={"body": "Cycle 7 here. It is hard."})

    detail = signed_in.get(f"/api/community/posts/{post_id}").json()
    assert len(detail["replies"]) == 1
    assert detail["replies"][0]["mine"] is False
    assert detail["post"]["replies"] == 1


def test_reactions_toggle_and_count_once_per_user(signed_in):
    post_id = signed_in.post(
        "/api/community/posts", json={"topic": "cycle", "body": "Solidarity."}
    ).json()["post"]["id"]

    first = signed_in.post("/api/community/react", json={"target_kind": "post", "target_id": post_id}).json()
    assert first == {"reacted": True, "hearts": 1}
    # Same user reacting again removes it rather than double-counting.
    second = signed_in.post("/api/community/react", json={"target_kind": "post", "target_id": post_id}).json()
    assert second == {"reacted": False, "hearts": 0}


def test_reports_hide_a_post_at_threshold(signed_in):
    post_id = signed_in.post(
        "/api/community/posts", json={"topic": "general", "body": "Buy my miracle cure."}
    ).json()["post"]["id"]

    for _ in range(community.HIDE_AFTER_REPORTS):
        signed_in.post("/api/community/report", json={"target_kind": "post", "target_id": post_id})

    row = db.query_one("SELECT hidden FROM community_posts WHERE id = ?", (post_id,))
    assert row["hidden"] == 1
    assert all(p["id"] != post_id for p in signed_in.get("/api/community/posts").json()["posts"])
    assert signed_in.get(f"/api/community/posts/{post_id}").status_code == 404


def test_only_the_author_can_delete(signed_in):
    post_id = signed_in.post(
        "/api/community/posts", json={"topic": "cycle", "body": "Mine to delete."}
    ).json()["post"]["id"]
    other = second_account(signed_in)
    assert other.delete(f"/api/community/posts/{post_id}").status_code == 404
    assert signed_in.delete(f"/api/community/posts/{post_id}").status_code == 200


def test_empty_body_rejected(signed_in):
    # Whitespace-only survives the length validator but not the scrubber.
    assert signed_in.post("/api/community/posts", json={"topic": "cycle", "body": "   "}).status_code == 400
    # A body that is nothing but contact details scrubs down to a placeholder,
    # which is still a post — the point is that the address does not survive.
    res = signed_in.post("/api/community/posts", json={"topic": "cycle", "body": "jane@example.com"})
    assert res.status_code == 200
    assert "jane@example.com" not in res.json()["post"]["body"]
    assert signed_in.post("/api/community/posts", json={"topic": "cycle", "body": ""}).status_code == 422


def test_deleting_an_account_leaves_the_thread_readable(signed_in):
    post_id = signed_in.post(
        "/api/community/posts", json={"topic": "endo", "body": "Ten years to diagnosis."}
    ).json()["post"]["id"]
    other = second_account(signed_in)
    signed_in.delete("/api/me")
    # The post survives with its pseudonym; the account link is severed.
    detail = other.get(f"/api/community/posts/{post_id}").json()
    assert detail["post"]["body"].startswith("Ten years")
    assert db.query_one("SELECT user_id FROM community_posts WHERE id = ?", (post_id,))["user_id"] is None
