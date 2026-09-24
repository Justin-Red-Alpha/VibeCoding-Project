# Spec Delta

## Purpose

Defines how the app behaves on a stateless host: data outlives any single
instance, outages are reported instead of shown as empty data, and scheduled work
is authenticated, bounded and picked up again if cut short.

## ADDED Requirements

### Requirement: Data survives restarts and scale-down
When the site is hosted, accounts, sessions, tracked products, listings, price
history and settings SHALL be kept in a database that outlives any single app
instance. After an instance stops and a new one starts, a signed-in user SHALL
still be signed in and SHALL see the same products and history. Run locally with
no hosting configuration, the site SHALL keep using its local database file
exactly as before.

#### Scenario: Instance replaced
- **WHEN** a user signs in and tracks a product, the instance scales down, and the user returns later
- **THEN** they are still signed in and the product and its price history are there

#### Scenario: Local run unchanged
- **WHEN** the app is started locally with no hosting settings
- **THEN** it reads and writes its local database file, with no network database involved

### Requirement: A database outage is never shown as empty data
If the database cannot be reached, pages that need it SHALL answer with a
"temporarily unavailable" error (HTTP 503) that says the data couldn't be loaded.
They SHALL NOT render as though the user has no products, no history or no
account. Nothing SHALL be written as a result of a failed read.

#### Scenario: Database unreachable
- **WHEN** a signed-in user opens their dashboard while the database is unreachable
- **THEN** they get a 503 page saying their data couldn't be loaded, not "Nothing tracked yet"

#### Scenario: Database back
- **WHEN** the database becomes reachable again
- **THEN** the same dashboard shows the user's products as before

### Requirement: Scheduled refreshes are authenticated, bounded and resumable
When scheduling is handed to the host, the host SHALL trigger a daily run through
an endpoint that requires a shared secret. The run SHALL:
- re-check listings stalest-first;
- stop starting new checks before the host's time limit, leaving the rest for the
  next run;
- then carry out archived-price lookups that were requested but never finished,
  unless an admin has paused them.

A request without the correct secret SHALL be refused and SHALL cause no work. If
no secret is configured, the endpoint SHALL be unavailable.

#### Scenario: Daily run
- **WHEN** the host calls the scheduled endpoint with the correct secret
- **THEN** the least recently checked listings get new price checks until the time budget is used, and each check is recorded

#### Scenario: Wrong or missing secret
- **WHEN** anyone calls the scheduled endpoint without the correct secret
- **THEN** it is refused, and no price check or archive request is made

#### Scenario: Interrupted background lookup is resumed
- **WHEN** an archive lookup started after tracking a listing was cut off before finishing
- **THEN** the next scheduled run looks that listing up, unless archive lookups are paused

#### Scenario: Too many listings for one run
- **WHEN** there are more listings than one run's time budget allows
- **THEN** the run stops cleanly before the limit, and the next run starts with the listings it didn't reach

### Requirement: Sign-in and form protection work behind the host's proxy
When the site is served over HTTPS through the host's proxy, the session cookie
SHALL be marked secure, and the cross-site form check SHALL compare against the
site's public host name. Forms submitted from the site itself SHALL be accepted.
Forms submitted from another website SHALL still be refused.

#### Scenario: Sign-in over HTTPS
- **WHEN** a user signs in on the hosted HTTPS site
- **THEN** the session cookie is marked Secure and HttpOnly

#### Scenario: Own form accepted
- **WHEN** a signed-in user submits the "Refresh my prices" form on the hosted site
- **THEN** it is accepted

#### Scenario: Cross-site form still refused
- **WHEN** another website makes the user's browser post to the hosted site
- **THEN** the post is refused with "submitted from another website"

### Requirement: Health check
The site SHALL answer a health-check request with whether the app is up and
whether its database answers. The answer SHALL NOT include credentials,
connection strings, hostnames or any user data.

#### Scenario: Healthy
- **WHEN** the health check is requested and the database answers
- **THEN** it returns HTTP 200, saying the app and database are OK

#### Scenario: Database down
- **WHEN** the health check is requested and the database does not answer
- **THEN** it returns HTTP 503, saying the database is unreachable, with no connection details
