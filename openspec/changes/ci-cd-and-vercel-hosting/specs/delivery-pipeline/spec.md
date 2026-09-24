# Spec Delta

## Purpose

Checks every change automatically on more than one operating system, builds and
tests the same container the host will run, and lets only a fully passing `main`
reach the live site.

## ADDED Requirements

### Requirement: Every change is checked automatically
Every push to `main` and every pull request SHALL trigger an automated check. It
SHALL byte-compile all application and test code, run every offline test suite on
both Linux and Windows, and verify that the docs' code references still resolve.
The check SHALL fail if any suite fails on either operating system, and SHALL show
which suite failed.

#### Scenario: A passing change
- **WHEN** a commit whose suites all pass is pushed to `main`
- **THEN** the check reports success on both Linux and Windows

#### Scenario: A test fails on one operating system
- **WHEN** a pull request breaks a test that fails only on Windows
- **THEN** the check reports failure, and its Windows run names the failing suite

#### Scenario: Docs point at code that no longer exists
- **WHEN** a change renames a function that a docs implementation map still names
- **THEN** the check fails and lists the dead reference

### Requirement: Tests also run on the production database engine
The check SHALL run the offline suites a second time against the same database
engine the hosted site uses, not only against the local file database. A test that
passes on the local database but fails on the production engine SHALL fail the
check. This test run SHALL never use the hosted site's own database, since the
tests erase the data they run against.

#### Scenario: Engine-specific failure
- **WHEN** a change works on the local database but breaks on the production engine (for example, results come back in a different order)
- **THEN** the check fails, and its production-engine run names the failing suite

#### Scenario: Pointed at a remote database
- **WHEN** the test database setting points at any host other than the local machine
- **THEN** the tests refuse to start, and nothing is erased

### Requirement: The hosted container is built and smoke-tested before release
The check SHALL build the same container image the host deploys, start it, and
confirm that it serves the sign-in page and can render a page in its headless
browser. A container that fails to build, fails to start, or cannot start its
browser SHALL fail the check.

#### Scenario: Image works
- **WHEN** the container is built from a passing commit and started
- **THEN** the sign-in page loads, a test page renders inside it, and the check passes

#### Scenario: Browser missing from the image
- **WHEN** a change removes the browser's system libraries from the image
- **THEN** the in-container render fails and the check reports failure

### Requirement: Only a fully passing main reaches production
A deploy to production SHALL happen only for a push to `main` after every check
above has passed. A failing check SHALL block that deploy. Pull requests SHALL
never deploy. Until the repository has deploy credentials, the deploy step SHALL
be skipped with a visible notice, never reported as a failure or a success.

#### Scenario: Green main deploys
- **WHEN** a push to `main` passes every check and deploy credentials are configured
- **THEN** that commit is deployed to production

#### Scenario: Red main does not deploy
- **WHEN** a push to `main` fails a test
- **THEN** nothing is deployed and production keeps serving the previous version

#### Scenario: No credentials yet
- **WHEN** a push to `main` passes but the repository has no deploy credentials
- **THEN** the deploy step is skipped with a notice saying credentials are missing
