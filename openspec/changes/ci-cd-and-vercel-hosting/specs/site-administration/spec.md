# Spec Delta

## MODIFIED Requirements

### Requirement: Admins change site settings without a restart
An admin SHALL be able to set:
- the default display currency for anonymous visitors and new users;
- the shops that deal search covers;
- the automatic refresh interval (1–168 hours), unless the host schedules
  refreshes itself;
- the discovery limits: listings kept per shop (1–20) and missing prices looked
  up per search (0–20).

Changes SHALL take effect on the next search or refresh without restarting the
server. Invalid values SHALL be refused with a message, leaving the old value in
place.

When the host schedules refreshes itself, the admin page SHALL show the host's
schedule (for example "once a day, set by the host") instead of an editable
interval. It SHALL NOT accept or store an interval it cannot honour. "Refresh all
prices now" SHALL keep working.

#### Scenario: Refresh interval changed
- **WHEN** an admin sets the refresh interval from 6 to 12 hours on a site that schedules its own refreshes
- **THEN** the next automatic refresh is scheduled 12 hours out, without a restart

#### Scenario: Shops searched changed
- **WHEN** an admin removes eBay from the shops searched
- **THEN** the next deal search shows no eBay section

#### Scenario: Invalid value
- **WHEN** an admin enters a refresh interval of 0 hours
- **THEN** it is refused with the allowed range and the interval stays as it was

#### Scenario: Host-scheduled refreshes
- **WHEN** an admin opens the settings on a site whose refreshes are scheduled by the host
- **THEN** the refresh interval is shown as the host's daily schedule, with no editable field

#### Scenario: Interval posted anyway on a host-scheduled site
- **WHEN** a request to save settings includes a refresh interval on a site whose refreshes are scheduled by the host
- **THEN** the interval is ignored and nothing about the schedule is stored, while the other settings save normally
