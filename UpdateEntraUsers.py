# Import the 'requests' library. This library allows us to send HTTP requests (like accessing web pages or APIs)
# in Python, which is essential for interacting with both Microsoft Graph and Netskope APIs.
import requests

# Import the 'msal' (Microsoft Authentication Library) library. This library simplifies the process of
# authenticating (proving our identity) with Microsoft Entra ID (formerly Azure AD) to get permission
# to access data like user and group information.
import msal

# Import the 'logging' library. This library helps us display messages during the script's execution.
# It's more flexible than just using 'print' because we can set different levels (like INFO, WARNING, ERROR)
# and control where the messages go (like to the console or a file). This is useful for understanding
# what the script is doing and for troubleshooting problems.
import logging

# Import the 'time' library. This library provides various time-related functions. We use it here
# specifically for 'time.sleep()', which pauses the script for a specified number of seconds. This can be
# important when dealing with APIs to avoid sending too many requests too quickly (rate limiting).
import time

# Import the 'json' library. This library helps work with JSON data, especially for formatting
# the body of our PATCH request nicely for logging.
import json

# ==================================
# ====== ENTRA CONFIGURATION ======
# ==================================
# This section holds the specific details needed to connect to your Microsoft Entra ID environment.
# You MUST replace the placeholder values with your actual information.

# Your Entra ID Tenant ID. A tenant is like your organization's dedicated space in Microsoft's cloud.
# Find this in your Entra ID (Azure AD) overview page.
TENANT_ID = "YOUR_TENANT_ID"  # <-- *** REPLACE WITH YOUR TENANT ID ***

# The Client ID (or Application ID) of the App Registration you created in Entra ID.
# This App Registration represents our script when it talks to Microsoft's services.
CLIENT_ID = "YOUR_CLIENT_ID"  # <-- *** REPLACE WITH YOUR CLIENT ID ***

# The Client Secret (or Application Password) for your App Registration. This is like a password for your script.
# Treat it securely and DO NOT share it publicly or commit it to public code repositories.
CLIENT_SECRET = "YOUR_CLIENT_SECRET" # <-- *** REPLACE WITH YOUR CLIENT SECRET ***

# The name of the specific group in Entra ID whose members we want to check.
ENTRA_GROUP_NAME = 'Crest Core QA' # The display name of the group in Entra

# --- Microsoft Graph API endpoints ---
# These are standard URLs used to interact with Microsoft's services.

# The authority URL is where our script goes to ask for an access token. It includes your Tenant ID
# to specify which organization we're authenticating against. The 'f' before the string means it's an
# f-string, allowing us to embed variables like {TENANT_ID} directly into the string.
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"

# The scope defines what permissions our script is requesting. "https://graph.microsoft.com/.default"
# means we want to use the permissions that were granted to our App Registration in Entra ID.
SCOPE = ["https://graph.microsoft.com/.default"]

# This is the base URL for all Microsoft Graph API calls. The 'v1.0' indicates we're using version 1.0
# of the API, which is the current stable version.
GRAPH_API_ENDPOINT = "https://graph.microsoft.com/v1.0"

# ====================================
# ====== NETSKOPE CONFIGURATION ======
# ====================================
# This section holds the specific details needed to connect to your Netskope environment.

# Your Netskope API token. This is like a password for accessing the Netskope API.
# You generate this within your Netskope tenant administration console. Keep it secret!
NETSKOPE_API_TOKEN = 'YOUR_NETSKOPE_API_TOKEN' # <-- *** REPLACE WITH YOUR NETSKOPE TOKEN ***

# Your Netskope tenant name. This is part of the URL you use to access Netskope.
NETSKOPE_TENANT = 'alliances' # Your Netskope tenant name

# The name of the specific group in Netskope that we want to compare against.
# This might be the same as the Entra group name, or it might be different depending on your setup.
NETSKOPE_GROUP_NAME = 'Netskope' # The Netskope group name (adjust if different from Entra)

# --- Netskope API setup ---

# We create a Python dictionary called 'NETSKOPE_HEADERS'. Headers provide extra information with our
# API requests. Here, we tell Netskope we accept 'SCIM+JSON' (a standard format for identity management)
# and we provide our API token for authentication. We also add 'Content-Type' for PATCH requests.
NETSKOPE_HEADERS = {
  'Accept': 'application/scim+json;charset=utf-8', # Tell Netskope what kind of response we expect.
  'Netskope-api-token': NETSKOPE_API_TOKEN,         # Provide our 'password' (API token).
  'Content-Type': 'application/scim+json;charset=utf-8' # Tell Netskope what format our request body is in.
}

# This builds the base URL for Netskope's SCIM API, using the tenant name we defined earlier.
NETSKOPE_API_ENDPOINT = f"https://{NETSKOPE_TENANT}.goskope.com/api/v2/scim"

# ==========================
# ====== MISCELLANEOUS ======
# ==========================

# Configure the 'logging' library. We set the minimum level to 'INFO', meaning it will show INFO,
# WARNING, and ERROR messages (but not DEBUG). We also set a format for how these messages will look,
# including the time, level, and the message itself.
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# =========================================
# ====== ENTRA AUTHENTICATION & FUNCTIONS ======
# =========================================
# This section contains the code for interacting with Microsoft Entra ID.

# Create an instance (a specific object) of the 'ConfidentialClientApplication'.
app = msal.ConfidentialClientApplication(
    CLIENT_ID,                    # The application's ID.
    authority=AUTHORITY,          # The URL to talk to for authentication.
    client_credential=CLIENT_SECRET, # The application's 'password'.
)

# Define a function called 'get_access_token'.
def get_access_token():
    """Acquires an Entra access token."""
    # First, try to get a token from a local cache.
    result = app.acquire_token_silent(SCOPE, account=None)
    # Check if 'acquire_token_silent' failed.
    if not result:
        # If no token was found in the cache, log an informational message.
        logging.info("Entra: No token in cache. Acquiring a new one...")
        # Ask Microsoft's authentication service for a brand new token.
        result = app.acquire_token_for_client(scopes=SCOPE)
    # Check if the 'result' dictionary contains a key named "access_token".
    if "access_token" in result:
        # If it does, log that we got it successfully.
        logging.info("Entra: Access token obtained.")
        # Return the actual access token value.
        return result["access_token"]
    else:
        # If no access token was found, log an error message.
        logging.error(f"Entra: Failed to obtain access token: {result}")
        # Stop the script and raise an 'Exception'.
        raise Exception(f"Entra: Failed to obtain access token: {result}")

# Define a function to find the unique ID of an Entra group based on its display name.
def get_entra_group_id(group_name, token):
    """Finds the Entra group ID by name."""
    # Set the URL for the Graph API 'groups' endpoint.
    url = f"{GRAPH_API_ENDPOINT}/groups"
    # Create the headers for this request.
    headers = {"Authorization": f"Bearer {token}"}
    # Create parameters for the request ($filter and $select).
    params = {"$filter": f"displayName eq '{group_name}'", "$select": "id,displayName"}
    # Log that we are starting the search.
    logging.info(f"Entra: Searching for group ID: {group_name}")
    # Send a GET request.
    response = requests.get(url, headers=headers, params=params)
    # Check if the API returned an error.
    response.raise_for_status()
    # Convert the JSON response into a Python dictionary.
    data = response.json()
    # Get the list of groups found.
    groups = data.get("value", [])
    # Check if the 'groups' list is empty.
    if not groups:
        logging.warning(f"Entra: Group '{group_name}' not found.")
        return None
    # Check if more than one group was found.
    elif len(groups) > 1:
        logging.warning(f"Entra: Multiple groups found with name '{group_name}'. Using first: {groups[0]['id']}")
    # Get the 'id' from the first group.
    group_id = groups[0]["id"]
    # Log that we found the group.
    logging.info(f"Entra: Found group '{group_name}' with ID: {group_id}")
    # Return the found group ID.
    return group_id

# Define a function to get members of a specific Entra group.
# **MODIFIED**: Now returns a list of dictionaries, each with 'displayName' and 'userPrincipalName'.
def get_entra_group_members(group_id, token):
    """Retrieves Entra group members as a list of {'displayName': '...', 'userPrincipalName': '...' dictionaries."""
    # If 'group_id' is None, return an empty list immediately.
    if not group_id: return []
    # Set the URL for the Graph API 'members' endpoint.
    url = f"{GRAPH_API_ENDPOINT}/groups/{group_id}/members"
    # Create the headers with the access token.
    headers = {"Authorization": f"Bearer {token}"}
    # Create parameters, asking for 'displayName' and 'userPrincipalName'.
    params = {"$select": "displayName,userPrincipalName"}
    # Initialize an empty list to store the member dictionaries.
    members_data = []
    # Log that we are starting to fetch members.
    logging.info(f"Entra: Fetching members for group ID: {group_id}")
    # Start a 'while' loop for pagination.
    while url:
        # Send a GET request.
        response = requests.get(url, headers=headers, params=params)
        # Set 'params' to 'None' for subsequent pages.
        params = None
        # Check for HTTP errors.
        response.raise_for_status()
        # Convert the JSON response to a Python dictionary.
        data = response.json()
        # Loop through each member ('m') in the response 'value'.
        for m in data.get("value", []):
            # We only want users, and they must have both displayName and userPrincipalName.
            # We also check the odata.type to be reasonably sure it's a user.
            if m.get('@odata.type') == '#microsoft.graph.user' and m.get("displayName") and m.get("userPrincipalName"):
                # Append a dictionary with the required info to our list.
                members_data.append({
                    "displayName": m["displayName"],
                    "userPrincipalName": m["userPrincipalName"]
                })
        # Get the URL for the next page, or None if this is the last page.
        url = data.get("@odata.nextLink")
    # Log how many members we found.
    logging.info(f"Entra: Found {len(members_data)} members.")
    # Return the list of member dictionaries.
    return members_data

# ===============================
# ====== NETSKOPE FUNCTIONS ======
# ===============================
# This section contains the code for interacting with the Netskope API.

# Define a function to find the Netskope group ID based on its name.
def get_netskope_group_id(group_name):
    """Finds the Netskope group ID by name with pagination."""
    # Set the URL for the Netskope Groups SCIM endpoint.
    url = f"{NETSKOPE_API_ENDPOINT}/Groups"
    # Set the starting index and count for pagination.
    start_index = 1
    count = 100
    # Log that we are starting the search.
    logging.info(f"Netskope: Searching for group ID: {group_name}")
    # Start the pagination loop.
    while True:
        # Create parameters for this page.
        params = {'startIndex': start_index, 'count': count}
        # Use 'try...except' for error handling.
        try:
            # Send the GET request.
            response = requests.get(url, headers=NETSKOPE_HEADERS, params=params)
            # Check for HTTP errors.
            response.raise_for_status()
            # Convert JSON response to dictionary.
            data = response.json()
            # Get the list of groups ("Resources").
            groups = data.get("Resources", [])
            # If no groups are returned, we've reached the end.
            if not groups:
                logging.warning(f"Netskope: Group '{group_name}' not found after checking {start_index-1} groups.")
                return None
            # Loop through the fetched groups.
            for group in groups:
                # If a group's displayName matches our target.
                if group.get("displayName") == group_name:
                    # Get its ID.
                    group_id = group["id"]
                    # Log that we found it.
                    logging.info(f"Netskope: Found group '{group_name}' with ID: {group_id}")
                    # Return the ID and exit the function.
                    return group_id
            # Check if we've reached the end based on totalResults or number received.
            if data.get("totalResults", 0) < start_index + count or len(groups) < count:
                 logging.warning(f"Netskope: Group '{group_name}' not found.")
                 return None
            # Prepare for the next page.
            start_index += count
            # Pause for 1 second to be polite to the API.
            time.sleep(1)
        # Catch any request errors.
        except requests.exceptions.RequestException as e:
            logging.error(f"Netskope: Error fetching groups: {e}")
            raise

# Define a function to get Netskope group member display names.
def get_netskope_group_members(group_id):
    """Retrieves Netskope group member display names."""
    # If no group ID, return empty list.
    if not group_id: return []
    # Set the URL to get group members.
    url = f"{NETSKOPE_API_ENDPOINT}/Groups/{group_id}?attributes=members"
    # Log the action.
    logging.info(f"Netskope: Fetching members for group ID: {group_id}")
    # Use 'try...except'.
    try:
        # Send GET request (Note: We use NETSKOPE_HEADERS which includes the token).
        response = requests.get(url, headers=NETSKOPE_HEADERS)
        # Check for errors.
        response.raise_for_status()
        # Convert JSON to dictionary.
        data = response.json()
        # Get the 'members' list.
        members = data.get("members", [])
        # Extract the 'display' name for each member.
        member_names = [m['display'] for m in members if 'display' in m]
        # Log the count.
        logging.info(f"Netskope: Found {len(member_names)} members.")
        # Return the list of names.
        return member_names
    # Catch request errors.
    except requests.exceptions.RequestException as e:
        logging.error(f"Netskope: Error fetching group members: {e}")
        raise
    # Catch key errors (if 'members' is missing).
    except KeyError:
        logging.warning(f"Netskope: 'members' key not found in response for group {group_id}. Assuming no members.")
        return []

# **NEW FUNCTION**: Define a function to find a Netskope user's SCIM ID by their username (UPN).
def get_netskope_user_id(username):
    """Finds a Netskope user's SCIM ID by their userName (usually Entra UPN)."""
    # Set the URL for the Netskope Users SCIM endpoint.
    url = f"{NETSKOPE_API_ENDPOINT}/Users"
    # Set the start index and count for pagination. We only expect 1, but we search pages just in case.
    start_index = 1
    count = 100 # We can fetch more users per page here if needed.
    # Define the filter to search for a user by their 'userName'.
    # Note: SCIM filter values are typically enclosed in double quotes.
    filter_query = f'userName eq "{username}"'
    # Log that we are starting the search.
    logging.info(f"Netskope: Searching for User ID with userName: {username}")
    # Start the pagination loop.
    while True:
        # Create parameters for this page, including the filter.
        params = {'filter': filter_query, 'startIndex': start_index, 'count': count}
        # Use 'try...except'.
        try:
            # Send the GET request.
            response = requests.get(url, headers=NETSKOPE_HEADERS, params=params)
            # Check for HTTP errors.
            response.raise_for_status()
            # Convert JSON to dictionary.
            data = response.json()
            # Get the list of users ("Resources").
            users = data.get("Resources", [])
            # If no users are returned, it means either the user isn't found, or we've reached the end.
            if not users:
                # Since we are filtering, if we hit an empty page, the user isn't found.
                logging.warning(f"Netskope: User '{username}' not found.")
                return None
            # Loop through the (usually single) user found.
            for user in users:
                # Double-check if the userName matches (case-insensitivity might occur).
                if user.get("userName", "").lower() == username.lower():
                    # Get the user's ID.
                    user_id = user["id"]
                    # Log that we found it.
                    logging.info(f"Netskope: Found user '{username}' with ID: {user_id}")
                    # Return the ID. Since we expect only one, we return immediately.
                    return user_id
            # If we didn't return, check if we need to go to the next page.
            if data.get("totalResults", 0) < start_index + count or len(users) < count:
                 logging.warning(f"Netskope: User '{username}' not found (end of search).")
                 return None
            # Prepare for the next page.
            start_index += count
            # Pause.
            time.sleep(1)
        # Catch request errors.
        except requests.exceptions.RequestException as e:
            logging.error(f"Netskope: Error fetching user '{username}': {e}")
            # We return None here, as we can't find the ID if there's an error.
            return None

# **NEW FUNCTION**: Define a function to update the Netskope group using the PATCH endpoint.
def update_netskope_group(group_id, user_ids_to_add):
    """Updates the Netskope group by adding a list of user IDs via PATCH."""
    # If there's no group ID or no users to add, we can't do anything.
    if not group_id or not user_ids_to_add:
        logging.warning("Netskope: Update skipped - No Group ID or no users to add.")
        return

    # Set the URL for the PATCH request, using the specific group ID.
    url = f"{NETSKOPE_API_ENDPOINT}/Groups/{group_id}"
    # Log the action, showing how many users we intend to add.
    logging.info(f"Netskope: Preparing to add {len(user_ids_to_add)} users to group {group_id}.")

    # Construct the 'value' part of the payload. It needs to be a list of dictionaries,
    # where each dictionary has a "value" key pointing to the user ID.
    # This uses a list comprehension for a concise way to build this list.
    members_payload = [{"value": user_id} for user_id in user_ids_to_add]

    # Construct the full request body (payload) according to the SCIM PATCH standard shown in the screenshot.
    patch_payload = {
        "Operations": [
            {
                "op": "add",           # We want to perform an 'add' operation.
                "path": "members",     # We want to add to the 'members' attribute.
                "value": members_payload # The list of users (with their IDs) to add.
            }
        ],
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"] # Standard SCIM schema.
    }

    # Log the payload we are about to send (using json.dumps for pretty printing).
    # Be mindful: In a highly secure environment, you might not want to log PII or IDs.
    logging.info(f"Netskope: Sending PATCH request with payload: {json.dumps(patch_payload, indent=2)}")

    # Use 'try...except'.
    try:
        # Send the PATCH request. We use 'requests.patch'.
        # 'json=patch_payload' tells 'requests' to automatically convert our Python dictionary
        # to a JSON string and set the 'Content-Type' header correctly (though we also set it
        # in NETSKOPE_HEADERS for clarity).
        response = requests.patch(url, headers=NETSKOPE_HEADERS, json=patch_payload)

        # Check for HTTP errors. If the PATCH fails (e.g., bad request, unauthorized), this will raise an error.
        response.raise_for_status()

        # If we reach here, the PATCH request was successful (returned a 2xx status code, usually 200 or 204).
        logging.info(f"Netskope: Successfully sent update request for group {group_id}. Status Code: {response.status_code}")
        print(f"\nSUCCESS: Sent request to add {len(user_ids_to_add)} users to Netskope group '{NETSKOPE_GROUP_NAME}'.")
        # You might want to check response.content here if Netskope returns details.

    # Catch request errors.
    except requests.exceptions.RequestException as e:
        # Log a detailed error message.
        logging.error(f"Netskope: FAILED to update group {group_id}: {e}")
        # Also print the error. response.text often contains useful details from the API.
        if e.response is not None:
             logging.error(f"Netskope: FAILED Response Body: {e.response.text}")
             print(f"ERROR: Failed to update Netskope group. API Response: {e.response.text}")
        else:
             print(f"ERROR: Failed to update Netskope group. Error: {e}")

# ==========================
# ====== MAIN SCRIPT ======
# ==========================
# This is the main part of our script.

# Define the 'main' function.
def main():
    """Fetches users from both systems, finds the difference, and updates Netskope."""
    # Use 'try...except' to catch any major errors.
    try:
        # --- Get Entra Users (now as dictionaries) ---
        logging.info("--- Starting Entra User Fetch ---")
        entra_token = get_access_token()
        entra_group_id = get_entra_group_id(ENTRA_GROUP_NAME, entra_token)
        # Get the list of Entra user dictionaries.
        entra_users_list = get_entra_group_members(entra_group_id, entra_token)
        # Create a dictionary mapping DisplayName to UPN for easier lookup later.
        # This assumes display names are unique enough for this purpose. If not, UPN might be better.
        entra_users_map = {user['displayName']: user['userPrincipalName'] for user in entra_users_list}
        # Create a set of just the display names for the initial comparison.
        entra_display_names = set(entra_users_map.keys())
        logging.info("--- Finished Entra User Fetch ---")

        # --- Get Netskope Users (just display names) ---
        logging.info("--- Starting Netskope User Fetch ---")
        netskope_group_id = get_netskope_group_id(NETSKOPE_GROUP_NAME)
        # Get the list of Netskope member display names.
        netskope_users_list = get_netskope_group_members(netskope_group_id)
        # Convert it to a set for efficient comparison.
        netskope_set = set(netskope_users_list)
        logging.info("--- Finished Netskope User Fetch ---")

        # --- Compare Users & Identify Missing ---
        logging.info("--- Comparing User Lists ---")
        # Find display names that are in Entra but not in Netskope group.
        missing_display_names = entra_display_names - netskope_set

        # --- Print Missing Users ---
        print("\n=======================================================")
        print(f"Users in Entra Group '{ENTRA_GROUP_NAME}' but NOT in Netskope Group '{NETSKOPE_GROUP_NAME}':")
        print("=======================================================")
        if missing_display_names:
            for name in sorted(list(missing_display_names)):
                print(f"- {name}")
            print(f"\nTotal users to potentially add to Netskope: {len(missing_display_names)}")
        else:
            print("All users in the Entra group appear to be present in the Netskope group.")
            print("=======================================================\n")
            # If no one is missing, we can just exit.
            return
        print("=======================================================\n")


        # --- Find Netskope IDs for Missing Users ---
        logging.info("--- Finding Netskope IDs for Missing Users ---")
        # Initialize an empty list to store the Netskope SCIM IDs we find.
        netskope_ids_to_add = []
        # Loop through each 'name' we identified as missing.
        for name in missing_display_names:
            # Look up the UPN for this display name from our Entra map.
            upn_to_find = entra_users_map[name]
            # Call our function to search for this user's ID in Netskope using their UPN.
            netskope_id = get_netskope_user_id(upn_to_find)
            # Check if we found an ID.
            if netskope_id:
                # If yes, add it to our list.
                netskope_ids_to_add.append(netskope_id)
            else:
                # If not, print a warning. This user needs to exist in Netskope before they can be added.
                print(f"WARNING: User '{name}' ({upn_to_find}) exists in Entra group but was NOT found in Netskope tenant. Cannot add to group.")
                logging.warning(f"User '{name}' ({upn_to_find}) not found in Netskope; cannot add to group.")

        # --- Update Netskope Group (if needed) ---
        # Check if we actually found any Netskope IDs to add.
        if netskope_ids_to_add:
            # If we have IDs and we found the Netskope group ID earlier...
            if netskope_group_id:
                # *** ADD A CONFIRMATION STEP (OPTIONAL BUT RECOMMENDED) ***
                # Ask the user if they really want to proceed with the update.
                # response = input(f"Found {len(netskope_ids_to_add)} users to add. Proceed with update? (yes/no): ").lower()
                # if response == 'yes':
                #    # If they say yes, call the update function.
                #    update_netskope_group(netskope_group_id, netskope_ids_to_add)
                # else:
                #    # If they say no, print a message and stop.
                #    print("Update cancelled by user.")

                # For now, we proceed directly without asking. Uncomment the block above for safety.
                print(f"\nAttempting to add {len(netskope_ids_to_add)} users to Netskope group...")
                update_netskope_group(netskope_group_id, netskope_ids_to_add)

            else:
                # If we couldn't find the Netskope group ID earlier, we can't update.
                print(f"ERROR: Cannot update Netskope because the group '{NETSKOPE_GROUP_NAME}' was not found.")
                logging.error(f"Cannot update Netskope; group '{NETSKOPE_GROUP_NAME}' not found.")
        else:
            # If we found missing users, but none of them exist in Netskope, print a message.
            print("\nNo users to add to Netskope group (either none missing, or missing users don't exist in Netskope).")

    # Catch any 'Exception' during the main process.
    except Exception as e:
        # Log the error with details.
        logging.error(f"An error occurred in the main process: {e}", exc_info=True)
        # Print a user-friendly error message.
        print(f"An error occurred: {e}")

# This standard Python 'if' statement checks if the script is being run directly.
if __name__ == "__main__":
    # If it is, it calls the 'main()' function to start everything.
    main()
