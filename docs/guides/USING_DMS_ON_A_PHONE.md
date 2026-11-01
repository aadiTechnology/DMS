# Using the DMS on a phone

The DMS works in the phone's browser at the same address as on a computer, and can be put on the home screen like an app. There is nothing to download from an app store.

## Put it on the home screen

| Phone | Steps |
|---|---|
| Android (Chrome) | Open your DMS address, open the menu (three dots), choose **Install app** (or **Add to Home screen**) |
| iPhone (Safari) | Open your DMS address, tap **Share**, then **Add to Home Screen** |

The address must start with `https://`. After installing, the icon opens the DMS full screen, starting on the dashboard. Updates arrive by themselves when the application is updated on the server. Signing in works as on a computer, including the two-step code.

## What is laid out for a phone (phase 1)

| Place | On a phone |
|---|---|
| Bottom bar | Dashboard, Documents, Upload, Approvals (with a red count of reviews waiting), and **More** |
| More | Everything else you may use, and Sign out |
| Dashboard | Figures two to a row, then charts and lists in one column |
| Documents | Compact cards; search always visible; filters open with the **Filters** button |
| A document | Details, then versions as cards with Preview, Download and Restore |
| Upload | **Take a photo** opens the camera; **Choose a file** opens the phone's files |
| Approvals | Cards with a **Review** button; the review opens full screen with Approve and Reject |

All other pages (people, categories, organization and so on) open on a phone and fit the width, but are designed for a computer; wide tables scroll sideways.

## Not included in this version

Offline use, push notifications, and a store app. These need a separate decision.

## For the person running the server

Nothing extra is needed beyond the normal deployment. The install files (`manifest.webmanifest` and the icons) are part of the web image. The browser's install option appears only on `https://` addresses.
