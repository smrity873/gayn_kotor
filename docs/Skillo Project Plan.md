Skillo: Project Plan 

# Skillo: Project Plan 

_A campus knowledge-and-skill exchange platform, built with Django, PostgreSQL and Tailwind CSS_ 

## 1. Overview 

Skillo is a campus knowledge-and-skill exchange platform for university students and lecturers. Users share PDF notes, sell video courses, and swap skills with each other. Everything runs on an internal currency called credits. Each credit is shown visually as a nut kept in a squirrel's tree hollow. 

Tagline: "Share what you know. Learn what you want." 

The platform has three pillars: 

- Note sharing, paid for with credits 

- Video courses, paid for with money 

- Skill swap, paid for with credits 

## 2. Campus Structure 

Universities have many departments, so the structure is: 

- Department (for example CSE, EEE, BBA) 

- Batch (a department plus a year or session, for example CSE 2022) 

- Each batch has one class teacher (a lecturer), one or more CRs (students), and its students 

Only the admin creates departments and batches and assigns a class teacher to each batch. The class teacher appoints the CRs for that batch. Users cannot give themselves these roles. 

## 3. User Roles 

### **Admin (the developer)** 

- Creates departments and batches and assigns class teachers. 

- Handles emergencies only, such as fixing mistakes or blocking a harmful account. 

Page 1 of 7 

Skillo: Project Plan 

Is not part of any daily workflow, because the admin is the developer and will not moderate content. 

### **Lecturer** 

- Must provide an ID and verify an email at sign-up. 

- Notes uploaded by a lecturer are published directly, with no review, because lecturers are trusted not to upload junk. 

- A lecturer who is a class teacher also appoints CRs and reviews notes for their batch. Lecturers use credits like everyone else, for example to learn a skill outside their course. 

### **Student** 

- Must provide a student ID and verify an email at sign-up. 

- Chooses their department and batch when signing up. 

- A student who is a CR reviews notes uploaded by their batch. 

Each role has its own dashboard. 

## 4. Credit System 

- New account: +30 credits. 

- Uploading a note: +10 credits, granted after the note is approved (see section 5). Downloading a note: -5 credits. 

- Someone rates your file: +5 credits to the file owner. 

- You rate someone else's file: +1 credit to the rater. 

### Rules that apply equally to students and lecturers: 

- A user can rate a file only after downloading it, only once per file, and never their own file. 

- There is a daily cap on credits earned from ratings. 

- A file can earn its owner rating credits from a limited number of raters. 

- When credits run out, users can buy more with money (sandbox payment first, a real gateway later). The conversion rate proposed is 1 taka = 1 credit. Credits can never be withdrawn as money. 

Anti-abuse design: 

Page 2 of 7 

Skillo: Project Plan 

- Every credit change is stored in a ledger table: who, how many, why, when, and which note or session it relates to. Balances are never edited directly. 

- The admin can inspect the ledger and reverse suspicious entries. 

- The upload bonus is released only after approval, or after the note has been downloaded a few times, so that uploading junk files for credits is not worthwhile. Sign-up bonuses are given only after email verification. 

## 5. Note Sharing (PDF only) 

Only PDF files are accepted. Each note has a title, course code, department, semester, description, and optionally a "department only" or "batch only" restriction. 

Review workflow for student uploads, with no admin involvement: 

1. A student uploads a note. 

2. The CRs of the uploader's batch get a notification. If a CR is the uploader, the note goes to another CR or directly to the class teacher. 

3. If no CR acts within 3 days, the batch's class teacher is notified, with a reminder each day. 

4. If nobody acts within 7 days in total, the note is published automatically with an "unverified" badge. 

5. If a note is rejected, a reason is required, and the uploader can appeal to the class teacher. 

6. Any user can report a note. Several reports send it back to the class teacher's queue. 

7. The class teacher can remove a note at any time. 

Edge cases: 

If a batch has no CR, notes go straight to the class teacher. 

- If a batch has several CRs, whoever decides first is final. 

- The 3-day and 7-day limits live in settings so they can be changed easily. 

- Time-based escalation is calculated from the upload time when pages load, so no scheduler is needed. A small management command can send reminders and emails, and can be run manually for demos. 

Page 3 of 7 

Skillo: Project Plan 

## 6. Video Courses (paid with money) 

Anyone with an approved account can sell a video course, either academic (inside the university syllabus) or non-academic (development, graphics, UI/UX, English speaking, and similar). 

Pricing rules: 

- Price must be based on total video duration, with a minimum and maximum allowed price per hour. 

- Academic courses have a low per-hour range, so they stay student-budget friendly. Non-academic skills have a higher per-hour range. 

The seller cannot set a price outside the allowed range for the category and duration. 

Payment runs in sandbox mode first. The seller earns the price minus a platform commission, into a wallet, and can request a withdrawal. Withdrawals are an admin or manual process in this version. 

Video storage starts on the server with a size limit and permission-checked streaming, so only buyers can watch. Cloud storage can come later. 

This pillar is the e-commerce-like part of the project, so it is built last and can be removed without affecting the rest. The teacher should be asked early whether this is acceptable. 

## 7. Skill Swap (paid with credits) 

Users post what they can teach and what they want to learn. For example: "I know Math but not Physics." Two people can match and teach each other. 

Flow: 

1. A user posts a skill offer or a learning request. 

2. Another user requests a session. 

3. The teacher accepts and proposes a time. 

4. The teacher creates their own meeting link (Google Meet, Zoom, or similar) and pastes it in. No external API is used. 

5. Only the two participants can see the link. 

6. After the session, both can rate it. 

Page 4 of 7 

Skillo: Project Plan 

Credit rule: each session involves 10 credits. The proposed design is a deposit, where 10 credits are held from each side when the session is booked and returned when the session is completed. A person who does not show up loses their deposit. This needs final confirmation. 

Link safety: only links from approved domains (meet.google.com, zoom.us, teams.microsoft.com) are accepted, and the link can be edited later if it was wrong. 

## 8. The Nut Hollow (credit visualization) 

Each credit is one nut. A dedicated page shows a tree with a hollow and a squirrel, plus a counter showing how many nuts the user has. 

Behavior: 

When credits are earned, the squirrel carries nuts into the hollow. 

- When credits are spent, the squirrel takes nuts out of the hollow. 

- When credits are bought, the squirrel happily carries the new nuts in. 

- Only a limited number of nuts are drawn (for example up to 20 to 30). The exact balance is shown as a number. 

The page also lists recent credit activity from the ledger. 

This is built with raw JavaScript and CSS animation. 

## 9. Notifications 

A bell icon in the navbar shows an unread count. The browser checks for new notifications every 30 seconds with simple polling. Email is optional, and in development emails print to the terminal. 

Notifications are sent for: 

A note awaiting review (to CRs) 

- A reminder on day 2 (to CRs) 

- An escalated note (to the class teacher) 

- A note approved or rejected, with the reason (to the uploader) 

- A rating received (to the file owner) 

- Credits added or deducted (to the user) 

- Skill session requested, accepted, time confirmed, or link added (to both people) 

Page 5 of 7 

Skillo: Project Plan 

## 10. Account Verification 

Because there is no admin reviewing accounts, verification is automatic or done by trusted batch members. 

- Email verification with a link or OTP is required before the 30 sign-up credits are granted. 

- If the university has its own email domain, only that domain is accepted. If students use ordinary email, then ID checking by the CR or class teacher becomes the main safeguard, and they can disable an account if something is wrong. 

- Lecturers verify by email and ID. After that, their notes are published without review. 

## 11. Pages and Dashboards 

- Home page: a polished landing page with the squirrel theme, how it works, popular notes and courses, and sign-up buttons. 

- Student dashboard: credits, downloads, courses bought, sessions, notifications. CR dashboard: notes waiting for review from the batch. 

- Class teacher dashboard: escalated notes, batch members, CR management. 

- Lecturer dashboard: own notes, courses, sessions, earnings. 

- Admin area: departments, batches, class teachers, ledger inspection, emergency actions. 

## 12. Technology 

- Frontend: HTML, Tailwind CSS, raw JavaScript. React is not needed, because the animations and polling are easy in plain JavaScript. 

- Backend: Django 

- Database: PostgreSQL 

- Credits: a ledger table, never direct balance edits 

- Payments: sandbox gateway behind a gateway interface, so a real one can be added later 

- Video: server storage with size limits at first 

Page 6 of 7 

Skillo: Project Plan 

## 13. Django Apps 

- accounts: user, role, ID, email verification 

- campus: department, batch, class teacher, CR assignments 

- credits: ledger, balance, rules, nut hollow page 

- notes: note upload, review workflow, ratings, reports 

- courses: video courses, pricing rules, purchases 

- swaps: skill offers, requests, sessions, meeting links, ratings 

- payments: wallet, sandbox gateway, withdrawals 

- notifications: bell and email 

The first version of Skillo already has working code for payment services, wallet, form styling, and base templates, which can be reused for the payments app and the shared layout. 

## 14. Timeline (about 4 weeks) 

- Week 1: Project setup, user model with roles, department and batch structure, login and email verification, home page, credit ledger. 

- Week 2: Note upload, CR and class teacher review workflow, ratings, notifications. 

- Week 3: Nut hollow page, skill swap, role dashboards. 

- Week 4: Video courses (riskiest part, so last), testing, polish, documentation, proposal. 

## 15. Open Questions 

1. Does the university have its own email domain for verification? 

2. Is there exactly one class teacher per batch? 

3. Should skill swap use a refundable deposit of 10 credits from each person, or something else? 

4. Is the video course pillar acceptable to the teacher, given that it involves money? 

5. Should credits be bought at 1 taka per credit? 

Page 7 of 7 

