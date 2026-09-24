# site-administration Specification

## Purpose
Gives admins one page to manage accounts, change site-wide settings without
editing code or restarting, and run maintenance actions.

## Requirements

### Requirement: The admin page is for admins only
The system SHALL provide an admin page reachable from the top bar for admins.
Users SHALL be refused, and anonymous visitors SHALL be sent to sign in.

#### Scenario: Admin opens it
- **WHEN** an admin opens `/admin`
- **THEN** it shows the users, site settings and maintenance sections

#### Scenario: User tries it
- **WHEN** a signed-in user opens `/admin` or posts to any admin action
- **THEN** they get "forbidden" and nothing changes

### Requirement: Admins manage user accounts
An admin SHALL see every account with its role, status, sign-up date and number
of tracked products. They SHALL be able to promote a user to admin, demote an
admin to user, disable or enable an account, and delete an account. Deleting an
account SHALL also delete that account's tracked products. The system SHALL
always keep at least one enabled admin.

#### Scenario: Promote and demote
- **WHEN** an admin promotes user B, and later demotes B
- **THEN** B can open the admin page after the promotion and not after the demotion

#### Scenario: Last admin protected
- **WHEN** the only enabled admin tries to demote, disable or delete themselves
- **THEN** it is refused with a message that the site needs at least one admin

#### Scenario: Delete removes the user's products
- **WHEN** an admin deletes user B, who tracks 2 products
- **THEN** B cannot sign in and B's 2 products are gone

### Requirement: Admins change site settings without a restart
An admin SHALL be able to set:
- the default display currency for anonymous visitors and new users;
- the shops that deal search covers;
- the automatic refresh interval (1–168 hours);
- the discovery limits: listings kept per shop (1–20) and missing prices looked
  up per search (0–20).

Changes SHALL take effect on the next search or refresh without restarting the
server. Invalid values SHALL be refused with a message, leaving the old value in
place.

#### Scenario: Refresh interval changed
- **WHEN** an admin sets the refresh interval from 6 to 12 hours
- **THEN** the next automatic refresh is scheduled 12 hours out, without a restart

#### Scenario: Shops searched changed
- **WHEN** an admin removes eBay from the shops searched
- **THEN** the next deal search shows no eBay section

#### Scenario: Invalid value
- **WHEN** an admin enters a refresh interval of 0 hours
- **THEN** it is refused with the allowed range and the interval stays as it was

### Requirement: Admins run maintenance actions
An admin SHALL be able to:
- refresh every user's tracked prices now;
- refresh the FX rates now;
- pause or resume the automatic archived-price lookups.

While lookups are paused, tracking a listing SHALL NOT contact the archive, and
product pages SHALL say lookups are paused.

#### Scenario: Pause archive lookups
- **WHEN** an admin pauses archive lookups and a user then tracks an Amazon listing
- **THEN** no archive request is made, and the product page says archive lookups are paused by an admin

#### Scenario: Refresh everything
- **WHEN** an admin runs "refresh all prices"
- **THEN** every user's listings get a new price check, not only the admin's
