"""Smoke test for incremental DatabaseStorageBackend upsert/delete."""
import tempfile, os
from services.storage.database_storage import DatabaseStorageBackend


def main():
    tmp = tempfile.mkdtemp()
    db = DatabaseStorageBackend(f"sqlite:///{os.path.join(tmp, 't.db')}")

    # seed via bulk save
    db.save_accounts([
        {"access_token": "a", "status": "正常", "quota": 1},
        {"access_token": "b", "status": "正常", "quota": 2},
    ])
    assert {x["access_token"] for x in db.load_accounts()} == {"a", "b"}

    # upsert existing (update) -> no duplicate, value changed
    db.upsert_account({"access_token": "a", "status": "限流", "quota": 0})
    accts = {x["access_token"]: x for x in db.load_accounts()}
    assert len(accts) == 2, accts
    assert accts["a"]["status"] == "限流" and accts["a"]["quota"] == 0

    # upsert new (insert)
    db.upsert_account({"access_token": "c", "status": "正常"})
    assert {x["access_token"] for x in db.load_accounts()} == {"a", "b", "c"}

    # delete one
    db.delete_account("b")
    assert {x["access_token"] for x in db.load_accounts()} == {"a", "c"}

    # delete non-existent is a no-op
    db.delete_account("zzz")
    assert {x["access_token"] for x in db.load_accounts()} == {"a", "c"}

    # token rotation pattern: delete old + upsert new
    db.delete_account("a")
    db.upsert_account({"access_token": "a2", "status": "正常"})
    assert {x["access_token"] for x in db.load_accounts()} == {"a2", "c"}

    print("INCREMENTAL STORAGE TEST PASSED")


if __name__ == "__main__":
    main()
