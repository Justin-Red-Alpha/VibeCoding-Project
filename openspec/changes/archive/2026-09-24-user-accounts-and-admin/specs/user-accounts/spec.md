# Spec Delta

## Purpose

Lets people create an account and sign in, gives the first account the admin role
and everyone after it the user role, and keeps accounts safe from password
guessing.

## ADDED Requirements

### Requirement: Registration with a username and password
A visitor SHALL be able to register with a username (3–32 characters: letters,
digits, `.`, `_`, `-`) and a password (8–256 characters). Usernames SHALL be
unique regardless of letter case. The first account ever registered SHALL get the
admin role, and every later account SHALL get the user role. Registering SHALL
sign the new user in.

#### Scenario: First account becomes admin
- **WHEN** the first visitor registers on a site with no accounts
- **THEN** the account has the admin role and the visitor is signed in

#### Scenario: Later accounts are users
- **WHEN** a second visitor registers
- **THEN** the account has the user role

#### Scenario: Username already taken
- **WHEN** a visitor registers as `Alice` and an account `alice` exists
- **THEN** registration is refused with "that username is taken" and no account is created

#### Scenario: Password too short
- **WHEN** a visitor registers with a 7-character password
- **THEN** registration is refused with the length rule and no account is created

### Requirement: Signing in and out
A registered, enabled user SHALL be able to sign in with their username and
password, and SHALL stay signed in for up to 14 days or until they sign out.
Signing out SHALL end that session immediately. A failed sign-in SHALL give the
same message whether the username or the password was wrong.

#### Scenario: Correct credentials
- **WHEN** a user signs in with the right username and password
- **THEN** they are signed in and taken to the page they were trying to reach, or the dashboard

#### Scenario: Wrong password or unknown user
- **WHEN** someone signs in with a wrong password, or with a username that doesn't exist
- **THEN** both cases show the same message, "Wrong username or password"

#### Scenario: Signing out
- **WHEN** a signed-in user signs out and then revisits their dashboard
- **THEN** they are asked to sign in again

### Requirement: Repeated failed sign-ins lock the username temporarily
After 5 failed sign-ins for the same username within 15 minutes, the system SHALL
refuse sign-in for that username for 15 minutes, even with the correct password,
and SHALL say so.

#### Scenario: Guessing is stopped
- **WHEN** 5 wrong passwords are tried for `alice` within 15 minutes
- **THEN** a 6th attempt with the right password is refused with a "too many attempts, try again later" message

#### Scenario: Lock expires
- **WHEN** 15 minutes pass after the lock started
- **THEN** `alice` can sign in with the right password

### Requirement: Disabled accounts cannot be used
A disabled account SHALL NOT be able to sign in, and its existing sessions SHALL
end at once.

#### Scenario: Disabled while signed in
- **WHEN** an admin disables a user who is currently signed in
- **THEN** that user's next page load asks them to sign in, and signing in is refused

#### Scenario: Re-enabled
- **WHEN** an admin re-enables the account
- **THEN** the user can sign in again
