# Spec Delta

## Purpose

Lets a user set the price they are willing to pay, in a currency they choose, and
have the BUY/WAIT verdict honour it without ever misreading its currency.

## ADDED Requirements

### Requirement: Target price carries a user-chosen currency
When a user sets a target price while tracking a product, the system SHALL let them
choose its currency. It SHALL keep that currency with the target, and SHALL show the
target on the product page in the currency it was entered in.

#### Scenario: User picks a currency for the target
- **WHEN** a user tracks a product with target `800` and currency `MYR`
- **THEN** the product page shows the target as `MYR 800.00`

#### Scenario: User leaves the currency on "Shop's currency"
- **WHEN** a user tracks a product with target `300` and no currency chosen, and its first priced listing is in `SGD`
- **THEN** the target is treated and shown as `SGD 300.00`

#### Scenario: Unrecognised currency is rejected
- **WHEN** a target is submitted with a currency code the app does not offer (e.g. `XYZ`)
- **THEN** the request is rejected with a client error and no product is created

### Requirement: Target currency defaults to what the user is looking at
The target currency selector SHALL default to the currently selected display
currency. When prices are shown as quoted, it SHALL default to "Shop's currency".

#### Scenario: Display currency selected
- **WHEN** the display currency is `MYR` and the user opens a form with a target field
- **THEN** the target currency selector is preset to `MYR`

#### Scenario: Prices shown as quoted
- **WHEN** no display currency is selected
- **THEN** the target currency selector is preset to "Shop's currency"

### Requirement: Target is compared in the price history's currency
Before a target is applied to the verdict, the system SHALL restate it in the
currency the price history is expressed in. That is the display currency when one
is selected, otherwise the product's primary currency. The stored target amount and
currency SHALL NOT change.

#### Scenario: Target in another currency is converted before comparison
- **WHEN** the target is `MYR 800`, the best current price is `SGD 300`, and `MYR 800` is worth about `SGD 250`
- **THEN** the verdict is not `BUY NOW` on account of the target

#### Scenario: Converted target is met
- **WHEN** the target is `MYR 1000` (about `SGD 313`) and the best current price is `SGD 300`
- **THEN** the verdict is `BUY NOW` and names the target as the reason

#### Scenario: Changing the display currency does not change a target-driven verdict
- **WHEN** every listing is in one currency and the user switches the display currency between "as quoted", `MYR` and `USD`
- **THEN** the verdict label is the same in all three views

#### Scenario: No exchange rate for the target's currency
- **WHEN** the target's currency differs from the history's currency and no rate is available
- **THEN** the target is shown, a notice says it is not used in the verdict, and the verdict is computed without it

#### Scenario: Stored target is never rewritten
- **WHEN** the user changes the display currency after setting a target
- **THEN** the stored target amount and currency are unchanged

### Requirement: Products tracked before target currencies existed keep their meaning
A product whose target has no stored currency SHALL keep treating its target as
being in the product's primary currency.

#### Scenario: Existing product after upgrade
- **WHEN** a database created before this change is opened and a product has target `300` with no target currency
- **THEN** the product and its target survive the upgrade, and the target is applied as `300` in the product's primary currency
