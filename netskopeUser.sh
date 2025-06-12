#!/bin/bash

# #############################################################################
# Script to fetch users from a specific Netskope SCIM group via a proxy.
#
# This script requires `curl` and `jq` to be installed.
# It directly queries for the group 'pt-extweb' and routes requests
# through the specified proxy server.
# #############################################################################

# --- Configuration ---
API_TOKEN="insert your token"
TENANT="alliances"
TARGET_GROUP_NAME="pt-extweb"
PROXY_SERVER="abc.org:8080"

# --- API Headers ---
ACCEPT_HEADER="Accept: application/scim+json;charset=utf-8"
TOKEN_HEADER="Netskope-api-token: ${API_TOKEN}"

# --- Main Logic ---

echo "Searching for group: '${TARGET_GROUP_NAME}' in tenant: ${TENANT}..."
echo "Using proxy server: ${PROXY_SERVER}"

# Step 1: Find the specific group by its display name using a filter.
# The filter 'displayName eq "..."' is standard SCIM protocol.
# The URL must be properly encoded; jq's @uri filter handles this perfectly.
ENCODED_FILTER=$(jq -nr --arg name "${TARGET_GROUP_NAME}" '("displayName eq \($name|tostring)") | @uri')
GROUP_SEARCH_URL="https://${TENANT}.goskope.com/api/v2/scim/Groups?${ENCODED_FILTER}"

GROUP_INFO_JSON=$(curl -s --request GET \
  --proxy "${PROXY_SERVER}" \
  --url "${GROUP_SEARCH_URL}" \
  --header "${ACCEPT_HEADER}" \
  --header "${TOKEN_HEADER}")

# Check if any group was returned. The response contains a 'totalResults' key.
TOTAL_RESULTS=$(echo "${GROUP_INFO_JSON}" | jq '.totalResults')

if [[ "${TOTAL_RESULTS}" -eq 0 ]]; then
  echo "Error: Group '${TARGET_GROUP_NAME}' not found."
  exit 1
elif [[ "${TOTAL_RESULTS}" -gt 1 ]]; then
    echo "Warning: Found multiple groups named '${TARGET_GROUP_NAME}'. Using the first one."
fi

# Extract the ID of the first group found.
GROUP_ID=$(echo "${GROUP_INFO_JSON}" | jq -r '.Resources[0].id')

if [[ -z "${GROUP_ID}" || "${GROUP_ID}" == "null" ]]; then
    echo "Error: Could not extract a valid ID for group '${TARGET_GROUP_NAME}'."
    echo "Response: ${GROUP_INFO_JSON}"
    exit 1
fi

echo "Found group '${TARGET_GROUP_NAME}' with ID: ${GROUP_ID}. Fetching its members..."

# Step 2: Fetch the members of that specific group using its ID.
GROUP_MEMBERS_URL="https://${TENANT}.goskope.com/api/v2/scim/Groups/${GROUP_ID}?attributes=members"

MEMBERS_JSON=$(curl -s --request GET \
  --proxy "${PROXY_SERVER}" \
  --url "${GROUP_MEMBERS_URL}" \
  --header "${ACCEPT_HEADER}" \
  --header "${TOKEN_HEADER}")

# Get the number of members in the group.
MEMBER_COUNT=$(echo "${MEMBERS_JSON}" | jq '.members | length')
echo "Group '${TARGET_GROUP_NAME}' has ${MEMBER_COUNT} members."

# Step 3: Format the output into a final list.
if [[ ${MEMBER_COUNT} -gt 0 ]]; then
  # Use jq to create the final JSON array of [user, group] pairs.
  user_group_list=$(echo "${MEMBERS_JSON}" | jq --arg gn "${TARGET_GROUP_NAME}" '[.members[]? | select(. != null) | [.display, $gn]]')
else
  user_group_list="[]"
fi

# --- Final Output ---
echo "---"
echo "Script finished. Final user-group list:"
echo "${user_group_list}" | jq '.'
