import pytest

from app import create_app, db


@pytest.fixture
def app(tmp_path):
    database_path = tmp_path / "test.sqlite"
    application = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret-key",
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path.as_posix()}",
            "WTF_CSRF_ENABLED": False,
            "ADMIN_USERNAME": "test_admin",
            "ADMIN_PASSWORD": "secure-test-admin-password",
        }
    )
    yield application
    with application.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def register_customer(client, username="test_customer", password="secure-customer-password"):
    return client.post(
        "/register",
        data={
            "username": username,
            "password": password,
            "password_confirmation": password,
        },
        follow_redirects=True,
    )


def sign_in(client, username, password):
    return client.post(
        "/login",
        data={"username": username, "password": password},
        follow_redirects=True,
    )
