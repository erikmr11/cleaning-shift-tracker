import streamlit as st
from supabase import create_client, Client
from datetime import datetime
import os
from dotenv import load_dotenv
from datetime import datetime, timezone
import pytz

toronto_tz = pytz.timezone("America/Toronto")

st.set_page_config(page_title="Cleaning Shift Tracker", layout="centered")

st.title("🧹 Cleaning Shift Tracker - Debug Mode")

# === DEBUG: Show if secrets load correctly ===
st.subheader("Step 1: Loading secrets...")
load_dotenv()
url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_ANON_KEY")

if url and key:
    st.success("✅ Secrets loaded successfully!")
    st.write("URL starts with:", url[:30] + "...")
    st.write("Key starts with:", key[:20] + "...")
else:
    st.error("❌ Secrets not found! Check your .env file or Streamlit Secrets")
    st.stop()

# === DEBUG: Try to connect to Supabase ===
st.subheader("Step 2: Connecting to Supabase...")
try:
    supabase: Client = create_client(url, key)
    st.success("✅ Supabase client created!")
except Exception as e:
    st.error(f"❌ Failed to create client: {str(e)}")
    st.stop()

# === DEBUG: Test database query ===
st.subheader("Step 3: Testing database connection...")
try:
    test = supabase.table("workers").select("*", count="exact").execute()
    st.success(f"✅ Database connected! Found {test.count} workers.")
except Exception as e:
    st.error(f"❌ Database query failed: {str(e)}")
    st.stop()

st.success("✅ Everything looks good so far! The rest of the app should load below...")

# === FULL APP CODE - LOGIN + CLOCK IN/OUT ===
if "worker" not in st.session_state:
    st.session_state.worker = None
    st.session_state.worker_id = None
    st.session_state.is_clocked_in = False
    st.session_state.shift_id = None

if st.session_state.worker is None:
    st.subheader("Login")
    workers = supabase.table("workers").select("name").execute().data
    name = st.selectbox("Your name", [w["name"] for w in workers])
    pin = st.text_input("PIN (if set)", type="password")
    
    if st.button("Login"):
        response = supabase.table("workers").select("*").eq("name", name).execute()
        if response.data:
            worker = response.data[0]
            if not worker.get("pin") or worker["pin"] == pin:
                st.session_state.worker = name
                st.session_state.worker_id = worker["id"]
                st.rerun()
            else:
                st.error("Wrong PIN")
        else:
            st.error("Worker not found")
else:
    st.success(f"Shift started at {datetime.now(toronto_tz).strftime('%H:%M %Z')}")
    
    building = st.text_input("Building", value="The Grand Tower")
    
    if not st.session_state.is_clocked_in:
        st.subheader("Start Shift")
        photo = st.camera_input("Take arrival photo (required)")
        notes = st.text_area("Notes (optional)")
        
        if st.button("START SHIFT", type="primary"):
            if photo is None:
                st.error("Photo is required!")
            else:
                filename = f"arrival/{st.session_state.worker}/{datetime.now().isoformat()}.jpg"
                supabase.storage.from_("photos").upload(filename, photo.getvalue())
                photo_url = supabase.storage.from_("photos").get_public_url(filename)
                
                data = {
                    "worker_id": st.session_state.worker_id,
                    "worker_name": st.session_state.worker,
                    "building": building,
                    "arrival_photo_url": photo_url,
                    "notes": notes
                }
                response = supabase.table("shifts").insert(data).execute()
                st.session_state.shift_id = response.data[0]["id"]
                st.session_state.is_clocked_in = True
                st.success(f"Shift started at {datetime.now().strftime('%H:%M')}")
                st.rerun()
    else:
        st.subheader("You are CLOCKED IN")
        photo = st.camera_input("Take end-of-day photo (optional)")
        notes = st.text_area("Notes")
        
    if st.button("END SHIFT", type="secondary"):
        photo_url = None

        if photo:
                filename = f"end/{st.session_state.worker}/{datetime.now().isoformat()}.jpg"
                supabase.storage.from_("photos").upload(filename, photo.getvalue())
                photo_url = supabase.storage.from_("photos").get_public_url(filename)
    
        # Get start time from Supabase (timestamptz in UTC)
        shift = supabase.table("shifts").select("start_time").eq("id", st.session_state.shift_id).execute().data[0]
        start_utc = datetime.fromisoformat(shift["start_time"].replace("Z", "+00:00"))
    
        # Convert to Toronto time for display
        toronto_tz = pytz.timezone("America/Toronto")
        start_local = start_utc.astimezone(toronto_tz)
    
        # Current time in Toronto
        now_local = datetime.now(toronto_tz)
    
        # Calculate hours (using UTC for accuracy)
        hours = round((datetime.now(timezone.utc) - start_utc).total_seconds() / 3600, 2)
    
        # Save end_time in UTC (Supabase standard)
        now_utc = datetime.now(timezone.utc)
    
        supabase.table("shifts").update({
             "end_time": now_utc.isoformat(),
             "total_hours": hours,
             "end_photo_url": photo_url,
             "notes": notes
        }).eq("id", st.session_state.shift_id).execute()
    
        # Show times in Toronto timezone
        st.success(f"Shift ended at {now_local.strftime('%H:%M %Z')} — {hours} hours recorded!")
        st.session_state.is_clocked_in = False
        st.rerun()
    
    if st.button("Logout"):
        st.session_state.worker = None
        st.rerun()