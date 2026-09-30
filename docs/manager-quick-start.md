# Seat Belt Sourcing Committee Cockpit — Quick Start for Managers

Address: **http://<server>:8031/** (replace with the address you were given)

## 1. First login

**Sourcing admin (Xiangwei Chen)** — the only account with a password. Click **Log in** (top right), enter your email, then the password field appears: enter the initial password you received. Afterwards click your name → **Change password**.

**Managers (Carrie Wang, William Shorter, Eric Wu, Fei Chen) and everyone else** — no password at all:

1. Click **Log in → Register**. Enter your name and company email (@zf.com or @zf-lifetec.com). Done — you are logged in as *User*.
2. Next time, click **Log in**, type your email, press Enter. That is the whole login.
3. Managers: tell the Sourcing admin once. He opens **Accounts** and changes your role to **Manager**; it takes effect immediately.

Password rules (admins only): at least 6 characters, not your email address, at least 4 different characters.

## 2. What each role can do

| | User | Manager | Sourcing admin |
| --- | --- | --- | --- |
| View cases, download files, export Excel | ✓ | ✓ | ✓ |
| Submit a case registration | ✓ | ✓ | ✓ |
| Report progress on a follow-up (with attachment) | ✓ | ✓ | ✓ |
| Confirm / return registrations (Approval page) | | ✓ | ✓ |
| Edit cases, record decisions and follow-ups | | ✓ | ✓ |
| Send reminders, approve / reject follow-up feedback | | ✓ | ✓ |
| Upload / remove case files | | ✓ | ✓ |
| Exchange rates, registration deadline, reminder settings | | | ✓ |
| Accounts page: roles, disable, reset password | | | ✓ |

Viewing does not require login. Submitting does.

## 3. Weekly routine for a Manager

**Before the meeting (Approval page)**
- Each new registration shows the part numbers, bundle spend, commercial data and uploaded files.
- **Confirm** registers it as a case for the requested Wednesday. **Return** sends it back to the submitter with your reason (required).
- A yellow "Late registration" banner means the buyer registered after the Monday 23:59 deadline and gave a reason; confirming approves the exception.
- **Dashboard → Agenda** exports the week's agenda as Excel (same layout as the committee template).

**After the meeting (case page → Edit)**
- Set **Sourcing Decision** (Approved / Approved with conditions / Rejected). Any decision other than Pending needs the **Sourcing Presentation Link**.
- Add **follow-up tasks**: task, owner, due date, category, and the owner's email (required for open tasks — that is where reminders go).
- **Save Changes**. **Dashboard → Minutes** exports the minutes plus an Actions sheet.

**Follow-ups page**
- Open and overdue tasks across all cases. Filter by category or owner.
- Anyone can post progress on a task (text + attachment, e.g. an Outlook .msg). You get "n feedback to approve": **Approve** closes the task, **Reject** needs a remark and keeps it open.
- Closing the last open task closes the case and asks for the **Final PPT / Supporting Document Link**.
- **Send reminder** sends a manual reminder to the owner. Until IT connects the mail relay, reminders are logged as "skipped" and nothing is sent — chase by email meanwhile.

## 4. Messages you may see

| Message | Meaning / what to do |
| --- | --- |
| Use your company email address (@zf.com or @zf-lifetec.com) | Only company addresses can register |
| An account with this email already exists | Just log in with the email |
| No account with this email yet — register first | Switch to the Register tab, enter name + email |
| This is a Sourcing admin account — enter the password | Admin accounts are the only ones with a password |
| Wrong email or password | Admins only; after 5 failures in 15 minutes the login is locked for 5 minutes |
| This account is disabled | Ask the Sourcing admin to re-enable it |
| Please fill in Project, Sourcing Type and Recommended Supplier for every part number row | Each part number row needs its own project, type and supplier |
| Please enter the bundle Peak Year Spend and Lifetime Spend | One total for the whole registration, both must be above 0 |
| Lifetime Spend is above 3 Mio EUR — a BPG must be available | Answer BPG = Yes, otherwise the case cannot be registered |
| A Level 2 case requires an available FRA | Answer FRA = Yes for Level 2 |
| Registration for the … meeting closed on … | Deadline passed: pick the next Wednesday, or tick "Request an exception" and give a reason |
| A Sourcing Decision cannot be saved without the Sourcing Presentation Link | Paste the SharePoint / OneDrive link of the presentation first |
| Follow-up task n: enter a valid "Send reminder to" email | Every open task needs an owner email |
| Keep at least one active Sourcing admin | Promote someone else to admin before demoting or disabling the last one |
| This needs the Manager role | Your account is still *User* — ask the Sourcing admin |

## 5. Good to know

- Login stays valid for 7 days; logging out ends it. Only Sourcing admins have a password; promoting someone to admin issues a temporary password shown once on the Accounts page.
- Uploaded files are renamed automatically to `YYYY.MM.DD Project Part-description PN, Supplier.ext`; the original name is still shown ("uploaded as …").
- Amounts are stored in EUR. USD / CNY entries are converted with the OP rate maintained by the Sourcing admin on the Dashboard; the entered amount stays visible.
- Week numbers are ISO calendar weeks (KW).
- **Import weekly committee Excel** (Home page, Sourcing admin only): drop the week's Agenda or Meeting Minutes files, or pick a stored historical file from the "Stored weekly files" dropdown ("Add all not yet imported" loads the whole 2025–2026 history in one go), tick the ones to import, press Import. The meeting date comes from the file name (KW39 23.09.2026); a file without a date asks for it. Importing the same week again replaces what was imported before. Imported cases show "Imported from …" and the original decision wording on the case page.
