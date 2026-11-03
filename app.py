import logging
import os
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from functools import wraps

from flask import Flask, abort, flash, redirect, render_template, request, url_for
from flask_login import (
    LoginManager,
    UserMixin,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect, generate_csrf
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from werkzeug.security import check_password_hash, generate_password_hash


db = SQLAlchemy()
csrf = CSRFProtect()
login_manager = LoginManager()
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_]{3,32}$")
MIN_PASSWORD_LENGTH = 12
MAX_TRANSACTION_CENTS = 100_000_000


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(32), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(16), nullable=False, default="customer")
    balance_cents = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    transactions = db.relationship(
        "Transaction",
        back_populates="customer",
        cascade="all, delete-orphan",
        order_by="Transaction.created_at.desc()",
    )

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Transaction(db.Model):
    __tablename__ = "transactions"

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    kind = db.Column(db.String(16), nullable=False)
    amount_cents = db.Column(db.Integer, nullable=False)
    balance_after_cents = db.Column(db.Integer, nullable=False)
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    customer = db.relationship("User", back_populates="transactions")


def valid_username(username):
    return bool(USERNAME_PATTERN.fullmatch(username or ""))


def valid_password(password):
    return isinstance(password, str) and MIN_PASSWORD_LENGTH <= len(password) <= 128


def normalize_database_url(url):
    if url.startswith("postgres://"):
        return "postgresql+psycopg2://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg2://" + url[len("postgresql://") :]
    return url


def provision_admin(app):
    username = app.config.get("ADMIN_USERNAME")
    password = app.config.get("ADMIN_PASSWORD")
    if not username and not password:
        return
    if not username or not password:
        raise RuntimeError("Both ADMIN_USERNAME and ADMIN_PASSWORD must be configured.")
    if not valid_username(username) or not valid_password(password):
        raise RuntimeError(
            "Admin environment credentials do not meet the username and password requirements."
        )

    username = username.lower()
    existing = db.session.scalar(select(User).where(User.username == username))
    if existing is not None and existing.role != "admin":
        raise RuntimeError("The configured admin username is already assigned to a customer.")
    if existing is None:
        existing = User(username=username, role="admin", balance_cents=0)
        db.session.add(existing)
    existing.set_password(password)
    db.session.commit()


def role_required(role):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if current_user.role != role:
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    database_url = os.environ.get("DATABASE_URL", "sqlite:///paran_bank.db")
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY") or os.urandom(32),
        SQLALCHEMY_DATABASE_URI=normalize_database_url(database_url),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        ADMIN_USERNAME=os.environ.get("ADMIN_USERNAME"),
        ADMIN_PASSWORD=os.environ.get("ADMIN_PASSWORD"),
    )
    if test_config:
        app.config.update(test_config)
        app.config["SQLALCHEMY_DATABASE_URI"] = normalize_database_url(
            app.config["SQLALCHEMY_DATABASE_URI"]
        )

    os.makedirs(app.instance_path, exist_ok=True)
    db.init_app(app)
    csrf.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "login"
    login_manager.login_message = "Please sign in to continue."
    login_manager.login_message_category = "info"

    @login_manager.user_loader
    def load_user(user_id):
        try:
            return db.session.get(User, int(user_id))
        except (TypeError, ValueError):
            return None

    @app.context_processor
    def inject_template_helpers():
        return {"csrf_token": generate_csrf}

    @app.template_filter("money")
    def money(cents):
        return f"${cents / 100:,.2f}"

    @app.route("/")
    def index():
        if current_user.is_authenticated:
            return redirect(url_for("admin_dashboard" if current_user.role == "admin" else "dashboard"))
        return redirect(url_for("login"))

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if current_user.is_authenticated:
            return redirect(url_for("index"))
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            confirmation = request.form.get("password_confirmation", "")
            if not valid_username(username):
                flash("Choose a username with 3–32 letters, numbers, or underscores.", "error")
            elif not valid_password(password):
                flash("Use a password between 12 and 128 characters.", "error")
            elif password != confirmation:
                flash("The password confirmation does not match.", "error")
            else:
                customer = User(username=username.lower(), role="customer", balance_cents=0)
                customer.set_password(password)
                db.session.add(customer)
                try:
                    db.session.commit()
                except IntegrityError:
                    db.session.rollback()
                    flash("That username is already taken.", "error")
                except SQLAlchemyError:
                    db.session.rollback()
                    app.logger.exception("Customer registration failed.")
                    flash("We couldn't create your account right now. Please try again.", "error")
                else:
                    login_user(customer)
                    flash("Your prototype account is ready. Welcome to Paran Bank.", "success")
                    return redirect(url_for("dashboard"))
        return render_template("register.html")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for("index"))
        if request.method == "POST":
            username = request.form.get("username", "").strip().lower()
            password = request.form.get("password", "")
            user = db.session.scalar(select(User).where(User.username == username))
            if user is None or not user.check_password(password):
                flash("Username or password is incorrect.", "error")
            else:
                login_user(user)
                return redirect(url_for("admin_dashboard" if user.role == "admin" else "dashboard"))
        return render_template("login.html")

    @app.route("/logout", methods=["POST"])
    @login_required
    def logout():
        logout_user()
        flash("You have been signed out.", "info")
        return redirect(url_for("login"))

    @app.route("/dashboard")
    @role_required("customer")
    def dashboard():
        activity = db.session.scalars(
            select(Transaction)
            .where(Transaction.customer_id == current_user.id)
            .order_by(Transaction.created_at.desc(), Transaction.id.desc())
            .limit(20)
        ).all()
        return render_template("dashboard.html", activity=activity)

    @app.route("/transactions", methods=["POST"])
    @role_required("customer")
    def create_transaction():
        kind = request.form.get("kind", "")
        raw_amount = request.form.get("amount", "").strip()
        if kind not in {"deposit", "withdrawal"}:
            flash("Choose a valid account action.", "error")
            return redirect(url_for("dashboard"))
        try:
            amount = Decimal(raw_amount)
            if not amount.is_finite() or amount <= 0 or amount.quantize(Decimal("0.01")) != amount:
                raise InvalidOperation
            amount_cents = int(amount * 100)
        except (InvalidOperation, ValueError):
            flash("Enter an amount greater than zero with no more than two decimal places.", "error")
            return redirect(url_for("dashboard"))
        if amount_cents > MAX_TRANSACTION_CENTS:
            flash("The maximum amount for one action is $1,000,000.00.", "error")
            return redirect(url_for("dashboard"))

        change = amount_cents if kind == "deposit" else -amount_cents
        statement = update(User).where(User.id == current_user.id)
        if kind == "withdrawal":
            statement = statement.where(User.balance_cents >= amount_cents)
        try:
            result = db.session.execute(
                statement.values(balance_cents=User.balance_cents + change)
            )
            if result.rowcount != 1:
                db.session.rollback()
                flash("There isn't enough simulated balance for that withdrawal.", "error")
                return redirect(url_for("dashboard"))
            balance_after = db.session.scalar(
                select(User.balance_cents).where(User.id == current_user.id)
            )
            db.session.add(
                Transaction(
                    customer_id=current_user.id,
                    kind=kind,
                    amount_cents=amount_cents,
                    balance_after_cents=balance_after,
                )
            )
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            app.logger.exception("Account action failed.")
            flash("We couldn't record that account action. Please try again.", "error")
            return redirect(url_for("dashboard"))

        action_label = "deposit" if kind == "deposit" else "withdrawal"
        flash(f"Simulated {action_label} of ${amount:,.2f} recorded.", "success")
        return redirect(url_for("dashboard"))

    @app.route("/admin")
    @role_required("admin")
    def admin_dashboard():
        customers = db.session.scalars(
            select(User).where(User.role == "customer").order_by(User.created_at.desc())
        ).all()
        return render_template("admin.html", customers=customers)

    @app.route("/admin/customers", methods=["POST"])
    @role_required("admin")
    def create_customer():
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirmation = request.form.get("password_confirmation", "")
        if not valid_username(username):
            flash("Choose a username with 3–32 letters, numbers, or underscores.", "error")
        elif not valid_password(password):
            flash("Use a password between 12 and 128 characters.", "error")
        elif password != confirmation:
            flash("The password confirmation does not match.", "error")
        else:
            customer = User(username=username.lower(), role="customer", balance_cents=0)
            customer.set_password(password)
            db.session.add(customer)
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                flash("That username is already taken.", "error")
            except SQLAlchemyError:
                db.session.rollback()
                app.logger.exception("Admin customer creation failed.")
                flash("We couldn't create that account right now. Please try again.", "error")
            else:
                flash(f"Customer account @{customer.username} created.", "success")
        return redirect(url_for("admin_dashboard"))

    @app.errorhandler(403)
    def forbidden(_error):
        return render_template("error.html", code=403, title="Access restricted"), 403

    with app.app_context():
        db.create_all()
        provision_admin(app)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")
