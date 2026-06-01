# DB API Marketplace - Overview

Source: https://developers.deutschebahn.com/db-api-marketplace/apis/start
Retrieved: 2026-05-05

---

## What the Marketplace Is

The DB API Marketplace (`developers.deutschebahn.com/db-api-marketplace`) is Deutsche Bahn's developer portal for accessing transportation and infrastructure APIs. The tagline is "Mit den APIs der Deutschen Bahn neue Lösungen für die Mobilität von morgen entwickeln!" (Create new mobility solutions using Deutsche Bahn APIs).

The portal requires JavaScript to be enabled. Most technical API documentation (OpenAPI specs, try-it-out interfaces) is only accessible after logging in and subscribing to a product.

---

## Registration and Onboarding (4-step process)

1. **Register** - Create a DB Kundenkonto (DB customer account) via the marketplace login page. Registration involves email verification and an OAuth redirect back to the marketplace.
2. **Create Application** - An "application" functions as a technical OAuth client. Upon creation, the portal generates a **Client ID** and a **Client Secret (API Key)**. The secret is shown exactly once and must be saved immediately.
3. **Subscribe** - Browse the catalog (`/product`), select a product, choose a subscription plan, and associate it with the created application.
4. **Call the API** - Use the "Versuch es!" (Try it out!) tab in the portal, or call externally using `DB-Client-Id` and `DB-Api-Key` headers.

---

## Authentication

### Method: Header-based API Key

All DB API Marketplace APIs use **header-based authentication** with two credentials obtained from the portal:

| Header | Value |
|--------|-------|
| `DB-Client-Id` | Your application's Client ID |
| `DB-Api-Key` | Your application's Client Secret (API Key) |

Both headers must be present on every API request.

Example (from OpenStation documentation):
```
curl 'https://apis.deutschebahn.com/db-api-marketplace/apis/open-station/v1/netex' \
  -H 'DB-Client-ID: <YOUR_CLIENT_ID>' \
  -H 'DB-Api-Key: <YOUR_CLIENT_SECRET>'
```

### Portal Login: OAuth 2.0 Authorization Code Flow

The marketplace portal itself uses OAuth 2.0 (`response_type=code`) delegating to Deutsche Bahn's identity provider. The login page shows "Weiter mit DB Kundenkonto" (Continue with DB customer account) - there are no username/password fields on the marketplace login page itself.

### x509 Client Certificates

**No x509 client certificate requirement has been documented** for any of the publicly available APIs on the DB API Marketplace. The portal login page has no certificate upload field. The application creation flow uses OAuth/API key credentials only.

Some restricted APIs (e.g., RIS::Transports, ISR Data Service) require authorization from DB and have contractual access controls, but these controls operate through account-level approval - not x509 certificates presented at the TLS layer.

The `username` field visible in some portal screenshots refers to the DB Kundenkonto login, not a certificate Common Name.

---

## Base URL Pattern

All APIs share this base URL pattern:

```
https://apis.deutschebahn.com/db-api-marketplace/apis/{api-name}/{version}/
```

There is **no separate sandbox hostname** documented publicly. The marketplace offers a "Test Access" plan for some APIs (limited call volume) and the built-in "Versuch es!" try-it-out interface, both of which use the same production hostname.

---

## Available APIs (from catalog, as of 2026-05-05)

### Publicly Available (Free or Subscription)

| API | Version | Category | Description |
|-----|---------|----------|-------------|
| **Timetables** | 1.0.274 | Open Data | Arrivals and departures for DB Station&Service AG stations. Plan + real-time changes. |
| **OpenStation** | 1.0.2814 | Infrastructure | Infrastructure data for passenger stations operated by DB InfraGO AG. CC0 license. |
| **RIS::Stations** | 1.29.3248 | Reisendeninformation / RIS-API | Stations, platforms, tracks, sectors, transfer times, station-area services. |
| **RIS::Transports** | 4.4.1135 | Reisendeninformation / RIS-API | Vehicle sequence (Wagenreihung), platform positioning, combined journeys, car equipment features. |
| **ISR Data Service** | 5.0.448 | Infrastructure | Infrastructure registry data: platforms (Bahnsteige), operating points (Betriebsstellen), track sections (Streckenabschnitte), tunnels. |

### RIS::Transports - Access Restriction
Access is **restricted to rail operators (Eisenbahnverkehrsunternehmen) and selected authorized third parties** with DB approval. Subscription plans range from free test access (max 2 months, 1,000 tx/day, 10/min) to paid packages (XS–XL, €4,200–€84,000/year, 5,000–500,000 calls/day).

### ISR Data Service - Access Restriction
Access requires authorization under ERegG § 1 Abs. 12. Must specify consumer organization name during product order in IPID. €1,846/year, up to 1,000 queries/day, 10/s. Daily maintenance window starting 20:00.

---

## Subscription Plans (representative examples)

### Timetables - Free Plan
- Cost: free
- Rate limit: 60 calls/minute
- SLA: 24/7 operation, no service guarantee

### RIS::Stations - Tiered Plans

| Plan | Annual Cost | Monthly Requests | Req/sec |
|------|-------------|-----------------|---------|
| Test Access | Free | 10,000 | 10 |
| XS | €4,200 | 150,000 | 100 |
| S | €12,000 | 750,000 | 100 |
| M | €27,000 | 3,000,000 | 100 |
| L | €54,000 | 7,500,000 | 100 |
| XL | €84,000 | 15,000,000 | 100 |

---

## Catalog and Portal URLs

| Page | URL |
|------|-----|
| Portal home | https://developers.deutschebahn.com/db-api-marketplace |
| Getting Started | https://developers.deutschebahn.com/db-api-marketplace/apis/start |
| Product catalog | https://developers.deutschebahn.com/db-api-marketplace/apis/product |
| Timetables product | https://developers.deutschebahn.com/db-api-marketplace/apis/product/timetables |
| Login | https://developers.deutschebahn.com/db-api-marketplace/apis/user/login |
| New application | https://developers.deutschebahn.com/db-api-marketplace/apis/application/new |
| Contact | api-marketplace@deutschebahn.com |

---

## Limitations of This Documentation

The DB API Marketplace portal is a single-page application that loads most content via JavaScript after authentication. Technical documentation (full OpenAPI specs, endpoint details beyond the product listing page, try-it-out parameter details) is only accessible after:
1. Creating a DB Kundenkonto
2. Creating an application
3. Subscribing to the relevant product

The OpenAPI specification URL pattern `https://developers.deutschebahn.com/db-api-marketplace/apis/feature/openapi/{api}/{version}` returns 404 without authentication.
