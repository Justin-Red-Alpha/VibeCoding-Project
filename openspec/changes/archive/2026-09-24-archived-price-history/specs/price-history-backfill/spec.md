# Spec Delta

## Purpose

Gives a newly tracked listing a price history on day one by finding its own past
prices in a public web archive, while never letting archived data distort the
current price or invent a saving.

## ADDED Requirements

### Requirement: Tracking a listing looks up its archived prices in the background
When a listing is added to a tracked product, the system SHALL look up archived
copies of that listing's page and record the prices found as that listing's past
observations, each dated at the time it was archived. The lookup SHALL run in the
background, and adding the listing SHALL NOT wait for it.

#### Scenario: Listing with archived copies
- **WHEN** an Amazon listing is tracked and the archive holds copies of its page with readable prices
- **THEN** within a few minutes the listing shows those prices in its history, each at its archived date, and the product page reports how many archived prices were found and over what date range

#### Scenario: Adding a listing is not slowed down
- **WHEN** a listing is tracked
- **THEN** the product page loads as soon as the first live price check finishes, and the archive lookup continues afterwards

#### Scenario: Archive unreachable
- **WHEN** the archive cannot be reached or times out
- **THEN** the product page says the archive could not be reached (not that there is no history), nothing is added, and the lookup can be retried

#### Scenario: No archived copies
- **WHEN** the archive holds no copies of the listing's page
- **THEN** the product page says no archived copies were found

### Requirement: Matching is exact to the tracked listing
Archived prices SHALL come only from archived copies of the tracked listing's own
page. That means its URL without tracking parameters, or the shop's canonical URL
for the same item (for Amazon, the `/dp/<item id>` form on the same domain).
Archived prices SHALL NOT be taken from other listings, other shops or other
country domains.

#### Scenario: Canonical Amazon URL included
- **WHEN** a tracked Amazon listing's URL contains a product slug and the archive has copies under both the slug URL and the `/dp/<item id>` URL
- **THEN** copies under both are used, with at most one price per calendar month

#### Scenario: Other country domain not used
- **WHEN** an amazon.sg listing is tracked and the archive holds copies of the same item on amazon.com only
- **THEN** no amazon.com prices are added to the amazon.sg listing

### Requirement: Archived observations are marked and traceable
Every archived price SHALL be distinguishable from live checks wherever snapshots
are listed, and SHALL link to the archived copy it came from. Looking up the same
listing again SHALL NOT create duplicate observations.

#### Scenario: Snapshot list shows provenance
- **WHEN** the user views a product's raw snapshots
- **THEN** archived entries are marked as archived and link to the archived copy

#### Scenario: Re-running the lookup
- **WHEN** the user clicks "Look for archived prices" for a product that was already looked up
- **THEN** only captures not already recorded are added, and existing ones are not duplicated

### Requirement: The current price comes only from live checks
"Cheapest right now", the savings figure and each listing's current price SHALL be
based only on live checks. Archived prices SHALL be used for history and the
verdict only.

#### Scenario: Archived capture newer than the last live check
- **WHEN** a listing's newest archived capture is more recent than its last successful live check
- **THEN** the listing's current price is still its last live price

#### Scenario: Listing with only archived prices
- **WHEN** every live check of a listing has failed but archived prices exist
- **THEN** the listing shows no current price (with the live error), and its archived prices still appear in history

### Requirement: Archived history counts toward the verdict, safely
Archived prices SHALL be included in the price history the BUY/WAIT verdict is
computed from. An archived price SHALL be excluded, and counted as excluded in the
page's note, when its currency differs from the listing's currency, or when it is
below one third or above three times the median of the listing's prices.

#### Scenario: New product gets a trend-based verdict
- **WHEN** a product has 1 live check and 12 archived prices that vary
- **THEN** the verdict is computed from all 13 and is not "not enough data"

#### Scenario: Implausible archived price excluded
- **WHEN** one archived capture reads a price of a tenth of the listing's median (for example an accessory or used offer)
- **THEN** that price is not stored, and the note reports one price excluded as implausible

#### Scenario: Different currency excluded
- **WHEN** an archived copy of an SGD listing shows its price in USD
- **THEN** that price is not stored, and the note reports it as excluded for currency

### Requirement: Shops whose prices need a browser are skipped honestly
For shops whose real price only appears after the page's scripts run, archived
copies SHALL NOT be used. The system SHALL say that archived copies of that shop
don't carry the selling price, and SHALL NOT fall back to any other price on the
page.

#### Scenario: Lazada listing
- **WHEN** a Lazada listing is tracked
- **THEN** no archived prices are added, no crossed-out list price is ever recorded, and the page says archived copies of this shop don't include the selling price

### Requirement: The archive is used politely
The system SHALL:
- fetch at most 24 archived copies per listing (one per calendar month, newest
  first);
- send the archive no more than 15 requests per minute;
- run at most one lookup per product at a time.

At the first sign of rate limiting (HTTP 429 or a refused connection), it SHALL
stop that lookup immediately and SHALL NOT contact the archive again for a pause
period: at least 15 minutes after a 429, and at least an hour after a refused
connection. The archive blocks clients that keep going after a 429, and it
doubles the block on repeat.

#### Scenario: Long-archived listing
- **WHEN** a listing has 53 monthly captures
- **THEN** only the 24 most recent months are fetched

#### Scenario: Archive signals rate limiting mid-lookup
- **WHEN** the archive answers one archived copy with HTTP 429
- **THEN** no further copies are requested, the listing's note says the archive asked to slow down, and no other listing's lookup contacts the archive during the pause

#### Scenario: Lookup requested twice quickly
- **WHEN** the user clicks "Look for archived prices" twice while a lookup for that product is running
- **THEN** only one lookup runs
