-- ==============================================================================
-- STRICT EMAIL UNIQUENESS ENFORCER (The "Highlander" Rule)
-- ==============================================================================
-- Purpose: Absolutely prevent duplicate accounts with the same email, 
-- regardless of provider (Google vs Email vs GitHub).
-- Even if Supabase allows unlinked accounts, this trigger will BLOCK the 2nd insert.

-- 1. Create the Check Function
CREATE OR REPLACE FUNCTION public.check_strict_email_uniqueness()
RETURNS TRIGGER AS $$
BEGIN
    -- Check uniqueness case-insensitive
    IF EXISTS (
        SELECT 1 
        FROM auth.users 
        WHERE lower(email) = lower(NEW.email)
        AND id != NEW.id -- Safety for Updates (though this is an Insert trigger)
    ) THEN
        RAISE EXCEPTION 'Security Policy Violation: Account with email % already exists. Please login with the original provider.', NEW.email;
    END IF;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- 2. Attach Trigger to auth.users (BEFORE INSERT)
-- We target 'auth.users' specifically as it's the root identity table.

DROP TRIGGER IF EXISTS check_email_uniqueness_trigger ON auth.users;

CREATE TRIGGER check_email_uniqueness_trigger
BEFORE INSERT ON auth.users
FOR EACH ROW
EXECUTE FUNCTION public.check_strict_email_uniqueness();

-- 3. Confirmation
COMMENT ON FUNCTION public.check_strict_email_uniqueness IS 'Enforces one-account-per-email policy strictly.';
