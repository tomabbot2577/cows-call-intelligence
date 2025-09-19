# Domain-Wide Delegation Setup for Google Drive Upload

## Service Account Information
- **Service Account Email:** call-recording-uploader@snappy-elf-472517-r8.iam.gserviceaccount.com
- **Client ID:** 104184775393017269477
- **Project ID:** snappy-elf-472517-r8

## Step-by-Step Setup Instructions

### Step 1: Access Google Workspace Admin Console
1. Go to https://admin.google.com
2. Sign in with your Google Workspace super administrator account

### Step 2: Configure Domain-Wide Delegation
1. Navigate to **Security** → **Access and data control** → **API Controls**
2. Click on **MANAGE DOMAIN-WIDE DELEGATION** at the bottom of the page
3. Click **Add new**
4. Enter the following information:
   - **Client ID:** `104184775393017269477`
   - **OAuth Scopes:**
     ```
     https://www.googleapis.com/auth/drive
     https://www.googleapis.com/auth/drive.file
     https://www.googleapis.com/auth/drive.appdata
     ```
5. Click **Authorize**

### Step 3: Choose an Impersonation Account
You need to select a Google Workspace user account that the service account will impersonate when uploading files. This should be:
- A real user account in your Google Workspace domain
- An account that has access to create folders and upload files
- Typically, this would be a dedicated service account user like `recordings@yourdomain.com`

### Step 4: Update Your Configuration
Once you've chosen the impersonation account, update your `.env` file:
```bash
# Add this new variable
GOOGLE_IMPERSONATE_EMAIL=user@yourdomain.com
```

### Step 5: Test the Setup
Run the test script to verify domain-wide delegation is working:
```bash
python test_domain_delegation.py
```

## Important Notes

1. **Propagation Time:** It may take up to 24 hours for domain-wide delegation changes to fully propagate, though it usually works within minutes.

2. **Security Best Practices:**
   - Only grant the minimum required scopes
   - Use a dedicated user account for impersonation rather than a personal account
   - Regularly audit domain-wide delegation settings

3. **Folder Permissions:** The impersonated user account will own all uploaded files and folders. Make sure this account has appropriate sharing settings configured.

## Troubleshooting

### Common Issues:

1. **"Delegation denied" error:**
   - Verify the Client ID is correct
   - Ensure the scopes match exactly
   - Wait 15-30 minutes for propagation

2. **"Invalid impersonation" error:**
   - Verify the impersonated email exists in your domain
   - Ensure the user account is active and not suspended

3. **Still getting quota errors:**
   - Verify domain-wide delegation is enabled in Admin Console
   - Check that the impersonated account has available storage

## Verification
After setup, the service account should be able to:
- Create folders in Google Drive
- Upload files to those folders
- All files will appear as owned by the impersonated user account