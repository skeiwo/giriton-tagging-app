from datetime import datetime
from dateutil.relativedelta import relativedelta
from google.oauth2.service_account import Credentials

import gspread
import json
import pandas as pd
import requests
import streamlit as st


st.set_page_config(layout="wide")
GIRITON_TOKEN = st.secrets["giriton_token"]
CURRENT_TIMESTAMP = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
BASE_URL = "https://rest.giriton.com/system/api/"
SHEET_ID = st.secrets["sheet_id"]
HEADERS = {"accept": "application/json", "giriton-token": GIRITON_TOKEN}
TODAY = datetime.today().date()
NEXT_3O_DAYS = TODAY + relativedelta(months=1)

tags_and_permissions = {
    "listing":	"6d54afd5-cdb6-4efc-ab30-2ee79954ceaa",
    "expe":	"99fc6cc8-697d-4a8c-a52f-90f7802de1b2",
    "trener":	"46412e1f-b6c5-4d27-8ad4-777c7509cf41",
    "trener_Hostivar":	"d05d9e75-5c2f-4120-9948-e56bf480c433",
    "matkovani":	"95b220e9-c423-4f67-8270-514e8cff85eb",
    "vydejna":	"affb2749-4376-43b8-96d0-35134847f618",
    "$shift.subscription.early.access:77": None,
  	"$shift.subscription.early.access:78": None,
      "$shift.subscription.early.access:54": None,
  	"Leady": "edb751aa-8b63-47eb-ad03-66dba890cb1b",
  	"zaskok": "52ba0964-c967-49c6-bb3f-8785cacf86a2",
    "quality_inspector": "462a8413-a73d-4f0f-b3f2-354c922e670c"
}

# Pulling HR data
def get_employees() -> pd.DataFrame:
    list_hr = []
    offset = 0

    while True:
        # url = BASE_URL + f"hr/usersEmployedOn?offset={offset}&limit=500"
        url = BASE_URL + f"hr/usersEmployedBetween?offset={offset}&limit=500&employedFrom={TODAY}&employedTo={NEXT_3O_DAYS}"
        try:
            response = requests.get(url, headers=HEADERS, timeout=30)
            response.raise_for_status()
            hr_data = response.json()
        except requests.exceptions.RequestException as e:
            print(f"Request failed at offset {offset}: {e}")
            break
        else:
            entries = hr_data.get("entries", [])
            for person in entries:
                list_hr.append({
                    "id": person.get("id"),
                    "giriton_number": person.get("number"),
                    "first_name": person.get("firstName"),
                    "last_name": person.get("lastName"),
                    "entry_timestamp": person.get("entryTimestamp"),
                    "job_position": person.get("jobPosition"),
                    "departments": [department.get("name") for department in person.get("departments", [])],
                    "tags": person.get("tags")
                })

            if hr_data.get("count", 0) != 500:
                print(f"Breaking at offset {offset}: count was {hr_data.get('count', 0)}")
                break
            offset += 500

    df = pd.DataFrame(list_hr)
    df = df[df["departments"].apply(lambda dept_list: any(dept in {"Kolbenova", "Hostivař"} for dept in dept_list))]
    
    return df

# Authentication using secrets
@st.cache_data
def load_credentials():
    users_dict = dict(st.secrets["users"])
    return {int(k): v for k, v in users_dict.items()}

def authenticate(username: str, password: str) -> bool:
    credentials = load_credentials()
    try:
        username_int = int(username.strip())
    except ValueError:
        return False
    
    if username_int not in credentials:
        return False
    
    stored_password = credentials[username_int].strip()
    return password.strip() == stored_password

# Gsheet logging function
def get_gspread_client():
    sa_info = st.secrets["gcp_service_account"]
    if isinstance(sa_info, str):
        sa_info = json.loads(sa_info)
    credentials = Credentials.from_service_account_info(sa_info, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    client = gspread.authorize(credentials)
    return client

# Event for gsheets logging
def log_event(username: str, action: str, details: str, sheet_id: str, worksheet_name: str = "streamlit_tag_logs"):
    client = get_gspread_client()
    sheet = client.open_by_key(sheet_id)
    worksheet = sheet.worksheet(worksheet_name)
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    worksheet.append_row([timestamp, username, action, details])

# Login page
if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False

if not st.session_state["authenticated"]:
    st.title("Please Log In")
    username_input = st.text_input("Username (Manny ID)")
    password_input = st.text_input("Password", type="password")
    
    if st.button("Login"):
        if authenticate(username_input, password_input):
            st.session_state["authenticated"] = True
            st.session_state["username"] = username_input.strip()
            st.success("Login successful!")
        else:
            st.error("Invalid username or password.")







# Load HR data
df = get_employees()
df = df[(df["job_position"] == "dělník") | (df["giriton_number"] == "X001")]

# Fulltext filter
df_fulltext = df["giriton_number"] + ": " + df["last_name"] + " " + df["first_name"]
chosen = df_fulltext[df_fulltext == "X001: Test Testovací"]
remaining = df_fulltext[df_fulltext != "X001: Test Testovací"].sort_values()
filter_result = pd.concat([chosen, remaining]).reset_index(drop=True)


if st.session_state["authenticated"]:
    st.title("Appka pro přiřazování tagů")
    st.text("Pokud jste špatně přiřadili tag, kontaktujte Annu Fučíkovou")
    
    # Sidebar: select a person by giriton id
    fulltext_choice = st.sidebar.selectbox("Select person by giriton id or name:", filter_result)
    giriton_number = fulltext_choice.split(":")[0]
    assigned_tags = [tag for tag in df[df["giriton_number"] == giriton_number]["tags"].explode().to_list() if tag in tags_and_permissions.keys()]
    unassigned_tags = [tag for tag in tags_and_permissions.keys() if tag not in df[df["giriton_number"] == giriton_number]["tags"].explode().to_list()]
    col1, col2 = st.columns([2, 1])
    
    with col2:
        # Adding permissions and tags
        add_tags = st.multiselect("Add tags:", sorted(unassigned_tags))
        permissions_to_add = [tags_and_permissions[add_tag] for add_tag in add_tags]

        # Removing permissions and tags
        remove_tags = st.multiselect("Remove tags:", sorted(assigned_tags))
        permissions_to_del = [tags_and_permissions[del_tag] for del_tag in remove_tags]

        # Button to run addition/removal of tags
        update_button = st.button("Update tags")
        
        if update_button:
            # Details rdy for logging
            details = f"Updated tags for {giriton_number}: added tags {add_tags}, removed tags: {remove_tags}"
            
            # Attempt to log to gsheets
            try:
                log_event(st.session_state["username"], "Update Tags", details, SHEET_ID)
            except Exception as e:
                error_message = f"Logging to Google Sheets failed. Aborting update. Error: {e}, contact Kilian"
                st.error(error_message)
            else:
                # Only proceed with updating tags if logging succeeded
                url = BASE_URL + "hr/usersEmployedOn"
                headers = {"accept": "application/json", "giriton-token": GIRITON_TOKEN, "Content-Type": "application/json"}
                try:
                    # Adding/Removing tags
                    user_id = df[df["giriton_number"] == giriton_number]["id"].values[0]
                    data = {"users": [{"id": user_id, "tagsToAdd": add_tags, "tagsToRemove": remove_tags}]}
                    response = requests.post(url, json=data, headers=headers)
                    response.raise_for_status()

                    # Adding permissions based on tags
                    for permission_to_add in permissions_to_add:
                        perm_add_url = BASE_URL + "permissionGroups/members"
                        perm_add_headers = {"accept": "application/json", "giriton-token": GIRITON_TOKEN, "Content-Type": "application/x-www-form-urlencoded"}
                        perm_add_data = {"permissionGroupId": permission_to_add, "personIds": user_id}
                        perm_add_response = requests.post(perm_add_url, headers=perm_add_headers, data=perm_add_data)

                    # Removing permissions based on tags
                    for permission_to_del in permissions_to_del:
                        perm_del_url = BASE_URL+"permissionGroups/members"
                        perm_del_headers = {"accept": "application/json", "giriton-token": GIRITON_TOKEN, "Content-Type": "application/x-www-form-urlencoded"}
                        perm_del_data = {"permissionGroupId": permission_to_del, "personIds": user_id}
                        perm_del_response = requests.delete(perm_del_url, headers=perm_del_headers, data=perm_del_data)
                except Exception as e:
                    error_message = f"Error updating tags for person number {giriton_number}: {e}"
                    st.error(error_message)
                else:
                    st.success("You successfully changed tags!")
                    st.success(f"Entities updated: {response.json().get('entitiesUpdated', 'N/A')}")
    
    with col1:
        df = get_employees()
        df_filtered = df[(df["job_position"] == "dělník") | (df["giriton_number"] == "X001")]
        st.dataframe(df_filtered[df_filtered["giriton_number"] == giriton_number][["giriton_number", "first_name", "last_name", "tags"]], width=1600)