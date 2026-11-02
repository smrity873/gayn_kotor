# Gayn Kotor — Future Work & Architectural Improvements

This document outlines key technical enhancements, scalability initiatives, and feature extensions planned for future iterations of **Gayn Kotor**.

---

## 1. Real Commercial Payment Gateways
While the platform incorporates an extensible gateway adapter pattern (`payments/gateways/`) with an operational Sandbox gateway, production commercial deployment in Bangladesh requires direct merchant integrations:

- **bKash Tokenized Checkout API**: Implement dynamic grant token lifecycle (`POST /tokenized/checkout/token/grant`), payment creation (`POST /tokenized/checkout/create`), and execution (`POST /tokenized/checkout/execute`) with webhook callback IP whitelisting.
- **Nagad Direct Merchant API**: Implement cryptographic public/private key signature verification (RSA-SHA256) and callback payment verification (`GET /verify/payment/{paymentRefId}`).
- **SSLCommerz Hosted Session Gateway**: Add multi-channel card and mobile banking support with IPN (Instant Payment Notification) hash validation.

---

## 2. Cloud Video Storage & Adaptive Transcoding Pipeline
Currently, uploaded MP4 lessons are validated via `mutagen` and streamed using chunked HTTP Range requests directly from private disk storage. For large-scale multi-gigabyte video catalogs:

- **Adaptive Bitrate Streaming (HLS / DASH)**: Transcode uploaded MP4 videos into multi-resolution HLS streams (360p, 720p, 1080p) using FFmpeg workers.
- **Cloudflare Stream / AWS MediaConvert Integration**: Offload video transcoding and delivery to managed edge streaming infrastructures with dynamic time-limited signed cookies and tokens.
- **Object Storage Backend**: Transition `PRIVATE_MEDIA_ROOT` from local filesystem to private S3-compatible buckets (Cloudflare R2, AWS S3, Google Cloud Storage) using private pre-signed URLs or S3 Range streaming proxies.

---

## 3. Asynchronous Worker Queue (Celery + Redis)
Presently, periodic tasks (review escalation, swap dispute resolution, ledger integrity checks) run via management commands (`send_reminders`, `resolve_swaps`, `check_ledger`), and PDF thumbnail generation runs synchronously on upload.

- **Distributed Task Architecture**: Integrate **Celery** with a **Redis** or RabbitMQ broker.
- **Offload Heavy Compute**: Move PyMuPDF PDF thumbnail rasterization and Mutagen video metadata extraction to background worker pools.
- **Celery Beat Schedulers**: Replace external system crons with integrated Celery Beat periodic schedules for automated review deadline evaluations and swap dispute expirations.

---

## 4. Real-Time WebSockets & Push Notifications
- **Django Channels (ASGI)**: Upgrade from HTTP polling/refreshing to asynchronous WebSockets for real-time notification delivery, active swap session status updates, and peer-to-peer text chat during scheduled tutoring sessions.
- **WebPush & FCM**: Integrate Firebase Cloud Messaging (FCM) and the W3C WebPush API to deliver native browser push notifications when a student receives review feedback, swap session requests, or sales earnings.

---

## 5. Automated AI Content Moderation & OCR
Currently, note moderation relies on manual Class Representative / Class Teacher reviews and community report thresholds:

- **PDF Optical Character Recognition (OCR)**: Integrate Tesseract or AWS Textract to index handwritten lecture notes into searchable vector text representations.
- **Copyright & Plagiarism Screening**: Use LLM embeddings (e.g. Gemini API / Sentence-Transformers) to compare student note submissions against indexed textbook chapters and academic repositories, automatically flagging potential copyright infringements before publication.
- **Automated Obscenity & Toxicity Filters**: Screen course titles, note descriptions, and skill postings for inappropriate content using automated classification models.

---

## 6. Multi-Party Mutual Skill Swap Pools (Trading Rings)
The current skill swap engine pairs 1-on-1 teachers and learners directly (A teaches B). In many scenarios, student A wants to learn Skill X from Student B, but Student B wants Skill Y, which is offered by Student C:

- **Cycle-Finding Algorithm (Graph-Based Matching)**: Implement an automated matching algorithm (e.g., Edmonds' Blossom algorithm or DFS cycle detection) to identify 3-way or N-way barter loops ($A \rightarrow B \rightarrow C \rightarrow A$).
- **Multi-Party Escrow Ledger**: Hold deposits across the ring and resolve transfers atomically when all ring sessions conclude successfully.

---

## 7. Native Mobile Applications (Flutter / React Native)
While the web frontend is fully responsive across 360px+ viewports, a native mobile application offers enhanced student engagement:

- **Cross-Platform App**: Build a mobile client using Flutter or React Native communicating with Django REST Framework / Ninja APIs.
- **Offline PDF Viewer & Video Caching**: Support encrypted offline storage of unlocked lecture notes and purchased video lessons.
- **Calendar Synchronization**: Sync scheduled skill swap tutoring sessions directly into Google Calendar or Apple Calendar using device calendar APIs.

