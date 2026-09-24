# Spec Delta

## Purpose

Lets a user search every configured shop for a product and see each shop's matches
and prices as fast as those shops allow, with blocked shops and failures reported
plainly instead of looking like "still loading" or "no results".

## ADDED Requirements

### Requirement: Shops are searched concurrently and reported as each finishes
The system SHALL search all configured shops at the same time. It SHALL deliver
each shop's results as soon as that shop finishes, independent of the other shops.
A slow, blocked or failing shop SHALL NOT delay any other shop's results.

#### Scenario: A fast shop is not held back by a slow one
- **WHEN** one shop answers in 2 s and another takes 8 s
- **THEN** the first shop's results are shown at about 2 s, before the second finishes

#### Scenario: One shop fails
- **WHEN** one shop's search raises an error
- **THEN** that shop shows its error and every other shop still shows its results

#### Scenario: Whole search is faster than the sequential baseline
- **WHEN** "Sony WH-1000XM5" is searched across the default shops on the development machine
- **THEN** the search, including missing-price lookups, finishes in under 15 seconds (it took 30.0 s before this change)

### Requirement: A blocked shop is reported as blocked, promptly
When a shop answers a search with an error page or a bot check instead of results,
the system SHALL report that shop as having refused the search within a few seconds.
It SHALL NOT wait out the full result timeout, and SHALL NOT describe the outcome as
"no results found".

#### Scenario: Shop returns a small error page
- **WHEN** a shop's search returns a page of a few kilobytes with no result cards (as eBay does)
- **THEN** that shop is shown as having refused the search, within about 3 seconds of the request

#### Scenario: A large page that has not rendered its results yet
- **WHEN** a shop returns a full-size page whose result cards render a moment later
- **THEN** the system keeps waiting for the results and does not report the shop as blocked

### Requirement: Faster rendering does not change what is read
Pages SHALL be rendered without downloading images, fonts or media. The titles,
links and prices read from them SHALL be the same as with a full download.

#### Scenario: Search result cards still carry titles and prices
- **WHEN** Amazon and Lazada are searched
- **THEN** result cards are found with titles and prices, as before

#### Scenario: Lazada product page still reads the sale price
- **WHEN** a Lazada product page is rendered to read its price
- **THEN** the price read is the current selling price shown on the page, not the crossed-out list price

### Requirement: Missing prices are looked up concurrently, within a limit
Listings whose search card shows no price SHALL be looked up at most 3 at a time.
Each price SHALL be delivered as soon as it is found. One failed lookup SHALL NOT
affect the others.

#### Scenario: Several prices missing
- **WHEN** 4 listings need their product page fetched and each fetch takes about the same time
- **THEN** all 4 arrive in roughly the time of two fetches, not four

#### Scenario: One lookup fails
- **WHEN** one of the price lookups fails
- **THEN** that listing shows the failure reason and the other listings still receive their prices

### Requirement: Browser rendering works however the server is started
Shop search and product-page rendering SHALL work whether the server is started
normally or with automatic reload. If the browser cannot be started, the system
SHALL report that as an error to the user and SHALL NOT leave shops shown as
still searching.

#### Scenario: Server started with automatic reload on Windows
- **WHEN** the server runs with `--reload` on Windows and a search is made
- **THEN** shops are searched and results are shown

#### Scenario: Browser cannot start
- **WHEN** the browser fails to launch
- **THEN** the page shows a message explaining the search could not run, and no shop is left showing "searching…"

### Requirement: Only shops that are actually searched show as searching
A configured shop that the app cannot search on its own site SHALL be shown as not
searched from the start. It SHALL NOT be shown as "searching…", and it SHALL NOT be
counted in the "Searched N of M shops" progress.

#### Scenario: Shop without site-search support
- **WHEN** Shopee (which has no site-search support) is among the configured shops
- **THEN** its section says it can't be searched directly, and progress counts only the searchable shops

#### Scenario: Every searchable shop has reported
- **WHEN** the last searchable shop has reported
- **THEN** no shop section is still showing "searching…"
