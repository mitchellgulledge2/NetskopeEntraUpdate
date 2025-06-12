<#
.SYNOPSIS
    Compares members between an Entra ID group and a Netskope SCIM group.
    Identifies users in Entra but not Netskope and attempts to add them to the Netskope group.

.DESCRIPTION
    This script performs the following actions:
    1. Authenticates to Microsoft Entra ID using Client Credentials Flow.
    2. Fetches members (DisplayName and UserPrincipalName) from a specified Entra ID group.
    3. Fetches members (DisplayName) from a specified Netskope SCIM group.
    4. Compares the two lists to find users present in Entra but missing from Netskope.
    5. For missing users, it finds their SCIM ID in Netskope using their UserPrincipalName.
    6. Sends a PATCH request to the Netskope SCIM API to add the found users to the group.

.NOTES
    Author: Gemini AI (based on user's Python script)
    Requires: PowerShell 7+ recommended.
    WARNING: This script contains secrets in plain text. Use secure methods for production.
    WARNING: Ensure the Entra App Registration has GroupMember.Read.All, User.Read.All permissions.
    WARNING: Ensure the Netskope API Token has SCIM Read and PATCH permissions.
#>

# ==================================
# ====== CONFIGURATION ======
# ==================================
# --- Entra ID Configuration ---
$TenantId = ""      # <-- *** REPLACE WITH YOUR TENANT ID ***
$ClientId = ""      # <-- *** REPLACE WITH YOUR CLIENT ID ***
$ClientSecret = "" # <-- *** REPLACE WITH YOUR CLIENT SECRET (WARNING: Insecure) ***
$EntraGroupName = ''                             # The Entra group name

# --- Netskope Configuration ---
$NetskopeApiToken = '' # <-- *** REPLACE WITH YOUR NETSKOPE TOKEN (WARNING: Insecure) ***
$NetskopeTenant = ''                           # Your Netskope tenant name
$NetskopeGroupName = ''                         # The Netskope group name

# --- API Endpoints ---
$EntraAuthority = "https://login.microsoftonline.com/$TenantId/oauth2/v2.0/token"
$EntraGraphScope = "https://graph.microsoft.com/.default"
$EntraGraphApiEndpoint = "https://graph.microsoft.com/v1.0"
$NetskopeApiEndpoint = "https://{0}.goskope.com/api/v2/scim" -f $NetskopeTenant

# --- Netskope Headers ---
$NetskopeHeaders = @{
    "Accept"             = "application/scim+json;charset=utf-8"
    "Netskope-api-token" = $NetskopeApiToken
    "Content-Type"       = "application/scim+json;charset=utf-8"
}

# ==================================
# ====== HELPER FUNCTIONS ======
# ==================================

# Function to handle API responses and errors
function Handle-ApiResponse {
    param(
        [Parameter(Mandatory=$true)]
        [Microsoft.PowerShell.Commands.WebResponseObject]$Response, # Or [System.Net.Http.HttpResponseMessage] in PS Core
        [string]$FunctionName
    )
    # Note: Invoke-RestMethod throws on >=400, so we often catch instead.
    # This is a placeholder; real handling happens in Try/Catch.
    # For now, we assume if we got here, it was likely ok, but Invoke-RestMethod handles this.
    return $Response
}

# ==================================
# ====== ENTRA FUNCTIONS ======
# ==================================

function Get-EntraAccessToken {
    [CmdletBinding()]
    param()

    Write-Host "Entra: Attempting to obtain access token..."
    $Body = @{
        client_id     = $ClientId
        scope         = $EntraGraphScope
        client_secret = $ClientSecret
        grant_type    = "client_credentials"
    }

    try {
        # Send a POST request to the token endpoint.
        $TokenResponse = Invoke-RestMethod -Uri $EntraAuthority -Method Post -Body $Body -ContentType 'application/x-www-form-urlencoded'
        Write-Host "Entra: Access token obtained successfully."
        # Return only the access token string.
        return $TokenResponse.access_token
    }
    catch {
        Write-Error "Entra: FAILED to obtain access token. Error: $($_.Exception.Message)"
        Write-Error "Entra: Response Details: $($_.Exception.Response.Content)"
        # Stop the script on authentication failure.
        throw "Failed to authenticate to Entra ID."
    }
}

function Get-EntraGroupId {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)]
        [string]$GroupName,
        [Parameter(Mandatory=$true)]
        [string]$AccessToken
    )

    Write-Host "Entra: Searching for group ID: $GroupName"
    # Encode the group name to handle special characters in the URL filter.
    $EncodedGroupName = [System.Web.HttpUtility]::UrlEncode($GroupName)
    $Url = "{0}/groups?`$filter=displayName eq '{1}'&`$select=id,displayName" -f $EntraGraphApiEndpoint, $EncodedGroupName
    $Headers = @{ "Authorization" = "Bearer $AccessToken" }

    try {
        $Response = Invoke-RestMethod -Uri $Url -Headers $Headers -Method Get
        $Groups = $Response.value
        if (-not $Groups) {
            Write-Warning "Entra: Group '$GroupName' not found."
            return $null
        }
        elseif ($Groups.Count -gt 1) {
            Write-Warning "Entra: Multiple groups found with name '$GroupName'. Using first: $($Groups[0].id)"
        }
        Write-Host "Entra: Found group '$GroupName' with ID: $($Groups[0].id)"
        return $Groups[0].id
    }
    catch {
        Write-Error "Entra: FAILED to get group ID for '$GroupName'. Error: $($_.Exception.Message)"
        Write-Error "Entra: Response Details: $($_.Exception.Response.Content)"
        return $null
    }
}

function Get-EntraGroupMembers {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)]
        [string]$GroupId,
        [Parameter(Mandatory=$true)]
        [string]$AccessToken
    )

    if (-not $GroupId) { return @() } # Return an empty array if no Group ID

    $Url = "{0}/groups/{1}/members?`$select=displayName,userPrincipalName" -f $EntraGraphApiEndpoint, $GroupId
    $Headers = @{ "Authorization" = "Bearer $AccessToken" }
    $AllMembers = [System.Collections.Generic.List[PSObject]]::new() # Create a list to hold all members.

    Write-Host "Entra: Fetching members for group ID: $GroupId"
    while ($Url) {
        try {
            Write-Host "Entra: Fetching page: $Url"
            $Response = Invoke-RestMethod -Uri $Url -Headers $Headers -Method Get
            
            # Add found members to our list.
            $Response.value | ForEach-Object {
                if ($_.userPrincipalName -and $_.displayName) {
                    $AllMembers.Add([PSCustomObject]@{
                        DisplayName       = $_.displayName
                        UserPrincipalName = $_.userPrincipalName
                    })
                }
            }
            # Get the URL for the next page.
            $Url = $Response.'@odata.nextLink'
        }
        catch {
            Write-Error "Entra: FAILED to fetch members from page. Error: $($_.Exception.Message)"
            Write-Error "Entra: Response Details: $($_.Exception.Response.Content)"
            $Url = $null # Stop pagination on error.
        }
    }
    Write-Host "Entra: Found $($AllMembers.Count) members."
    return $AllMembers
}

# ==================================
# ====== NETSKOPE FUNCTIONS ======
# ==================================

function Get-NetskopeGroupId {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)]
        [string]$GroupName
    )

    $BaseUrl = "{0}/Groups" -f $NetskopeApiEndpoint
    $StartIndex = 1
    $Count = 100
    Write-Host "Netskope: Searching for group ID: $GroupName"

    while ($true) {
        $Url = "{0}?startIndex={1}&count={2}" -f $BaseUrl, $StartIndex, $Count
        try {
            $Response = Invoke-RestMethod -Uri $Url -Headers $NetskopeHeaders -Method Get
            $Groups = $Response.Resources
            if (-not $Groups) {
                Write-Warning "Netskope: Group '$GroupName' not found after checking $($StartIndex - 1) groups."
                return $null
            }

            foreach ($Group in $Groups) {
                if ($Group.displayName -eq $GroupName) {
                    Write-Host "Netskope: Found group '$GroupName' with ID: $($Group.id)"
                    return $Group.id
                }
            }

            if (($Response.totalResults -lt ($StartIndex + $Count)) -or ($Groups.Count -lt $Count)) {
                Write-Warning "Netskope: Group '$GroupName' not found."
                return $null
            }
            $StartIndex += $Count
            Start-Sleep -Seconds 1 # Be kind to the API.
        }
        catch {
            Write-Error "Netskope: FAILED to fetch groups. Error: $($_.Exception.Message)"
            Write-Error "Netskope: Response Details: $($_.Exception.Response.Content)"
            return $null
        }
    }
}

function Get-NetskopeGroupMembers {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)]
        [string]$GroupId
    )

    if (-not $GroupId) { return @() }

    $Url = "{0}/Groups/{1}?attributes=members" -f $NetskopeApiEndpoint, $GroupId
    Write-Host "Netskope: Fetching members for group ID: $GroupId"

    try {
        $Response = Invoke-RestMethod -Uri $Url -Headers $NetskopeHeaders -Method Get
        $Members = $Response.members
        if ($Members) {
            $MemberNames = $Members | ForEach-Object { $_.display }
            Write-Host "Netskope: Found $($MemberNames.Count) members."
            return $MemberNames
        } else {
            Write-Host "Netskope: No 'members' found for group $GroupId."
            return @()
        }
    }
    catch {
        Write-Error "Netskope: FAILED to fetch group members. Error: $($_.Exception.Message)"
        Write-Error "Netskope: Response Details: $($_.Exception.Response.Content)"
        return @()
    }
}

function Get-NetskopeUserId {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)]
        [string]$Username
    )

    $BaseUrl = "{0}/Users" -f $NetskopeApiEndpoint
    $StartIndex = 1
    $Count = 100
    # SCIM filter syntax usually requires quotes around the value.
    $FilterQuery = 'userName eq "{0}"' -f $Username
    Write-Host "Netskope: Searching for User ID with userName: $Username"

    while ($true) {
        # We need to URL encode the filter query itself.
        $EncodedFilter = [System.Web.HttpUtility]::UrlEncode($FilterQuery)
        $Url = "{0}?filter={1}&startIndex={2}&count={3}" -f $BaseUrl, $EncodedFilter, $StartIndex, $Count
        
        try {
            $Response = Invoke-RestMethod -Uri $Url -Headers $NetskopeHeaders -Method Get
            $Users = $Response.Resources
            if (-not $Users) {
                Write-Warning "Netskope: User '$Username' not found."
                return $null
            }

            foreach ($User in $Users) {
                if ($User.userName -eq $Username) {
                    Write-Host "Netskope: Found user '$Username' with ID: $($User.id)"
                    return $User.id
                }
            }

            if (($Response.totalResults -lt ($StartIndex + $Count)) -or ($Users.Count -lt $Count)) {
                Write-Warning "Netskope: User '$Username' not found (end of search)."
                return $null
            }
            $StartIndex += $Count
            Start-Sleep -Seconds 1
        }
        catch {
            Write-Error "Netskope: FAILED to fetch user '$Username'. Error: $($_.Exception.Message)"
            Write-Error "Netskope: Response Details: $($_.Exception.Response.Content)"
            return $null
        }
    }
}

function Update-NetskopeGroup {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)]
        [string]$GroupId,
        [Parameter(Mandatory=$true)]
        [string[]]$UserIdsToAdd
    )

    if (-not $GroupId -or -not $UserIdsToAdd) {
        Write-Warning "Netskope: Update skipped - No Group ID or no users to add."
        return
    }

    $Url = "{0}/Groups/{1}" -f $NetskopeApiEndpoint, $GroupId
    Write-Host "Netskope: Preparing to add $($UserIdsToAdd.Count) users to group $GroupId."

    # Construct the payload structure required by SCIM PATCH.
    $MembersPayload = $UserIdsToAdd | ForEach-Object { @{ "value" = $_ } }
    $PatchPayload = @{
        "Operations" = @(
            @{
                "op"    = "add"
                "path"  = "members"
                "value" = $MembersPayload
            }
        )
        "schemas"    = @("urn:ietf:params:scim:api:messages:2.0:PatchOp")
    }

    # Convert the PowerShell object to a JSON string. -Depth controls how many levels deep it converts.
    $JsonBody = $PatchPayload | ConvertTo-Json -Depth 5
    Write-Host "Netskope: Sending PATCH request..."
    # Write-Verbose "Netskope: Payload: $JsonBody" # Uncomment for debugging

    try {
        # Send the PATCH request. Body must be a JSON string.
        $Response = Invoke-RestMethod -Uri $Url -Headers $NetskopeHeaders -Method Patch -Body $JsonBody -ContentType "application/scim+json;charset=utf-8"
        # If Invoke-RestMethod doesn't throw an error, it was successful (2xx).
        Write-Host ("Netskope: Successfully sent update request for group {0}." -f $GroupId) -ForegroundColor Green
        Write-Host ("SUCCESS: Sent request to add {0} users to Netskope group '{1}'." -f $UserIdsToAdd.Count, $NetskopeGroupName) -ForegroundColor Green
    }
    catch {
        Write-Error "Netskope: FAILED to update group $GroupId. Error: $($_.Exception.Message)"
        Write-Error "Netskope: Response Details: $($_.Exception.Response.Content)"
    }
}

# ==================================
# ====== MAIN SCRIPT LOGIC ======
# ==================================

Write-Host "--- Script Starting ---"

try {
    # --- Get Entra Users ---
    Write-Host "--- Starting Entra User Fetch ---"
    $EntraToken = Get-EntraAccessToken
    $EntraGroupId = Get-EntraGroupId -GroupName $EntraGroupName -AccessToken $EntraToken
    $EntraUsersList = Get-EntraGroupMembers -GroupId $EntraGroupId -AccessToken $EntraToken
    # Create a Hashtable mapping DisplayName to UPN.
    $EntraUsersMap = @{}
    $EntraUsersList | ForEach-Object { $EntraUsersMap[$_.DisplayName] = $_.UserPrincipalName }
    # Create a HashSet for fast lookups/comparison (requires PS 5+ or can use Where-Object on arrays).
    $EntraDisplayNames = [System.Collections.Generic.HashSet[string]]::new([string[]]$EntraUsersMap.Keys, [System.StringComparer]::OrdinalIgnoreCase)
    Write-Host "--- Finished Entra User Fetch ---"

    # --- Get Netskope Users ---
    Write-Host "--- Starting Netskope User Fetch ---"
    $NetskopeGroupId = Get-NetskopeGroupId -GroupName $NetskopeGroupName
    $NetskopeUsersList = Get-NetskopeGroupMembers -GroupId $NetskopeGroupId
    $NetskopeSet = [System.Collections.Generic.HashSet[string]]::new([string[]]$NetskopeUsersList, [System.StringComparer]::OrdinalIgnoreCase)
    Write-Host "--- Finished Netskope User Fetch ---"

    # --- Compare Users & Identify Missing ---
    Write-Host "--- Comparing User Lists ---"
    # Clone the Entra set and remove items present in Netskope set.
    $MissingDisplayNames = [System.Collections.Generic.List[string]]::new()
    foreach ($entraUser in $EntraDisplayNames) {
        if (-not $NetskopeSet.Contains($entraUser)) {
            $MissingDisplayNames.Add($entraUser)
        }
    }

    # --- Print Missing Users ---
    Write-Host "`n======================================================="
    Write-Host "Users in Entra Group '$EntraGroupName' but NOT in Netskope Group '$NetskopeGroupName':"
    Write-Host "======================================================="
    if ($MissingDisplayNames.Count -gt 0) {
        $MissingDisplayNames | Sort-Object | ForEach-Object { Write-Host "- $_" }
        Write-Host "`nTotal users to potentially add to Netskope: $($MissingDisplayNames.Count)"
    } else {
        Write-Host "All users in the Entra group appear to be present in the Netskope group."
        Write-Host "======================================================="
        Write-Host "--- Script Finished ---"
        exit # Exit the script if no work to do.
    }
    Write-Host "======================================================="

    # --- Find Netskope IDs for Missing Users ---
    Write-Host "`n--- Finding Netskope IDs for Missing Users ---"
    $NetskopeIdsToAdd = [System.Collections.Generic.List[string]]::new()
    foreach ($Name in $MissingDisplayNames) {
        $UpnToFind = $EntraUsersMap[$Name]
        $NetskopeId = Get-NetskopeUserId -Username $UpnToFind
        if ($NetskopeId) {
            $NetskopeIdsToAdd.Add($NetskopeId)
        } else {
            Write-Warning "User '$Name' ($UpnToFind) exists in Entra group but was NOT found in Netskope tenant. Cannot add to group."
        }
    }

    # --- Update Netskope Group ---
    if ($NetskopeIdsToAdd.Count -gt 0) {
        if ($NetskopeGroupId) {
            Write-Host "`nAttempting to add $($NetskopeIdsToAdd.Count) users to Netskope group..."
            # Optional: Add a confirmation prompt here if desired.
            # $Confirm = Read-Host "Proceed with update? (yes/no)"
            # if ($Confirm -eq 'yes') {
                 Update-NetskopeGroup -GroupId $NetskopeGroupId -UserIdsToAdd $NetskopeIdsToAdd.ToArray()
            # } else {
            #    Write-Host "Update cancelled by user."
            # }
        } else {
            Write-Error "Cannot update Netskope because the group '$NetskopeGroupName' was not found."
        }
    } else {
        Write-Host "`nNo users to add to Netskope group (either none missing, or missing users don't exist in Netskope)."
    }
}
catch {
    Write-Error "An unexpected error occurred in the main script block: $($_.Exception.ToString())"
}

Write-Host "--- Script Finished ---"
