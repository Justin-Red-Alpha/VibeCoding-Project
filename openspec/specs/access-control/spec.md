# access-control Specification

## Purpose
Defines what anonymous visitors, signed-in users and admins can each see and do,
so one user's tracked products and preferences stay theirs and form submissions
and redirects can't be abused.

## Requirements

### Requirement: Deal search is public; everything else needs an account
Anonymous visitors SHALL be able to search shops for deals and see the results.
The dashboard, product pages, tracking, adding or removing shops, refreshing, and
changing preferences SHALL require sign-in. An anonymous visitor SHALL be sent to
sign in and then returned to the page they asked for.

#### Scenario: Anonymous search
- **WHEN** an anonymous visitor searches for "Sony WH-1000XM5"
- **THEN** results stream in per shop as for a signed-in user, and the "Track these" section says to sign in to track

#### Scenario: Anonymous visitor opens the dashboard
- **WHEN** an anonymous visitor opens `/`
- **THEN** they are sent to sign in, and after signing in they land on `/`

#### Scenario: Anonymous tracking attempt
- **WHEN** an anonymous visitor submits the track form
- **THEN** nothing is tracked and they are sent to sign in

### Requirement: Each user's products are private to them
A user SHALL see only the products they track, on the dashboard and anywhere else.
Opening, changing, refreshing or deleting another user's product SHALL behave as
if it doesn't exist. An admin SHALL be able to open and manage any product.
Products that existed before accounts SHALL belong to the first admin.

#### Scenario: Another user's product
- **WHEN** user B opens the product page of user A's product
- **THEN** B gets "not found", and nothing about the product is shown

#### Scenario: Another user's delete
- **WHEN** user B submits a delete for user A's product
- **THEN** B gets "not found" and the product still exists

#### Scenario: Admin sees any product
- **WHEN** an admin opens user A's product page
- **THEN** the page shows it

#### Scenario: Existing products after upgrade
- **WHEN** the first admin registers on a site that already had tracked products
- **THEN** those products appear on that admin's dashboard

### Requirement: Display currency is a personal preference
Each signed-in user SHALL choose their own "Show prices in" currency, and it SHALL
NOT affect other users. Anonymous visitors SHALL see prices in the site's default
display currency, which an admin sets.

#### Scenario: Two users, two currencies
- **WHEN** user A chooses MYR and user B chooses USD
- **THEN** A sees MYR and B sees USD on the same product data

#### Scenario: Anonymous default
- **WHEN** the admin sets the site default to SGD and an anonymous visitor searches
- **THEN** results are shown converted to SGD

### Requirement: Only same-site form submissions and local redirects
The system SHALL reject a state-changing request that comes from another site. It
SHALL only redirect to a page on this site after sign-in or after changing a
preference.

#### Scenario: Cross-site form post
- **WHEN** a page on another site makes the browser post to this site's delete URL
- **THEN** the request is refused and nothing changes

#### Scenario: Redirect to another site
- **WHEN** sign-in or a preference change is given `next=https://evil.example/`
- **THEN** the user is taken to a page on this site instead
