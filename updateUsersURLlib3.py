# Import the 'urllib3' library. This is an alternative to 'requests' for making HTTP calls.
# It's more low-level, meaning we have to do more work manually.
# *** YOU MUST TRY TO INSTALL THIS: pip3 install urllib3 (This will likely fail due to your network issues) ***
import urllib3

# Import the 'msal' (Microsoft Authentication Library) library for Entra ID authentication.
# *** NOTE: 'msal' itself might still require 'requests' to be installed to work correctly! ***
import msal

# Import the 'logging' library for displaying messages during execution.
import logging

# Import the 'time' library for pausing the script (rate limiting).
import time

# Import the 'json' library. We need this to convert Python dictionaries to JSON strings
# for request bodies, and to parse JSON responses back into dictionaries.
import json

# ==================================
# ====== ENTRA CONFIGURATION ======
# ==================================
TENANT_ID = ""
CLIENT_ID = ""
CLIENT_SECRET = ""
ENTRA_GROUP_NAME = ''

AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
SCOPE = ["https://graph.microsoft.com/.default"]
GRAPH_API_ENDPOINT = "https://graph.microsoft.com/v1.0"

# ====================================
# ====== NETSKOPE CONFIGURATION ======
# ====================================
NETSKOPE_API_TOKEN = ''
NETSKOPE_TENANT = ''
NETSKOPE_GROUP_NAME = ''

NETSKOPE_HEADERS = {
  'Accept': 'application/scim+json;charset=utf-8',
  'Netskope-api-token': NETSKOPE_API_TOKEN,
  'Content-Type': 'application/scim+json;charset=utf-8'
}
NETSKOPE_API_ENDPOINT = f"https://{NETSKOPE_TENANT}.goskope.com/api/v2/scim"

# ==========================
# ====== MISCELLANEOUS ======
# ==========================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Create a PoolManager instance from urllib3. This manages connections for us.
# We will use this 'http' object for all our API calls.
# We disable warnings because making many HTTPS requests without full cert verification (which
# urllib3 sometimes flags) can be noisy; in a production/secure scenario, you'd investigate these.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
http = urllib3.PoolManager()

# =========================================
# ====== ENTRA AUTHENTICATION & FUNCTIONS ======
# =========================================
app = msal.ConfidentialClientApplication(
    CLIENT_ID,
    authority=AUTHORITY,
    client_credential=CLIENT_SECRET,
)

def get_access_token():
    """Acquires an Entra access token (still uses msal)."""
    result = app.acquire_token_silent(SCOPE, account=None)
    if not result:
        logging.info("Entra: No token in cache. Acquiring a new one...")
        result = app.acquire_token_for_client(scopes=SCOPE)
    if "access_token" in result:
        logging.info("Entra: Access token obtained.")
        return result["access_token"]
    else:
        logging.error(f"Entra: Failed to obtain access token: {result}")
        raise Exception(f"Entra: Failed to obtain access token: {result}")

# Helper function to handle urllib3 responses and errors
def handle_urllib3_response(response, function_name):
    """Checks urllib3 response status and decodes JSON data."""
    # Check if the HTTP status code indicates an error (400 or higher).
    if response.status >= 400:
        # Try to decode the error message for better logging. 'errors=ignore' prevents crashes on bad decoding.
        error_body = response.data.decode('utf-8', errors='ignore')
        logging.error(f"{function_name}: HTTP Error {response.status} - {error_body}")
        # Raise an exception to stop the script or be caught by 'try...except'.
        raise Exception(f"{function_name}: HTTP Error {response.status} - {error_body}")
    
    # If the status is okay, decode the response data from bytes to a UTF-8 string.
    decoded_data = response.data.decode('utf-8')
    # If the decoded data is empty (like in a 204 No Content response), return an empty dict.
    if not decoded_data:
        return {}
    # Parse the JSON string into a Python dictionary.
    return json.loads(decoded_data)


def get_entra_group_id(group_name, token):
    """Finds the Entra group ID by name using urllib3."""
    url = f"{GRAPH_API_ENDPOINT}/groups"
    headers = {"Authorization": f"Bearer {token}"}
    # For GET with urllib3, parameters go in 'fields'. It handles URL encoding.
    fields = {"$filter": f"displayName eq '{group_name}'", "$select": "id,displayName"}
    logging.info(f"Entra: Searching for group ID: {group_name}")

    try:
        # Make the GET request using the http object.
        response = http.request('GET', url, headers=headers, fields=fields)
        # Process the response using our helper function.
        data = handle_urllib3_response(response, "get_entra_group_id")
    except Exception as e:
        logging.error(f"Entra: Failed during get_entra_group_id request: {e}")
        raise # Re-raise the exception.

    groups = data.get("value", [])
    if not groups:
        logging.warning(f"Entra: Group '{group_name}' not found.")
        return None
    elif len(groups) > 1:
        logging.warning(f"Entra: Multiple groups found with name '{group_name}'. Using first: {groups[0]['id']}")
    group_id = groups[0]["id"]
    logging.info(f"Entra: Found group '{group_name}' with ID: {group_id}")
    return group_id

def get_entra_group_members(group_id, token):
    """Retrieves Entra group members using urllib3."""
    if not group_id: return []
    url = f"{GRAPH_API_ENDPOINT}/groups/{group_id}/members"
    headers = {"Authorization": f"Bearer {token}"}
    fields = {"$select": "displayName,userPrincipalName"}
    members_data = []
    logging.info(f"Entra: Fetching members for group ID: {group_id}")

    while url:
        try:
            # Make the GET request. Use 'fields' only on the first call.
            # On subsequent calls, 'url' will be the full nextLink, so fields should be None.
            current_fields = fields if fields else None
            response = http.request('GET', url, headers=headers, fields=current_fields)
            fields = None # Clear fields for next iteration
            data = handle_urllib3_response(response, "get_entra_group_members")
        except Exception as e:
            logging.error(f"Entra: Failed during get_entra_group_members request: {e}")
            raise

        for m in data.get("value", []):
            if m.get('@odata.type') == '#microsoft.graph.user' and m.get("displayName") and m.get("userPrincipalName"):
                members_data.append({
                    "displayName": m["displayName"],
                    "userPrincipalName": m["userPrincipalName"]
                })
        url = data.get("@odata.nextLink")

    logging.info(f"Entra: Found {len(members_data)} members.")
    return members_data

# ===============================
# ====== NETSKOPE FUNCTIONS ======
# ===============================

def get_netskope_group_id(group_name):
    """Finds the Netskope group ID by name using urllib3."""
    url = f"{NETSKOPE_API_ENDPOINT}/Groups"
    start_index = 1
    count = 100
    logging.info(f"Netskope: Searching for group ID: {group_name}")
    while True:
        fields = {'startIndex': start_index, 'count': count}
        try:
            # Send the GET request using urllib3.
            response = http.request('GET', url, headers=NETSKOPE_HEADERS, fields=fields)
            data = handle_urllib3_response(response, "get_netskope_group_id")
            
            groups = data.get("Resources", [])
            if not groups:
                logging.warning(f"Netskope: Group '{group_name}' not found after checking {start_index-1} groups.")
                return None
            for group in groups:
                if group.get("displayName") == group_name:
                    group_id = group["id"]
                    logging.info(f"Netskope: Found group '{group_name}' with ID: {group_id}")
                    return group_id
            if data.get("totalResults", 0) < start_index + count or len(groups) < count:
                 logging.warning(f"Netskope: Group '{group_name}' not found.")
                 return None
            start_index += count
            time.sleep(1)
        except Exception as e:
            logging.error(f"Netskope: Error fetching groups: {e}")
            raise

def get_netskope_group_members(group_id):
    """Retrieves Netskope group member display names using urllib3."""
    if not group_id: return []
    # Note: '?attributes=members' is part of the URL, not 'fields', for this specific call.
    url = f"{NETSKOPE_API_ENDPOINT}/Groups/{group_id}?attributes=members"
    logging.info(f"Netskope: Fetching members for group ID: {group_id}")
    try:
        # Send GET request. No 'fields' needed here.
        response = http.request('GET', url, headers=NETSKOPE_HEADERS)
        data = handle_urllib3_response(response, "get_netskope_group_members")
        
        members = data.get("members", [])
        member_names = [m['display'] for m in members if 'display' in m]
        logging.info(f"Netskope: Found {len(member_names)} members.")
        return member_names
    except Exception as e:
        logging.error(f"Netskope: Error fetching group members: {e}")
        # If the error is due to KeyError, it means 'members' wasn't found.
        if isinstance(e, KeyError):
            logging.warning(f"Netskope: 'members' key not found in response for group {group_id}. Assuming no members.")
            return []
        raise # Re-raise other errors.

def get_netskope_user_id(username):
    """Finds a Netskope user's SCIM ID by their userName using urllib3."""
    url = f"{NETSKOPE_API_ENDPOINT}/Users"
    start_index = 1
    count = 100
    filter_query = f'userName eq "{username}"'
    logging.info(f"Netskope: Searching for User ID with userName: {username}")
    while True:
        fields = {'filter': filter_query, 'startIndex': start_index, 'count': count}
        try:
            # Send GET request with filter fields.
            response = http.request('GET', url, headers=NETSKOPE_HEADERS, fields=fields)
            data = handle_urllib3_response(response, "get_netskope_user_id")

            users = data.get("Resources", [])
            if not users:
                logging.warning(f"Netskope: User '{username}' not found.")
                return None
            for user in users:
                if user.get("userName", "").lower() == username.lower():
                    user_id = user["id"]
                    logging.info(f"Netskope: Found user '{username}' with ID: {user_id}")
                    return user_id
            if data.get("totalResults", 0) < start_index + count or len(users) < count:
                 logging.warning(f"Netskope: User '{username}' not found (end of search).")
                 return None
            start_index += count
            time.sleep(1)
        except Exception as e:
            logging.error(f"Netskope: Error fetching user '{username}': {e}")
            return None # Return None on error.

def update_netskope_group(group_id, user_ids_to_add):
    """Updates the Netskope group by adding user IDs via PATCH using urllib3."""
    if not group_id or not user_ids_to_add:
        logging.warning("Netskope: Update skipped - No Group ID or no users to add.")
        return

    url = f"{NETSKOPE_API_ENDPOINT}/Groups/{group_id}"
    logging.info(f"Netskope: Preparing to add {len(user_ids_to_add)} users to group {group_id}.")
    members_payload = [{"value": user_id} for user_id in user_ids_to_add]
    patch_payload = {
        "Operations": [{"op": "add", "path": "members", "value": members_payload}],
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"]
    }

    # Convert the Python dictionary to a JSON string, then encode it into bytes (UTF-8).
    # This is required for the 'body' parameter in urllib3.
    encoded_body = json.dumps(patch_payload).encode('utf-8')

    logging.info(f"Netskope: Sending PATCH request with payload: {json.dumps(patch_payload, indent=2)}")

    try:
        # Send the PATCH request. Use 'PATCH' method and pass the encoded data as 'body'.
        # We use NETSKOPE_HEADERS which already includes 'Content-Type'.
        response = http.request('PATCH', url, headers=NETSKOPE_HEADERS, body=encoded_body)

        # Check the response status. We don't need the full JSON back, just success/fail.
        # A status code < 400 (like 200 OK or 204 No Content) means success.
        if response.status < 400:
            logging.info(f"Netskope: Successfully sent update request for group {group_id}. Status Code: {response.status}")
            print(f"\nSUCCESS: Sent request to add {len(user_ids_to_add)} users to Netskope group '{NETSKOPE_GROUP_NAME}'.")
        else:
            # If status is 400 or above, it's an error. Try to decode and log.
            error_body = response.data.decode('utf-8', errors='ignore')
            logging.error(f"Netskope: FAILED to update group {group_id}. Status {response.status} - {error_body}")
            print(f"ERROR: Failed to update Netskope group. Status {response.status} - {error_body}")

    except Exception as e:
        # Catch any other exceptions during the request.
        logging.error(f"Netskope: FAILED to update group {group_id} due to an exception: {e}")
        print(f"ERROR: Failed to update Netskope group. Exception: {e}")


# ==========================
# ====== MAIN SCRIPT ======
# ==========================
def main():
    """Fetches users from both systems, finds the difference, and updates Netskope."""
    try:
        logging.info("--- Starting Entra User Fetch ---")
        entra_token = get_access_token()
        entra_group_id = get_entra_group_id(ENTRA_GROUP_NAME, entra_token)
        entra_users_list = get_entra_group_members(entra_group_id, entra_token)
        entra_users_map = {user['displayName']: user['userPrincipalName'] for user in entra_users_list}
        entra_display_names = set(entra_users_map.keys())
        logging.info("--- Finished Entra User Fetch ---")

        logging.info("--- Starting Netskope User Fetch ---")
        netskope_group_id = get_netskope_group_id(NETSKOPE_GROUP_NAME)
        netskope_users_list = get_netskope_group_members(netskope_group_id)
        netskope_set = set(netskope_users_list)
        logging.info("--- Finished Netskope User Fetch ---")

        logging.info("--- Comparing User Lists ---")
        missing_display_names = entra_display_names - netskope_set

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
            return
        print("=======================================================\n")

        logging.info("--- Finding Netskope IDs for Missing Users ---")
        netskope_ids_to_add = []
        for name in missing_display_names:
            upn_to_find = entra_users_map[name]
            netskope_id = get_netskope_user_id(upn_to_find)
            if netskope_id:
                netskope_ids_to_add.append(netskope_id)
            else:
                print(f"WARNING: User '{name}' ({upn_to_find}) exists in Entra group but was NOT found in Netskope tenant. Cannot add to group.")
                logging.warning(f"User '{name}' ({upn_to_find}) not found in Netskope; cannot add to group.")

        if netskope_ids_to_add:
            if netskope_group_id:
                print(f"\nAttempting to add {len(netskope_ids_to_add)} users to Netskope group...")
                update_netskope_group(netskope_group_id, netskope_ids_to_add)
            else:
                print(f"ERROR: Cannot update Netskope because the group '{NETSKOPE_GROUP_NAME}' was not found.")
                logging.error(f"Cannot update Netskope; group '{NETSKOPE_GROUP_NAME}' not found.")
        else:
            print("\nNo users to add to Netskope group (either none missing, or missing users don't exist in Netskope).")

    except Exception as e:
        logging.error(f"An error occurred in the main process: {e}", exc_info=True)
        print(f"An error occurred: {e}")

# This standard Python 'if' statement checks if the script is being run directly.
if __name__ == "__main__":
    # If it is, it calls the 'main()' function to start everything.
    main()
