# currency-comparison Specification

## Purpose
Guarantees that a price is only ranked, charted or counted in history against
prices it can honestly be compared with, so a currency mix-up never fabricates a
"cheapest" listing or a saving.

## Requirements

### Requirement: Prices with an unknown currency are shown but never compared
A listing whose price has no recognised currency SHALL be shown with a
"currency unknown" note. It SHALL NOT be ranked, declared cheapest, counted in the
price history, or drawn on the chart, whether or not a display currency is selected.

#### Scenario: Cheaper unknown-currency listing does not win
- **WHEN** one listing is `SGD 100` and another is `50` with no recognised currency
- **THEN** the `SGD 100` listing is cheapest and the other is marked "currency unknown — not compared"

#### Scenario: Unknown currency with a display currency selected
- **WHEN** a display currency is selected and a listing has no recognised currency
- **THEN** that listing is still excluded from ranking and history

### Requirement: Without a display currency, only the product's currency is ranked
With prices shown as quoted, listings in a currency other than the product's primary
currency SHALL be shown and marked "different currency — not compared". They SHALL
be excluded from ranking, history and the chart.

#### Scenario: Foreign listing excluded
- **WHEN** the product's primary currency is `SGD` and one listing is `MYR 200`
- **THEN** the `MYR` listing is not ranked and does not appear in the best-price history

#### Scenario: No primary currency and a single shared currency
- **WHEN** the product has no pinned currency and every priced listing is in `SGD`
- **THEN** the listings are compared in `SGD`

#### Scenario: No primary currency and mixed currencies
- **WHEN** the product has no pinned currency and priced listings are in several currencies
- **THEN** no listing is declared cheapest

### Requirement: With a display currency, listings compete after conversion
With a display currency selected, every listing with an available rate SHALL be
converted and ranked together. A listing whose currency has no rate SHALL be shown
and marked "no rate — not compared", and never declared cheapest.

#### Scenario: Converted listing wins
- **WHEN** the display currency is `MYR`, one listing is `SGD 100` (≈ `MYR 320`) and another is `MYR 200`
- **THEN** the `MYR 200` listing is cheapest

#### Scenario: No rate for a listing's currency
- **WHEN** a listing's currency has no available rate
- **THEN** it is shown, marked as not compared, and never cheapest

#### Scenario: Nothing could be converted
- **WHEN** a display currency is selected but no listing's currency has a rate
- **THEN** the page does not claim that prices were converted

### Requirement: Chart lines never mix currencies
Each shop's line on the price chart SHALL be expressed in one currency: the display
currency if one is selected, otherwise the product's primary currency. Points that
cannot be expressed in that currency SHALL be left out rather than plotted at face
value.

#### Scenario: Foreign snapshot left off an as-quoted chart
- **WHEN** no display currency is selected and a shop's history contains an `MYR` snapshot on an `SGD` product
- **THEN** that snapshot is not plotted

#### Scenario: Snapshot converted for a display-currency chart
- **WHEN** the display currency is `SGD` and a snapshot is `MYR 409` with a rate available
- **THEN** it is plotted as its `SGD` equivalent

#### Scenario: Unconvertible snapshot left off
- **WHEN** a display currency is selected and a snapshot's currency has no rate or is unknown
- **THEN** that snapshot is not plotted
