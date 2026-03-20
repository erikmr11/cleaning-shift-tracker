import reflex as rxpip
from supabase import create_client, Client
from datetime import datetime
import os
from dotenv import load_dotenv

# === STEP 1: Load secret keys from .env file ===
load_dotenv()
supabase: Client = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_ANON_KEY")
)

# === STEP 2: This is the "brain" of the app ===
class ShiftState(rx.State):
    """All the logic lives here — Reflex calls this automatically."""

    # Who is logged in right now
    current_worker: str = ""
    current_worker_id: str = ""
    selected_pin: str = ""
    building: str = "The Grand Tower"   # Change this later for different jobs

    # Form fields
    notes: str = ""

    # Feedback messages
    message: str = ""
    is_clocked_in: bool = False
    current_shift_id: str = ""

    def login(self):
        """Worker picks their name + PIN → we check in the database."""
        if not self.current_worker:
            self.message = "Please select your name."
            return

        response = supabase.table("workers").select("*").eq("name", self.current_worker).execute()
        if not response.data:
            self.message = "Worker not found."
            return

        worker = response.data[0]
        if worker.get("pin") and worker["pin"] != self.selected_pin:
            self.message = "Wrong PIN."
            return

        # Login success
        self.current_worker_id = worker["id"]
        self.message = f"Welcome, {self.current_worker}!"
        self.check_if_clocked_in()

    def check_if_clocked_in(self):
        """Checks if this worker already has an open shift today."""
        today = datetime.now().replace(hour=0, minute=0, second=0).isoformat()
        response = supabase.table("shifts").select("*") \
            .eq("worker_id", self.current_worker_id) \
            .gte("start_time", today) \
            .is_("end_time", None).execute()

        if response.data:
            self.is_clocked_in = True
            self.current_shift_id = response.data[0]["id"]
        else:
            self.is_clocked_in = False

    async def start_shift(self, files: list[rx.UploadFile]):
        """Clock IN: must take a photo → saves time + photo automatically."""
        if not files:
            self.message = "You MUST take an arrival photo."
            return

        file = files[0]
        filename = f"arrival/{self.current_worker}/{datetime.now().isoformat()}.jpg"

        # Upload photo to the "photos" bucket just created
        supabase.storage.from_("photos").upload(filename, await file.read())
        photo_url = supabase.storage.from_("photos").get_public_url(filename)

        # Save the shift start
        data = {
            "worker_id": self.current_worker_id,
            "worker_name": self.current_worker,
            "building": self.building,
            "arrival_photo_url": photo_url,
            "notes": self.notes
        }
        response = supabase.table("shifts").insert(data).execute()

        self.current_shift_id = response.data[0]["id"]
        self.is_clocked_in = True
        self.message = f"✅ Shift STARTED at {datetime.now().strftime('%H:%M')}"

    async def end_shift(self, files: list[rx.UploadFile] = None):
        """Clock OUT: optional photo + calculates exact hours."""
        if not self.is_clocked_in:
            return

        photo_url = None
        if files and files[0]:
            filename = f"end/{self.current_worker}/{datetime.now().isoformat()}.jpg"
            supabase.storage.from_("photos").upload(filename, await files[0].read())
            photo_url = supabase.storage.from_("photos").get_public_url(filename)

        # Calculate hours using real server time
        shift = supabase.table("shifts").select("start_time").eq("id", self.current_shift_id).execute().data[0]
        start = datetime.fromisoformat(shift["start_time"].replace("Z", "+00:00"))
        hours = round((datetime.now() - start).total_seconds() / 3600, 2)

        # Update the shift
        supabase.table("shifts").update({
            "end_time": datetime.now().isoformat(),
            "total_hours": hours,
            "end_photo_url": photo_url,
            "notes": self.notes
        }).eq("id", self.current_shift_id).execute()

        self.is_clocked_in = False
        self.message = f"✅ Shift ENDED — {hours} hours recorded for payroll!"

    def logout(self):
        self.current_worker = ""
        self.current_worker_id = ""
        self.selected_pin = ""
        self.message = ""
        self.is_clocked_in = False

# === PAGES (what the worker sees) ===

def login_page():
    return rx.center(
        rx.vstack(
            rx.heading("Cleaning Shift Tracker", size="9"),
            rx.text("Select your name:"),
            rx.select(
                [w["name"] for w in supabase.table("workers").select("name").execute().data],
                on_change=ShiftState.set_current_worker,
                placeholder="Your name",
            ),
            rx.input(placeholder="PIN (if set)", type="password", value=ShiftState.selected_pin, on_change=ShiftState.set_selected_pin),
            rx.button("Login", on_click=ShiftState.login, size="lg", color_scheme="blue"),
            rx.text(ShiftState.message, color="green"),
            spacing="5",
            padding="4em",
        )
    )

def worker_dashboard():
    return rx.center(
        rx.vstack(
            rx.heading(f"Hi {ShiftState.current_worker}!", size="8"),
            rx.text(f"Site: {ShiftState.building}"),

            rx.cond(
                ShiftState.is_clocked_in,
                # === CLOCKED IN VIEW ===
                rx.vstack(
                    rx.heading("You are CLOCKED IN", color="green", size="7"),
                    rx.upload(rx.button("Take end-of-day photo (optional)"), accept="image/*", multiple=False),
                    rx.input(placeholder="Notes", value=ShiftState.notes, on_change=ShiftState.set_notes),
                    rx.button("END SHIFT", on_click=ShiftState.end_shift(rx.upload_files()), size="lg", color_scheme="red"),
                ),
                # === CLOCKED OUT VIEW ===
                rx.vstack(
                    rx.heading("Ready to start?", color="blue", size="7"),
                    rx.upload(rx.button("Take arrival photo (REQUIRED)"), accept="image/*", multiple=False),
                    rx.input(placeholder="Notes", value=ShiftState.notes, on_change=ShiftState.set_notes),
                    rx.button("START SHIFT", on_click=ShiftState.start_shift(rx.upload_files()), size="lg", color_scheme="green"),
                )
            ),
            rx.button("Logout", on_click=ShiftState.logout),
            rx.text(ShiftState.message),
            spacing="6",
            padding="4em",
        )
    )

# === ADMIN PAGE (to see payroll) ===
@rx.page(route="/admin")
def admin_page():
    shifts = supabase.table("shifts").select("*").order("start_time", desc=True).limit(50).execute().data
    return rx.center(
        rx.vstack(
            rx.heading("Payroll Timesheet — Last 50 shifts"),
            rx.data_table(data=shifts, pagination=True, search=True),
            spacing="4",
            padding="2em",
        )
    )

# === MAIN APP ===
@rx.page(route="/")
def index():
    return rx.cond(
        ShiftState.current_worker == "",
        login_page(),
        worker_dashboard()
    )

app = rx.App()