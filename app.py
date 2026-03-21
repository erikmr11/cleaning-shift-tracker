import streamlit as st
from supabase import create_client, Client
from datetime import datetime, timezone, timedelta
import os
from dotenv import load_dotenv
import pytz
import pandas as pd

# Toronto timezone
toronto_tz = pytz.timezone("America/Toronto")

load_dotenv()
supabase: Client = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_ANON_KEY")
)

st.set_page_config(page_title="Cleaning Shift Tracker", layout="centered")

st.title("🧹 Cleaning Shift Tracker")

# Initialize session state
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
    st.success(f"Welcome, {st.session_state.worker}!")

    # Get worker role
    worker_data = supabase.table("workers").select("role").eq("id", st.session_state.worker_id).execute().data
    role = worker_data[0]["role"] if worker_data else "worker"

    # Manager / Accountant Dashboard (payroll + CSV)
    if role in ["manager", "accountant"]:
        st.subheader("Payroll Overview (last 15 days)")
        fifteen_days_ago = (datetime.now(timezone.utc) - timedelta(days=15)).isoformat()
        all_shifts = supabase.table("shifts") \
            .select("worker_name, start_time, end_time, total_hours, building") \
            .gte("start_time", fifteen_days_ago) \
            .execute().data

        if all_shifts:
            df = pd.DataFrame(all_shifts)
            df['start_time'] = pd.to_datetime(df['start_time']).dt.tz_convert('America/Toronto')
            df['end_time'] = pd.to_datetime(df['end_time']).dt.tz_convert('America/Toronto')
            df['pay'] = df['total_hours'] * 18.00  # Default rate; can join with workers table later

            st.dataframe(df)

            csv = df.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="Download Full Payroll CSV (last 15 days)",
                data=csv,
                file_name="payroll_15days_all_workers.csv",
                mime="text/csv"
            )
        else:
            st.info("No shifts in the last 15 days.")

    # Clock in/out - only for regular workers (role == "worker")
    if role == "worker":
        buildings = ["Joy Condos Markham", "Bauhaus Downtown"]
        building = st.selectbox("Which building are you working at?", buildings)

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
                    
                    now_local = datetime.now(toronto_tz)
                    st.success(f"Shift started at {now_local.strftime('%Y-%m-%d %H:%M %Z')} at {building}")
                    st.rerun()
        else:
            st.subheader(f"You are CLOCKED IN at {building}")
            photo = st.camera_input("Take end-of-day photo (optional)")
            notes = st.text_area("Notes")
            
            if st.button("END SHIFT", type="secondary"):
                photo_url = None
                if photo:
                    filename = f"end/{st.session_state.worker}/{datetime.now().isoformat()}.jpg"
                    supabase.storage.from_("photos").upload(filename, photo.getvalue())
                    photo_url = supabase.storage.from_("photos").get_public_url(filename)
                
                shift = supabase.table("shifts").select("start_time").eq("id", st.session_state.shift_id).execute().data[0]
                start_str = shift["start_time"]
                
                start_utc = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                now_utc = datetime.now(timezone.utc)
                
                hours = round((now_utc - start_utc).total_seconds() / 3600, 2)
                
                supabase.table("shifts").update({
                    "end_time": now_utc.isoformat(),
                    "total_hours": hours,
                    "end_photo_url": photo_url,
                    "notes": notes
                }).eq("id", st.session_state.shift_id).execute()
                
                now_local = datetime.now(toronto_tz)
                st.success(f"Shift ended at {now_local.strftime('%Y-%m-%d %H:%M %Z')} at {building} — {hours} hours recorded!")
                st.session_state.is_clocked_in = False
                st.session_state.shift_id = None
                st.rerun()
    
    if st.button("Logout"):
        st.session_state.worker = None
        st.session_state.worker_id = None
        st.session_state.is_clocked_in = False
        st.session_state.shift_id = None
        st.rerun()