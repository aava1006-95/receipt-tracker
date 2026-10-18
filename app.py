import os
import uuid
from io import BytesIO

import streamlit as st
from dotenv import load_dotenv
from supabase import create_client
from PIL import Image
from pillow_heif import register_heif_opener

def login_with_user_id(user_id, password):
    normalized_user_id = user_id.strip().upper()

    if not normalized_user_id or not password:
        return False, "Enter both your User ID and password."

    try:
        # Look up the internal email using the private server-side client.
        result = (
            lookup_client
            .table("profiles")
            .select("auth_email")
            .eq("user_id", normalized_user_id)
            .limit(1)
            .execute()
        )

        if not result.data or not result.data[0].get("auth_email"):
            return False, "Invalid User ID or password."

        auth_email = result.data[0]["auth_email"]

        # Supabase Auth still verifies the actual password.
        auth_result = supabase.auth.sign_in_with_password({
            "email": auth_email,
            "password": password,
        })

        if not auth_result.session or not auth_result.user:
            return False, "Invalid User ID or password."

        # Save the authenticated session for your existing app.
        st.session_state["access_token"] = (
            auth_result.session.access_token
        )
        st.session_state["refresh_token"] = (
            auth_result.session.refresh_token
        )
        st.session_state["user"] = auth_result.user

        return True, "Login successful."

    
    except Exception as e:
        import traceback

        print("LOGIN ERROR:", repr(e), flush=True)
        traceback.print_exc()

        return False, f"Login error: {str(e)}"

# =========================================================
# CONFIGURATION 
# =========================================================
load_dotenv()
def get_config(name):
    try:
        return st.secrets[name]
    except (KeyError, FileNotFoundError):
        return os.getenv(name)
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

# Regular client: use for normal app operations and employee authentication.
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Separate privileged client: use ONLY to look up a User ID.
if not SUPABASE_SERVICE_ROLE_KEY:
    st.error("Missing SUPABASE_SERVICE_ROLE_KEY in your environment.")
    st.stop()

lookup_client = create_client(
    SUPABASE_URL,
    SUPABASE_SERVICE_ROLE_KEY
)
register_heif_opener()


def prepare_receipt_image(receipt_file):
    """Convert HEIC/HEIF to JPEG and preserve JPEG/PNG."""

    image_bytes = receipt_file.getvalue()
    filename = (getattr(receipt_file, "name", "") or "").lower()
    file_type = (getattr(receipt_file, "type", "") or "").lower()

    is_heic = (
        filename.endswith((".heic", ".heif"))
        or file_type in (
            "image/heic",
            "image/heif",
            "image/heic-sequence",
            "image/heif-sequence",
        )
    )

    if is_heic:
        with Image.open(BytesIO(image_bytes)) as image:
            image.load()
            image = image.convert("RGB")

            output = BytesIO()
            image.save(output, format="JPEG", quality=90)

            return output.getvalue(), "jpg", "image/jpeg"

    if filename.endswith(".png") or file_type == "image/png":
        # Validate the PNG before uploading.
        with Image.open(BytesIO(image_bytes)) as image:
            image.verify()

        return image_bytes, "png", "image/png"

    # JPEG, including photos captured by the camera widget.
    with Image.open(BytesIO(image_bytes)) as image:
        image.verify()

    return image_bytes, "jpg", "image/jpeg"


st.set_page_config(
    page_title="Receipt Tracker",
    page_icon="🧾",
    layout="wide",
)

st.title("🧾 Receipt Tracker")


# =========================================================
# SUPABASE CONNECTION
# =========================================================
url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_KEY")

if not url or not key:
    st.error("Supabase credentials are missing. Check your .env file.")
    st.stop()

supabase = create_client(url, key)


# =========================================================
# SESSION RESTORATION
# =========================================================
if "access_token" not in st.session_state:
    st.session_state.access_token = None

if "refresh_token" not in st.session_state:
    st.session_state.refresh_token = None

current_user = None

if st.session_state.access_token and st.session_state.refresh_token:
    try:
        supabase.auth.set_session(
            st.session_state.access_token,
            st.session_state.refresh_token,
        )
        current_user = supabase.auth.get_user()

    except Exception:
        st.session_state.access_token = None
        st.session_state.refresh_token = None
        st.rerun()


# =========================================================
# LOGGED-IN USER
# =========================================================
if current_user:
    user = current_user.user

    try:
        profile_result = (
            supabase.table("profiles")
            .select("display_name, role")
            .eq("id", user.id)
            .single()
            .execute()
        )
        profile = profile_result.data
        role = profile["role"]

    except Exception:
        st.error("Could not load your profile. Check your database permissions.")
        st.stop()

    st.success(f"Logged in as {user.email}")
    st.write(f"Role: **{role}**")


      # =====================================================
    # MANAGER DASHBOARD
    # =====================================================
    if role == "manager":
        import pandas as pd

        st.subheader("Manager Dashboard")
        st.caption("Select a job to review its expenses and receipts.")

        # -------------------------------------------------
        # 1. LOAD DATA FROM SUPABASE
        # -------------------------------------------------
        try:
            credit_cards = (
                supabase.table("credit_cards")
                .select("id, name, active")
                .execute()
            ).data or []
            purchases = (
                supabase.table("purchases")
                .select("*")
                .order("created_at", desc=True)
                .execute()
            ).data or []

            profiles = (
                supabase.table("profiles")
                .select("id, display_name")
                .execute()
            ).data or []

            # Load ALL jobs so older receipts still show
            # their job names even if a job is inactive.
            jobs = (
                supabase.table("jobs")
                .select("id, name, active")
                .execute()
            ).data or []

            categories = (
                supabase.table("categories")
                .select("id, name")
                .execute()
            ).data or []

        except Exception as e:
            st.error(f"Could not load dashboard data: {e}")
            purchases = []
            profiles = []
            jobs = []
            categories = []
            credit_cards = []
        
        # -------------------------------------------------
        # 2. CREATE LOOKUP DICTIONARIES
        # -------------------------------------------------
        employee_names = {
            p["id"]: p.get("display_name") or "Unnamed employee"
            for p in profiles
        }

        job_names = {
            j["id"]: j["name"]
            for j in jobs
        }

        category_names = {
            c["id"]: c["name"]
            for c in categories
        }
        
        credit_card_names ={
            card["id"]: card["name"]
            for card in credit_cards
        }

        # -------------------------------------------------
        # 3. PREPARE RECEIPT RECORDS
        # -------------------------------------------------
        receipts = []

        for purchase in purchases:
            receipts.append({
                "Receipt ID": purchase["id"],
                "Employee": employee_names.get(
                    purchase.get("submitted_by"),
                    "Unknown employee",
                ),
                "Job": job_names.get(
                    purchase.get("job_id"),
                    "Unknown job",
                ),
                "Category": category_names.get(
                    purchase.get("category_id"),
                    "Unknown category",
                ),
                "Credit Card" : credit_card_names.get(
                    purchase.get("credit_card_id"),
                    "Not recorded",
                ),
                "Amount ($)": float(purchase.get("cost") or 0),
                "Submitted": (
                    pd.to_datetime(purchase.get("created_at"), utc=True)
                    .tz_convert("America/New_York")
                    .strftime("%B %d, %Y at %I:%M %p")
                    if purchase.get("created_at")
                    else ""
),
                "Receipt Path": purchase.get("receipt_path") or "",
            })

        # -------------------------------------------------
        # 4. SELECT A JOB
        # -------------------------------------------------
        st.divider()
        st.subheader("Select a Job")

        job_options = sorted({
            receipt["Job"]
            for receipt in receipts
        })

        if not job_options:
            st.info("No receipts have been submitted yet.")

        else:
            selected_job = st.selectbox(
                "Choose a job to review",
                job_options,
                key="manager_selected_job",
            )

            # All records for the selected job
            job_receipts = [
                receipt
                for receipt in receipts
                if receipt["Job"] == selected_job
            ]

            # -------------------------------------------------
            # 5. JOB SPENDING SUMMARY + PIE CHART
            # -------------------------------------------------
            st.divider()
            st.subheader(f"Spending Breakdown — {selected_job}")

            total_spending = sum(
                receipt["Amount ($)"]
                for receipt in job_receipts
            )

            st.metric(
                "Total Spending",
                f"${total_spending:,.2f}",
            )

            if job_receipts:
                spending_by_category = (
                    pd.DataFrame(job_receipts)
                    .groupby("Category")["Amount ($)"]
                    .sum()
                    .sort_values(ascending=False)
                )

                if spending_by_category.sum() > 0:
                    chart_data = spending_by_category.rename(
                        "Total Spending ($)"
                    )

                    st.subheader("Expenses by Category")
                    st.vega_lite_chart(
                        pd.DataFrame({
                            "Category": chart_data.index,
                            "Amount": chart_data.values,
                        }),
                        {
                            "mark": {
                                "type": "arc",
                                "innerRadius": 55,
                                "tooltip": True,
                            },
                            "encoding": {
                                "theta": {
                                    "field": "Amount",
                                    "type": "quantitative",
                                },
                                "color": {
                                    "field": "Category",
                                    "type": "nominal",
                                    "legend": {"title": "Category"},
                                },
                                "tooltip": [
                                    {
                                        "field": "Category",
                                        "type": "nominal",
                                    },
                                    {
                                        "field": "Amount",
                                        "type": "quantitative",
                                        "format": "$,.2f",
                                    },
                                ],
                            },
                            "height": 300,
                        },
                        use_container_width=True,
                    )
                else:
                    st.info(
                        "There are no spending amounts to chart "
                        "for this job yet."
                    )

            # -------------------------------------------------
            # 6. RECEIPT RECORDS + CATEGORY FILTER
            # -------------------------------------------------
            st.divider()
            st.subheader("Receipt Records")

            category_options = ["All categories"] + sorted({
                receipt["Category"]
                for receipt in job_receipts
            })

            selected_category = st.selectbox(
                "Filter records by category",
                category_options,
                key="manager_receipt_category",
            )

            if selected_category == "All categories":
                filtered_receipts = job_receipts
            else:
                filtered_receipts = [
                    receipt
                    for receipt in job_receipts
                    if receipt["Category"] == selected_category
                ]

            st.caption(
                f"{len(filtered_receipts)} matching receipt(s)"
            )

            if filtered_receipts:
                table_rows = [
                    {
                        "Employee": receipt["Employee"],
                        "Job": receipt["Job"],
                        "Category": receipt["Category"],
                        "Credit Card": receipt["Credit Card"],
                        "Amount ($)": receipt["Amount ($)"],
                        "Submitted": receipt["Submitted"],
                    }
                    for receipt in filtered_receipts
                ]

                st.dataframe(
                    pd.DataFrame(table_rows),
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "Amount ($)": st.column_config.NumberColumn(
                            "Amount ($)",
                            format="$%.2f",
                        ),
                    },
                )

            else:
                st.info(
                    "No receipts match the selected category."
                )
                

            # Filter receipts by credit card.
            card_filter_options = ["All cards"] + sorted({
                receipt["Credit Card"]
                for receipt in job_receipts
            })

            selected_card = st.selectbox(
                "Filter records by credit card",
                card_filter_options,
                key="manager_receipt_card",
            )

            if selected_card != "All cards":
                filtered_receipts = [
                    receipt
                    for receipt in filtered_receipts
                    if receipt["Credit Card"] == selected_card
                ]

            st.divider()
            st.subheader("Spending by Credit Card")

            card_spending = (
                pd.DataFrame(job_receipts)
                .groupby("Credit Card")["Amount ($)"]
                .sum()
                .sort_values(ascending=False)
            )

            if not card_spending.empty:
                st.dataframe(
                    card_spending.rename(
                        "Total Spending ($)"
                    ).reset_index(),
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "Total Spending ($)": (
                            st.column_config.NumberColumn(
                                "Total Spending ($)",
                                format="$%.2f",
                            )
                        ),
                    },
                )
            else:
                st.info("No spending records are available.")


            # -------------------------------------------------
            # 7. VIEW RECEIPT IMAGES
            # Uses the same job and category filters above.
            # -------------------------------------------------
            st.divider()
            st.subheader("View Receipt Images")

            if filtered_receipts:
                for receipt in filtered_receipts:
                    with st.expander(
                        f'{receipt["Employee"]} — '
                        f'{receipt["Category"]} — '
                        f'${receipt["Amount ($)"]:,.2f}'
                    ):
                        st.write(f'**Job:** {receipt["Job"]}')
                        st.write(
                            f'**Category:** {receipt["Category"]}'
                        )
                        st.write(
                            f'**Credit Card:** {receipt["Credit Card"]}'
                        )
                        st.write(
                            f'**Amount:** ${receipt["Amount ($)"]:,.2f}'
                        )
                        st.write(
                            f'**Submitted:** {receipt["Submitted"]}'
                        )
                        

                        receipt_path = receipt["Receipt Path"]

                        if receipt_path:
                            try:
                                signed_response = (
                                    supabase.storage
                                    .from_("receipt-images")
                                    .create_signed_url(receipt_path, 300)
                                )

                                if isinstance(signed_response, dict):
                                    signed_data = signed_response.get(
                                        "data", signed_response
                                    )
                                else:
                                    signed_data = getattr(
                                        signed_response,
                                        "data",
                                        {},
                                    ) or {}

                                if isinstance(signed_data, list):
                                    signed_data = (
                                        signed_data[0]
                                        if signed_data else {}
                                    )

                                signed_url = (
                                    signed_data.get("signedURL")
                                    or signed_data.get("signedUrl")
                                ) if isinstance(signed_data, dict) else None

                                if signed_url:
                                    st.image(
                                        signed_url,
                                        caption="Submitted receipt",
                                        use_container_width=True,
                                    )
                                else:
                                    st.warning(
                                        "Could not create a temporary "
                                        "link for this receipt."
                                    )

                            except Exception as e:
                                st.warning(
                                    f"Could not load receipt image: {e}"
                                )
                        else:
                            st.info("No receipt image is attached.")

            else:
                st.info(
                    "No receipt images match the selected filters."
                )
    
    # =====================================================
    # EMPLOYEE RECEIPT FORM
    # =====================================================
    else:
        st.subheader("Submit a Receipt")
        st.caption(
            "You can add a new job or category below. "
            "New entries will be available to other employees."
        )

        # -------------------------------------------------
        # ADD A NEW JOB INLINE
        # -------------------------------------------------
        with st.expander("➕ Add a new job"):
            with st.form("add_job_form"):
                new_job_name = st.text_input(
                    "New job name",
                    placeholder="e.g. Office Renovation",
                )
                add_job_clicked = st.form_submit_button(
                    "Save New Job"
                )

            if add_job_clicked:
                clean_job_name = new_job_name.strip()

                if not clean_job_name:
                    st.error("Please enter a job name.")
                else:
                    try:
                        existing_job = (
                            supabase.table("jobs")
                            .select("id, name")
                            .ilike("name", clean_job_name)
                            .limit(1)
                            .execute()
                        ).data or []

                        if existing_job:
                            st.warning(
                                "A job with that name already exists."
                            )
                        else:
                            supabase.table("jobs").insert({
                                "name": clean_job_name,
                                "active": True,
                            }).execute()

                            st.session_state["new_job_name"] = (
                                clean_job_name
                            )
                            st.success(
                                f"Job '{clean_job_name}' added!"
                            )
                            st.rerun()

                    except Exception as e:
                        st.error(
                            "Could not add the job. Check your "
                            f"Supabase permissions. Details: {e}"
                        )

        # -------------------------------------------------
        # ADD A NEW CATEGORY INLINE
        # -------------------------------------------------
        with st.expander("➕ Add a new category"):
            with st.form("add_category_form"):
                new_category_name = st.text_input(
                    "New category name",
                    placeholder="e.g. Equipment",
                )
                add_category_clicked = st.form_submit_button(
                    "Save New Category"
                )

            if add_category_clicked:
                clean_category_name = new_category_name.strip()

                if not clean_category_name:
                    st.error("Please enter a category name.")
                else:
                    try:
                        existing_category = (
                            supabase.table("categories")
                            .select("id, name")
                            .ilike("name", clean_category_name)
                            .limit(1)
                            .execute()
                        ).data or []

                        if existing_category:
                            st.warning(
                                "A category with that name already exists."
                            )
                        else:
                            supabase.table("categories").insert({
                                "name": clean_category_name,
                                "active": True,
                            }).execute()

                            st.session_state["new_category_name"] = (
                                clean_category_name
                            )
                            st.success(
                                f"Category '{clean_category_name}' added!"
                            )
                            st.rerun()

                    except Exception as e:
                        st.error(
                            "Could not add the category. Check your "
                            f"Supabase permissions. Details: {e}"
                        )

        # -------------------------------------------------
        # LOAD JOBS AND CATEGORIES
        # -------------------------------------------------
        try:
            jobs = (
                supabase.table("jobs")
                .select("id, name")
                .eq("active", True)
                .order("name")
                .execute()
            ).data or []

            categories = (
                supabase.table("categories")
                .select("id, name")
                .eq("active", True)
                .order("name")
                .execute()
            ).data or []
            
            active_credit_cards = (
                supabase.table("credit_cards")
                .select("id, name")
                .eq("active", True)
                .order("name")
                .execute()
            ).data or []
        except Exception as e:
            st.error(
                "Could not load jobs or categories. "
                f"Check your database permissions. Details: {e}"
            )
            st.stop()

        if not jobs:
            st.warning(
                "No active jobs are available. "
                "Use 'Add a new job' above to create one."
            )
            st.stop()

        if not categories:
            st.warning(
                "No active categories are available. "
                "Use 'Add a new category' above to create one."
            )
            st.stop()

        job_options = {
            job["name"]: job["id"]
            for job in jobs
        }
        category_options = {
            category["name"]: category["id"]
            for category in categories
        }
        credit_card_options = {
            card["name"]: card["id"]
            for card in active_credit_cards
        }
        if not credit_card_options:
            st.warning(
                "No active credit cards are available. "
                "Please ask a manager to add a card"
            )
            st.stop()
        credit_card_names = st.selectbox(
            "Credit Card Used",
            list(credit_card_options.keys()),
            key = "receipt_credit_card_select",
        )

        # Select a newly created item automatically when possible.
        saved_job = st.session_state.get("new_job_name")
        saved_category = st.session_state.get("new_category_name")

        job_names = list(job_options.keys())
        category_names = list(category_options.keys())

        default_job_index = (
            job_names.index(saved_job)
            if saved_job in job_names
            else 0
        )
        default_category_index = (
            category_names.index(saved_category)
            if saved_category in category_names
            else 0
        )

        job_name = st.selectbox(
            "Job",
            job_names,
            index=default_job_index,
            key="receipt_job_select",
        )

        category_name = st.selectbox(
            "Category",
            category_names,
            index=default_category_index,
            key="receipt_category_select",
        )

        # Clear the one-time defaults after rendering.
        st.session_state.pop("new_job_name", None)
        st.session_state.pop("new_category_name", None)

        cost = st.number_input(
            "Receipt amount ($)",
            min_value=0.01,
            value=1.00,
            step=0.01,
            format="%.2f",
            key="receipt_cost",
        )

        receipt_source = st.radio(
            "How would you like to add your receipt?",
            ["Take a photo", "Upload a photo"],
            horizontal=True,
        )

        if receipt_source == "Take a photo":
            receipt_file = st.camera_input(
                "Take a picture of your receipt"
            )
        else:
            receipt_file = st.file_uploader(
                "Choose a receipt photo",
                type=["jpg", "jpeg", "png", "heic", "heif"],
                key="receipt_upload",
            )

        receipt_bytes = None
        receipt_extension = None
        receipt_content_type = None

        if receipt_file is not None:
            try:
                (
                    receipt_bytes,
                    receipt_extension,
                    receipt_content_type,
                ) = prepare_receipt_image(receipt_file)

                st.image(
                    receipt_bytes,
                    caption="Receipt preview",
                    width=300,
                )

                original_name = (
                    getattr(receipt_file, "name", "") or ""
                ).lower()
                original_type = (
                    getattr(receipt_file, "type", "") or ""
                ).lower()

                if (
                    original_name.endswith((".heic", ".heif"))
                    or original_type in (
                        "image/heic",
                        "image/heif",
                        "image/heic-sequence",
                        "image/heif-sequence",
                    )
                ):
                    st.success("HEIC image converted to JPEG.")

            except Exception as e:
                receipt_bytes = None
                st.error(
                    "Could not process this image. Please try another "
                    f"JPEG or PNG photo. Details: {e}"
                )

        with st.form("receipt_form"):
            submitted = st.form_submit_button("Submit Receipt")

        if submitted:
            if receipt_file is None:
                st.error(
                    "Please take a photo or upload a receipt image."
                )

            elif receipt_bytes is None:
                st.error(
                    "The image could not be processed. "
                    "Please select it again."
                )

            else:
                purchase_id = str(uuid.uuid4())
                receipt_path = (
                    f"{user.id}/{purchase_id}.{receipt_extension}"
                )

                try:
                    supabase.storage.from_("receipt-images").upload(
                        receipt_path,
                        receipt_bytes,
                        file_options={
                            "content-type": receipt_content_type,
                            "upsert": "false",
                        },
                    )

                    supabase.table("purchases").insert({
                        "id": purchase_id,
                        "submitted_by": user.id,
                        "job_id": job_options[job_name],
                        "category_id": category_options[category_name],
                        "credit_card_id" : credit_card_options[credit_card_names],
                        "cost": cost,
                        "receipt_path": receipt_path,
                    }).execute()

                    st.success("Receipt submitted successfully!")
                    st.write(f"**Job:** {job_name}")
                    st.write(f"**Category:** {category_name}")
                    st.write(f"**Amount:** ${cost:.2f}")
                    st.write(f"**Credit Card:** {credit_card_names}")

                except Exception as e:
                    st.error(f"Receipt submission failed: {e}")

    # =====================================================
    # LOG OUT
    # =====================================================
    if st.button("Log out"):
        try:
            supabase.auth.sign_out()
        finally:
            st.session_state.access_token = None
            st.session_state.refresh_token = None
            st.rerun()




# =========================================================
# LOGIN
# =========================================================
else:
    st.subheader("Log in")

    with st.form("login_form"):
        user_id = st.text_input(
            "User ID",
            placeholder="e.g. EMP001"
        )
        password = st.text_input(
            "Password",
            type="password"
        )
        submitted = st.form_submit_button("Log in")

    if submitted:
        success, message = login_with_user_id(
            user_id,
            password
        )

        if success:
            st.success(message)
            st.rerun()
        else:
            st.error(message)
