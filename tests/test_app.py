from sqlalchemy import select

from app import Transaction, User, create_app, db
from conftest import register_customer, sign_in


PASSWORD = "secure-customer-password"


def test_registration_hashes_password_and_signs_in_customer(client, app):
    response = register_customer(client)

    assert response.status_code == 200
    assert b"Your prototype account is ready" in response.data
    assert b"$0.00" in response.data
    with app.app_context():
        customer = db.session.scalar(select(User).where(User.username == "test_customer"))
        assert customer is not None
        assert customer.password_hash != PASSWORD
        assert customer.check_password(PASSWORD)
        assert customer.role == "customer"


def test_registration_validates_username_password_and_confirmation(client):
    invalid_username = client.post(
        "/register",
        data={"username": "bad name", "password": PASSWORD, "password_confirmation": PASSWORD},
    )
    assert b"Choose a username" in invalid_username.data

    invalid_password = client.post(
        "/register",
        data={"username": "valid_name", "password": "short", "password_confirmation": "short"},
    )
    assert b"Use a password between 12 and 128 characters" in invalid_password.data

    mismatch = client.post(
        "/register",
        data={"username": "valid_name", "password": PASSWORD, "password_confirmation": "different"},
    )
    assert b"password confirmation does not match" in mismatch.data


def test_duplicate_usernames_are_case_insensitive(client):
    register_customer(client, username="Example")
    client.post("/logout")
    response = client.post(
        "/register",
        data={"username": "example", "password": PASSWORD, "password_confirmation": PASSWORD},
    )

    assert b"That username is already taken" in response.data


def test_login_logout_and_password_check(client):
    register_customer(client)
    client.post("/logout", follow_redirects=True)

    bad_login = client.post(
        "/login", data={"username": "test_customer", "password": "incorrect-password"}
    )
    assert b"Username or password is incorrect" in bad_login.data

    good_login = sign_in(client, "test_customer", PASSWORD)
    assert b"Good day, test_customer" in good_login.data
    signed_out = client.post("/logout", follow_redirects=True)
    assert b"You have been signed out" in signed_out.data
    assert b"Sign in to pick up where you left off" in signed_out.data


def test_customer_and_admin_authorization(client):
    response = client.get("/dashboard", follow_redirects=False)
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]

    admin_login = sign_in(client, "test_admin", "secure-test-admin-password")
    assert b"Account overview" in admin_login.data
    assert client.get("/dashboard").status_code == 403
    assert client.get("/admin").status_code == 200

    client.post("/logout")
    register_customer(client)
    assert client.get("/admin").status_code == 403


def test_csrf_rejects_unprotected_post(tmp_path):
    application = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "csrf-test-secret",
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{(tmp_path / 'csrf.sqlite').as_posix()}",
            "ADMIN_USERNAME": None,
            "ADMIN_PASSWORD": None,
        }
    )
    response = application.test_client().post(
        "/register",
        data={
            "username": "csrf_customer",
            "password": PASSWORD,
            "password_confirmation": PASSWORD,
        },
    )
    assert response.status_code == 400
    with application.app_context():
        db.drop_all()


def test_no_admin_exists_without_environment_credentials(tmp_path):
    application = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "no-admin-test-secret",
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{(tmp_path / 'no-admin.sqlite').as_posix()}",
            "ADMIN_USERNAME": None,
            "ADMIN_PASSWORD": None,
        }
    )
    with application.app_context():
        assert db.session.scalar(select(User).where(User.role == "admin")) is None
        db.drop_all()


def test_deposit_withdrawal_and_overdraft_protection(client, app):
    register_customer(client)
    deposit = client.post(
        "/transactions", data={"kind": "deposit", "amount": "125.50"}, follow_redirects=True
    )
    assert b"Simulated deposit of $125.50 recorded" in deposit.data
    assert b"$125.50" in deposit.data

    withdrawal = client.post(
        "/transactions", data={"kind": "withdrawal", "amount": "25.25"}, follow_redirects=True
    )
    assert b"Simulated withdrawal of $25.25 recorded" in withdrawal.data
    assert b"$100.25" in withdrawal.data

    declined = client.post(
        "/transactions", data={"kind": "withdrawal", "amount": "100.26"}, follow_redirects=True
    )
    assert b"There isn&#39;t enough simulated balance" in declined.data
    with app.app_context():
        customer = db.session.scalar(select(User).where(User.username == "test_customer"))
        history = db.session.scalars(select(Transaction).where(Transaction.customer_id == customer.id)).all()
        assert customer.balance_cents == 10_025
        assert len(history) == 2
        assert {entry.kind for entry in history} == {"deposit", "withdrawal"}
        assert all(entry.balance_after_cents >= 0 for entry in history)


def test_invalid_transaction_amounts_are_rejected(client):
    register_customer(client)
    for amount in ("0", "-1", "1.001", "not-a-number", "NaN", "1000000.01"):
        response = client.post(
            "/transactions",
            data={"kind": "deposit", "amount": amount},
            follow_redirects=True,
        )
        assert b"Enter an amount" in response.data or b"maximum amount" in response.data


def test_admin_can_create_customer_and_customers_cannot(client, app):
    sign_in(client, "test_admin", "secure-test-admin-password")
    response = client.post(
        "/admin/customers",
        data={
            "username": "new_customer",
            "password": PASSWORD,
            "password_confirmation": PASSWORD,
        },
        follow_redirects=True,
    )
    assert b"Customer account @new_customer created" in response.data
    with app.app_context():
        customer = db.session.scalar(select(User).where(User.username == "new_customer"))
        assert customer is not None
        assert customer.role == "customer"
        assert customer.balance_cents == 0
        assert customer.check_password(PASSWORD)

    client.post("/logout")
    register_customer(client)
    forbidden = client.post(
        "/admin/customers",
        data={
            "username": "not_allowed",
            "password": PASSWORD,
            "password_confirmation": PASSWORD,
        },
    )
    assert forbidden.status_code == 403


def test_database_persists_across_app_instances(tmp_path):
    database_path = tmp_path / "persistent.sqlite"
    uri = f"sqlite:///{database_path.as_posix()}"
    first_app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "persistent-test-secret",
            "SQLALCHEMY_DATABASE_URI": uri,
            "ADMIN_USERNAME": None,
            "ADMIN_PASSWORD": None,
        }
    )
    with first_app.app_context():
        customer = User(username="persistent_user", role="customer")
        customer.set_password(PASSWORD)
        db.session.add(customer)
        db.session.commit()
        customer_id = customer.id
        db.session.remove()

    second_app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "persistent-test-secret",
            "SQLALCHEMY_DATABASE_URI": uri,
            "ADMIN_USERNAME": None,
            "ADMIN_PASSWORD": None,
        }
    )
    with second_app.app_context():
        persisted = db.session.get(User, customer_id)
        assert persisted is not None
        assert persisted.username == "persistent_user"
        assert persisted.check_password(PASSWORD)
        db.session.remove()

    for application in (first_app, second_app):
        with application.app_context():
            db.drop_all()
