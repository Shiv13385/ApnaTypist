from flask import Flask, render_template, request, redirect, url_for, flash, session, send_from_directory
import sqlite3
import os
import secrets
import resend

from dotenv import load_dotenv
from werkzeug.utils import secure_filename


# =========================
# LOAD ENVIRONMENT
# =========================

load_dotenv()


# =========================
# BASIC SETUP
# =========================

app = Flask(__name__)

app.secret_key = os.environ.get("FLASK_SECRET_KEY")

if not app.secret_key:
    raise RuntimeError(
        "FLASK_SECRET_KEY is missing in .env file."
    )


# =========================
# SESSION SECURITY
# =========================

app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

app.config["SESSION_COOKIE_SECURE"] = os.environ.get(
    "SESSION_COOKIE_SECURE",
    "False"
).lower() == "true"


# =========================
# MAXIMUM UPLOAD SIZE
# =========================

app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024


# =========================
# PATHS
# =========================

UPLOAD_FOLDER = "uploads"
DB_NAME = "contacts.db"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# =========================
# ALLOWED FILE TYPES
# =========================

ALLOWED_EXTENSIONS = {
    "pdf",
    "doc",
    "docx",
    "xls",
    "xlsx",
    "jpg",
    "jpeg",
    "png",
    "webp",
}


def allowed_file(filename):

    if not filename or "." not in filename:
        return False

    extension = filename.rsplit(".", 1)[1].lower()

    return extension in ALLOWED_EXTENSIONS


# =========================
# SERVICE RATES
# =========================

SERVICE_RATES = {
    "PDF to Word": 10,
    "Image to Word": 10,
    "Hindi Image to Word": 15,
    "PDF to Excel": 20,
    "Manual Typing - English": 15,
    "Manual Typing - Hindi": 20,
    "Data Entry": 20,
    "Formatting & Proofreading": 10,
}


# =========================
# DATABASE
# =========================

def get_db():

    conn = sqlite3.connect(DB_NAME)

    conn.row_factory = sqlite3.Row

    return conn


def init_db():

    conn = get_db()

    # CONTACTS TABLE
    conn.execute("""
        CREATE TABLE IF NOT EXISTS contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            email TEXT,
            phone TEXT,
            message TEXT
        )
    """)

    # ORDERS TABLE
    conn.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            phone TEXT NOT NULL,
            work_type TEXT NOT NULL,
            file_names TEXT NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 1,
            rate INTEGER NOT NULL DEFAULT 0,
            total_amount INTEGER NOT NULL DEFAULT 0,
            payment_reference TEXT,
            payment_status TEXT NOT NULL DEFAULT 'Pending Verification',
            status TEXT NOT NULL DEFAULT 'Pending',
            deadline TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # CHECK EXISTING COLUMNS
    existing = {
        row["name"]
        for row in conn.execute(
            "PRAGMA table_info(orders)"
        ).fetchall()
    }

    additions = {
        "quantity": "INTEGER NOT NULL DEFAULT 1",
        "rate": "INTEGER NOT NULL DEFAULT 0",
        "total_amount": "INTEGER NOT NULL DEFAULT 0",
        "payment_reference": "TEXT",
        "payment_status": "TEXT NOT NULL DEFAULT 'Pending Verification'",
        "deadline": "TEXT",
    }

    for column, definition in additions.items():

        if column not in existing:

            conn.execute(
                f"ALTER TABLE orders ADD COLUMN {column} {definition}"
            )

    conn.commit()

    conn.close()


init_db()


# =========================
# EMAIL CONFIG CHECK
# =========================

print("========================================")
print("           EMAIL CONFIGURATION")
print("========================================")

print(
    "RESEND_API_KEY configured:",
    bool(os.environ.get("RESEND_API_KEY"))
)

print(
    "ADMIN_EMAIL configured:",
    bool(os.environ.get("ADMIN_EMAIL"))
)

if os.environ.get("ADMIN_EMAIL"):
    print(
        "Admin email:",
        os.environ.get("ADMIN_EMAIL")
    )

print("========================================")


# =========================
# EMAIL FUNCTION
# =========================

def send_email(subject, body, receiver):
    """
    Send an email through Resend API.
    """

    print()
    print("=== RESEND EMAIL FUNCTION CALLED ===")

    api_key = os.environ.get("RESEND_API_KEY")

    print(
        "RESEND_API_KEY exists:",
        bool(api_key)
    )

    # API KEY CHECK
    if not api_key:

        print(
            "ERROR: RESEND_API_KEY is not configured."
        )

        return False

    # RECEIVER CHECK
    if not receiver:

        print(
            "ERROR: Receiver email is missing."
        )

        return False

    receiver = receiver.strip()

    if not receiver:

        print(
            "ERROR: Receiver email is empty."
        )

        return False

    try:

        resend.api_key = api_key

        params = {
            "from": "Apna Typist <admin@apnatypist.in>",
            "to": [receiver],
            "subject": subject,
            "html": body,
        }

        print(
            "Sending email to:",
            receiver
        )

        response = resend.Emails.send(params)

        print(
            "RESEND RESPONSE:",
            response
        )

        print(
            "EMAIL SENT SUCCESSFULLY TO:",
            receiver
        )

        return True

    except Exception as e:

        print(
            "RESEND EMAIL ERROR:",
            repr(e)
        )

        return False


# =========================
# ORDER ID
# =========================

def generate_order_id():

    conn = get_db()

    try:

        while True:

            oid = (
                "AT"
                + secrets.token_hex(3).upper()
            )

            existing = conn.execute(
                """
                SELECT 1
                FROM orders
                WHERE order_id=?
                """,
                (oid,)
            ).fetchone()

            if not existing:

                return oid

    finally:

        conn.close()


# =========================
# HOME
# =========================

@app.route("/")
def home():

    return render_template(
        "index.html"
    )


# =========================
# PAYMENT PAGE
# =========================

@app.route("/payment")
def payment():

    return render_template(
        "payment.html",
        service_rates=SERVICE_RATES
    )


# =========================
# UPLOAD / PLACE ORDER
# =========================

@app.route("/upload", methods=["POST"])
def upload():

    name = request.form.get(
        "name",
        ""
    ).strip()

    email = request.form.get(
        "email",
        ""
    ).strip()

    phone = request.form.get(
        "phone",
        ""
    ).strip()

    work_type = request.form.get(
        "work_type",
        ""
    ).strip()

    payment_reference = request.form.get(
        "payment_reference",
        ""
    ).strip()


    # =========================
    # GET FILES
    # =========================

    files = [
        f
        for f in request.files.getlist("documents")
        if f and f.filename
    ]


    # =========================
    # QUANTITY
    # =========================

    try:

        quantity = int(
            request.form.get(
                "quantity",
                "0"
            )
        )

    except ValueError:

        quantity = 0


    # =========================
    # BASIC VALIDATION
    # =========================

    if (
        not name
        or not email
        or not phone
        or work_type not in SERVICE_RATES
        or not files
    ):

        flash(
            "Please fill all details and select at least one file.",
            "danger"
        )

        return redirect(
            url_for("payment")
        )


    # =========================
    # QUANTITY VALIDATION
    # =========================

    if quantity <= 0:

        flash(
            "Please enter a valid number of pages/sheets.",
            "danger"
        )

        return redirect(
            url_for("payment")
        )


    # =========================
    # PAYMENT REFERENCE
    # =========================

    if (
        not payment_reference
        or len(payment_reference) < 6
    ):

        flash(
            "Please enter your UTR / Transaction ID after payment.",
            "danger"
        )

        return redirect(
            url_for("payment")
        )


    # =========================
    # RATE / TOTAL
    # =========================

    rate = SERVICE_RATES[work_type]

    total = quantity * rate


    # =========================
    # GENERATE ORDER ID
    # =========================

    oid = generate_order_id()


    # =========================
    # ORDER FOLDER
    # =========================

    order_folder = os.path.join(
        UPLOAD_FOLDER,
        oid
    )

    os.makedirs(
        order_folder,
        exist_ok=True
    )


    saved = []


    # =========================
    # SAVE FILES
    # =========================

    for f in files:

        if not allowed_file(
            f.filename
        ):

            flash(
                f"File type not allowed: {f.filename}",
                "danger"
            )

            return redirect(
                url_for("payment")
            )


        safe = secure_filename(
            f.filename
        )

        if not safe:
            continue


        stem, ext = os.path.splitext(
            safe
        )

        path = os.path.join(
            order_folder,
            safe
        )

        number = 1


        while os.path.exists(path):

            safe = (
                f"{stem}_{number}{ext}"
            )

            path = os.path.join(
                order_folder,
                safe
            )

            number += 1


        f.save(path)


        saved.append(
            f"{oid}/{safe}"
        )


    # =========================
    # CHECK SAVED FILES
    # =========================

    if not saved:

        try:

            os.rmdir(
                order_folder
            )

        except OSError:

            pass


        flash(
            "No valid file was uploaded.",
            "danger"
        )

        return redirect(
            url_for("payment")
        )


    # =========================
    # SAVE ORDER TO DATABASE
    # =========================

    conn = get_db()

    conn.execute(
        """
        INSERT INTO orders
        (
            order_id,
            name,
            email,
            phone,
            work_type,
            file_names,
            quantity,
            rate,
            total_amount,
            payment_reference,
            payment_status,
            status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            oid,
            name,
            email,
            phone,
            work_type,
            "\n".join(saved),
            quantity,
            rate,
            total,
            payment_reference,
            "Pending Verification",
            "Pending"
        )
    )

    conn.commit()

    conn.close()


    # ==================================================
    # SEND EMAIL TO ADMIN
    # ==================================================

    admin_email = os.environ.get(
        "ADMIN_EMAIL"
    )

    admin_email_result = send_email(
        f"New Apna Typist Order - {oid}",
        f"""
A new order has been received.

Order ID: {oid}

Name: {name}
Email: {email}
Phone: {phone}

Work: {work_type}
Quantity: {quantity}
Rate: ₹{rate}
Total: ₹{total}

UTR / Transaction ID:
{payment_reference}

Uploaded Files:
{chr(10).join(saved)}

Payment Status: Pending Verification
Order Status: Pending
""",
        receiver=admin_email
    )

    print(
        "ADMIN ORDER EMAIL RESULT:",
        admin_email_result
    )


    # ==================================================
    # SEND CONFIRMATION EMAIL TO CUSTOMER
    # ==================================================

    customer_email_result = send_email(
        f"Apna Typist - Order Received ({oid})",
        f"""
Hello {name},

Thank you for placing your order with Apna Typist.

Your order has been received successfully.

Order ID: {oid}
Service: {work_type}
Quantity: {quantity}
Rate: ₹{rate}
Total Amount: ₹{total}

UTR / Transaction ID:
{payment_reference}

Payment Status: Pending Verification
Order Status: Pending

Uploaded Files:
{chr(10).join(saved)}

We will verify your payment and start processing your order.

You can use your Order ID and email address on the Track Order page to check your order status.

Thank you,
Apna Typist
""",
        receiver=email
    )

    print(
        "CUSTOMER ORDER EMAIL RESULT:",
        customer_email_result
    )


    # =========================
    # SUCCESS PAGE
    # =========================

    return render_template(
        "order_success.html",
        order_id=oid,
        name=name,
        email=email,
        work_type=work_type,
        quantity=quantity,
        rate=rate,
        total_amount=total,
        payment_reference=payment_reference
    )


# =========================
# TRACK ORDER
# =========================

@app.route(
    "/track",
    methods=["GET", "POST"]
)
def track():

    order = None

    searched = False


    if request.method == "POST":

        searched = True

        oid = request.form.get(
            "order_id",
            ""
        ).strip().upper()

        email = request.form.get(
            "email",
            ""
        ).strip().lower()


        conn = get_db()

        order = conn.execute(
            """
            SELECT *
            FROM orders
            WHERE order_id=?
            AND lower(email)=?
            """,
            (
                oid,
                email
            )
        ).fetchone()

        conn.close()


    return render_template(
        "track_order.html",
        order=order,
        searched=searched
    )


# =========================
# ADMIN LOGIN
# =========================

@app.route(
    "/admin",
    methods=["GET", "POST"]
)
def admin():

    if request.method == "POST":

        key = request.form.get(
            "key",
            ""
        ).strip()

        expected = os.environ.get(
            "ADMIN_KEY"
        )


        if not expected:

            flash(
                "Admin key is not configured in .env file.",
                "danger"
            )

            return render_template(
                "admin_login.html"
            )


        if secrets.compare_digest(
            key,
            expected
        ):

            session.clear()

            session["admin_logged_in"] = True

            return redirect(
                url_for("admin")
            )


        flash(
            "Invalid admin key.",
            "danger"
        )


    if not session.get(
        "admin_logged_in"
    ):

        return render_template(
            "admin_login.html"
        )


    conn = get_db()


    orders = conn.execute(
        """
        SELECT *
        FROM orders
        ORDER BY id DESC
        """
    ).fetchall()


    contacts = conn.execute(
        """
        SELECT *
        FROM contacts
        ORDER BY id DESC
        """
    ).fetchall()


    conn.close()


    return render_template(
        "admin.html",
        orders=orders,
        contacts=contacts
    )


# =========================================================
# ADMIN - LIST ORDER FILES
# =========================================================

@app.route(
    "/admin/order-files-list/<order_id>"
)
def order_files_list(order_id):

    if not session.get(
        "admin_logged_in"
    ):

        return {
            "error": "Unauthorized"
        }, 401


    conn = get_db()


    order = conn.execute(
        """
        SELECT file_names
        FROM orders
        WHERE order_id=?
        """,
        (order_id,)
    ).fetchone()


    conn.close()


    if not order:

        return {
            "error": "Order not found"
        }, 404


    files = []


    stored_files = (
        order["file_names"]
        or ""
    )


    for stored_file in stored_files.splitlines():

        stored_file = stored_file.strip()

        if not stored_file:
            continue


        normalized = (
            stored_file.replace(
                "\\",
                "/"
            )
        )


        prefix = order_id + "/"


        if normalized.startswith(
            prefix
        ):

            filename = normalized[
                len(prefix):
            ]

            filename = secure_filename(
                filename
            )


            if filename:

                files.append(
                    filename
                )


    return {
        "order_id": order_id,
        "files": files
    }


# =========================================================
# ADMIN - VIEW / DOWNLOAD FILE
# =========================================================

@app.route(
    "/admin/order-files/<order_id>/<filename>"
)
def order_file(
    order_id,
    filename
):

    if not session.get(
        "admin_logged_in"
    ):

        return "Unauthorized", 401


    safe_filename = secure_filename(
        filename
    )


    if not safe_filename:

        return "Invalid file name", 400


    conn = get_db()


    order = conn.execute(
        """
        SELECT file_names
        FROM orders
        WHERE order_id=?
        """,
        (order_id,)
    ).fetchone()


    conn.close()


    if not order:

        return "Order not found", 404


    stored_files = (
        order["file_names"]
        or ""
    )


    allowed = False


    for stored_file in stored_files.splitlines():

        stored_file = stored_file.strip()

        if not stored_file:
            continue


        normalized = (
            stored_file.replace(
                "\\",
                "/"
            )
        )


        if normalized == (
            f"{order_id}/{safe_filename}"
        ):

            allowed = True

            break


    if not allowed:

        return "File not found", 404


    order_folder = os.path.join(
        UPLOAD_FOLDER,
        order_id
    )


    file_path = os.path.join(
        order_folder,
        safe_filename
    )


    if not os.path.isfile(
        file_path
    ):

        return "File not found on server", 404


    return send_from_directory(
        order_folder,
        safe_filename,
        as_attachment=False
    )


# =========================================================
# ADMIN - DELETE ORDER
# =========================================================

@app.route(
    "/admin/delete-order",
    methods=["POST"]
)
def delete_order():

    if not session.get(
        "admin_logged_in"
    ):

        return "Unauthorized", 401


    order_id = request.form.get(
        "order_id",
        ""
    ).strip()


    if not order_id:

        flash(
            "Invalid Order ID.",
            "danger"
        )

        return redirect(
            url_for("admin")
        )


    conn = get_db()


    order = conn.execute(
        """
        SELECT *
        FROM orders
        WHERE order_id=?
        """,
        (order_id,)
    ).fetchone()


    if not order:

        conn.close()

        flash(
            "Order not found.",
            "danger"
        )

        return redirect(
            url_for("admin")
        )


    # DELETE DATABASE RECORD

    conn.execute(
        """
        DELETE FROM orders
        WHERE order_id=?
        """,
        (order_id,)
    )


    conn.commit()

    conn.close()


    # DELETE ORDER FOLDER

    order_folder = os.path.join(
        UPLOAD_FOLDER,
        order_id
    )


    if os.path.isdir(
        order_folder
    ):

        import shutil

        try:

            shutil.rmtree(
                order_folder
            )

        except Exception as e:

            print(
                f"Could not delete folder {order_folder}:",
                e
            )


    flash(
        f"Order {order_id} deleted successfully.",
        "success"
    )


    return redirect(
        url_for("admin")
    )


# =========================================================
# ADMIN - DELETE CONTACT
# =========================================================

@app.route(
    "/admin/delete-contact",
    methods=["POST"]
)
def delete_contact():

    if not session.get(
        "admin_logged_in"
    ):

        return "Unauthorized", 401


    try:

        contact_id = int(
            request.form.get(
                "contact_id",
                "0"
            )
        )

    except ValueError:

        contact_id = 0


    if contact_id <= 0:

        flash(
            "Invalid contact ID.",
            "danger"
        )

        return redirect(
            url_for("admin")
        )


    conn = get_db()


    contact = conn.execute(
        """
        SELECT *
        FROM contacts
        WHERE id=?
        """,
        (contact_id,)
    ).fetchone()


    if not contact:

        conn.close()

        flash(
            "Contact not found.",
            "danger"
        )

        return redirect(
            url_for("admin")
        )


    conn.execute(
        """
        DELETE FROM contacts
        WHERE id=?
        """,
        (contact_id,)
    )


    conn.commit()

    conn.close()


    flash(
        "Contact deleted successfully.",
        "success"
    )


    return redirect(
        url_for("admin")
    )


# =========================
# ADMIN LOGOUT
# =========================

@app.route(
    "/admin/logout"
)
def admin_logout():

    session.clear()

    return redirect(
        url_for("admin")
    )


# =========================
# ADMIN UPDATE ORDER
# =========================

@app.route(
    "/admin/update-order",
    methods=["POST"]
)
def update_order():

    if not session.get(
        "admin_logged_in"
    ):

        return "Unauthorized", 401


    oid = request.form.get(
        "order_id",
        ""
    ).strip()


    status = request.form.get(
        "status",
        ""
    ).strip()


    deadline = request.form.get(
        "deadline",
        ""
    ).strip()


    payment_status = request.form.get(
        "payment_status",
        ""
    ).strip()


    allowed_statuses = {
        "Pending",
        "Approved",
        "In Progress",
        "Completed",
        "Rejected",
        "Cancelled",
    }


    allowed_payment_statuses = {
        "Pending Verification",
        "Verified",
        "Rejected",
    }


    if status not in allowed_statuses:

        return "Invalid order status", 400


    if (
        payment_status
        not in allowed_payment_statuses
    ):

        return "Invalid payment status", 400


    conn = get_db()


    order = conn.execute(
        """
        SELECT *
        FROM orders
        WHERE order_id=?
        """,
        (oid,)
    ).fetchone()


    if not order:

        conn.close()

        return "Order not found", 404


    conn.execute(
        """
        UPDATE orders
        SET status=?,
            deadline=?,
            payment_status=?
        WHERE order_id=?
        """,
        (
            status,
            deadline or None,
            payment_status,
            oid
        )
    )


    conn.commit()

    conn.close()


    # =========================
    # CUSTOMER NOTIFICATION
    # =========================

    customer_email_result = send_email(
        f"Apna Typist Order Update - {oid}",
        f"""
Hello {order['name']},

Your Apna Typist order has been updated.

Order ID: {oid}
Work: {order['work_type']}
Quantity: {order['quantity']}
Total: ₹{order['total_amount']}

Payment Status: {payment_status}
Order Status: {status}
Deadline: {deadline or 'Not set'}

Thank you,
Apna Typist
""",
        receiver=order["email"]
    )


    print(
        "CUSTOMER ORDER UPDATE EMAIL RESULT:",
        customer_email_result
    )


    return redirect(
        url_for("admin")
    )


# =========================
# CONTACT FORM
# =========================

@app.route(
    "/contact",
    methods=["GET", "POST"]
)
def contact():

    if request.method == "POST":

        name = request.form.get(
            "name",
            ""
        ).strip()


        email = request.form.get(
            "email",
            ""
        ).strip()


        phone = request.form.get(
            "phone",
            ""
        ).strip()


        message = request.form.get(
            "message",
            ""
        ).strip()


        # =========================
        # VALIDATION
        # =========================

        if (
            not name
            or not email
            or not message
        ):

            flash(
                "Please fill the required fields.",
                "danger"
            )

            return redirect(
                url_for("home")
                + "#contact-section"
            )


        # =========================
        # SAVE CONTACT
        # =========================

        conn = get_db()


        conn.execute(
            """
            INSERT INTO contacts
            (
                name,
                email,
                phone,
                message
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                name,
                email,
                phone,
                message
            ),
        )


        conn.commit()

        conn.close()


        # ==================================================
        # ADMIN EMAIL
        # ==================================================

        admin_email = os.environ.get(
            "ADMIN_EMAIL"
        )


        admin_email_result = send_email(
            "New Apna Typist Contact Form Entry",
            f"""
A new contact form message has been received.

Name: {name}
Email: {email}
Phone: {phone}

Message:
{message}
""",
            receiver=admin_email
        )


        print(
            "ADMIN CONTACT EMAIL RESULT:",
            admin_email_result
        )


       
        # ==================================================
        # CUSTOMER CONFIRMATION EMAIL
        # ==================================================

        customer_email_result = send_email(
            "Apna Typist - Message Received",
            f"""
            <h2>Thank You, {name}!</h2>
            <p>We have received your message successfully.</p>
            <p><strong>Your Message:</strong></p>
            <p>{message}</p>
            <p>Our team will review your request and contact you soon.</p>
            <hr>
            <p>
            Regards,<br>
            <strong>Apna Typist</strong><br>
            admin@apnatypist.in<br>
            <a href="https://apnatypist.in">https://apnatypist.in</a>
            </p>
            """,
            receiver=email
        )

        print(
            "CUSTOMER CONTACT EMAIL RESULT:",
            customer_email_result
        )

     

        # =========================
        # SUCCESS MESSAGE
        # =========================

        flash(
            "Your message has been submitted successfully.",
            "success"
        )


        return redirect(
            url_for("home")
            + "#contact-section"
        )


    return render_template(
        "contact.html"
    )


# =========================
# ERROR HANDLER - 413
# =========================

@app.errorhandler(413)
def file_too_large(error):

    flash(
        "Uploaded file(s) are too large. Maximum allowed size is 20 MB.",
        "danger"
    )

    return redirect(
        url_for("payment")
    )


# =========================
# ERROR HANDLER - 404
# =========================

@app.errorhandler(404)
def page_not_found(error):

    return render_template(
        "404.html"
    ), 404


# =========================
# START APP
# =========================

if __name__ == "__main__":

    debug_mode = (
        os.environ.get(
            "FLASK_DEBUG",
            "False"
        ).lower()
        == "true"
    )

    app.run(
        debug=debug_mode
    )