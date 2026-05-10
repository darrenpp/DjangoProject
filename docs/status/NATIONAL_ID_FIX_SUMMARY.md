# Fix Summary: AttributeError 'User' object has no attribute 'national_id'

## Problem
The application was throwing an `AttributeError: 'User' object has no attribute 'national_id'` when users tried to access the student dashboard. The error occurred at line 220 in `apps/dashboard/views.py`:

```python
student = HealthStudent.objects.filter(national_id=request.user.national_id).first()
```

The `national_id` field did not exist on the User model, but the dashboard views were trying to access it to link users to their professional records.

## Root Cause
The User model was missing the `national_id` field that is needed to link User accounts to professional records (HealthStudent, NursingProfessional, MedicalDoctor, CommunityHealthWorker).

## Solution Implemented

### 1. Added national_id field to User Model
**File**: `apps/accounts/models.py`
- Added `national_id = models.CharField(max_length=50, blank=True, null=True, unique=True)` to the User model

### 2. Created and Applied Database Migration
**File**: `apps/accounts/migrations/0005_user_national_id.py`
- Created migration with: `python manage.py makemigrations accounts`
- Applied migration with: `python manage.py migrate accounts`
- Status: Migration applied successfully ✓

### 3. Updated User Registration Form
**File**: `apps/accounts/forms.py`
- Added `national_id` field to PublicUserRegistrationForm
- Updated form's `fields` list to include 'national_id'
- Added widget configuration for the new field

### 4. Updated User Registration View
**File**: `apps/accounts/views.py`
- Modified `public_register` function to populate user's `national_id` from form data
- When creating a student, the user's `national_id` is now properly set and used for linking to HealthStudent

### 5. Enhanced Dashboard Views with Safety Checks
**File**: `apps/dashboard/views.py`
Updated the following views to check if national_id exists before querying:
- `nurse_dashboard()` (line 186-196)
- `chw_dashboard()` (line 199-208)
- `doctor_dashboard()` (line 211-221)
- `student_dashboard()` (line 224-234)

Each view now checks `if request.user.national_id:` before attempting to query the professional model.

### 6. Populated Existing User Data
- User "tolly" was updated with:
  - First Name: Darren
  - Last Name: Kila
  - National ID: 7654321
  - This links to the existing HealthStudent record

## Verification Results
✓ User model has national_id field
✓ Database migration applied successfully
✓ User "tolly" has national_id set to 7654321
✓ HealthStudent found with matching national_id
✓ Original failing line (line 220) now executes without AttributeError

## Files Modified
1. `apps/accounts/models.py` - Added national_id field
2. `apps/accounts/forms.py` - Added national_id form field
3. `apps/accounts/views.py` - Updated registration to set national_id
4. `apps/dashboard/views.py` - Added safety checks in dashboard views

## Files Created (for testing/verification)
1. `tools/maintenance/fix_user_national_id.py` - Script to fix missing national_id
2. `tools/maintenance/legacy/test_fix.py` - Test script to verify the fix
3. `tools/maintenance/legacy/verify_fix.py` - Verification script showing the fix works

## Testing
The exact failing code path has been tested and verified to work:
```python
tolly = User.objects.get(username='tolly')
student = HealthStudent.objects.filter(national_id=tolly.national_id).first()
# Result: Successfully retrieves HealthStudent "Darren Kila"
# No AttributeError thrown
```

## Impact
- Users can now access their respective dashboards (student, nurse, doctor, chw)
- The application no longer throws AttributeError when accessing dashboard views
- User-to-professional linkage is now properly established through national_id
- Future new users will automatically have national_id populated during registration

## Next Steps (Optional)
- Update existing admin/registrar users with appropriate national_id if they correspond to professionals
- Add validation to ensure national_id uniqueness is enforced at registration
- Consider adding national_id field to admin interface for manual updates

