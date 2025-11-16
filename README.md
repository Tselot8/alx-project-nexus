# Project Nexus

## Project Objective
**Project Nexus** is a backend system designed to manage polls, options, and votes, providing a robust, secure, and real-time API for interactive voting applications. The system is built with **Python** and **Django**, implementing best practices in authentication, caching, and data integrity.

The project’s main goal is to provide a **fully functional backend** that can support frontend clients (web or mobile) for creating polls, casting votes, and retrieving real-time poll results.

---

## Key Features
- **Poll Management**
  - Create, update, and delete polls with associated options.
  - Support for optional poll expiration dates and public/private polls.
  
- **Option Management**
  - Add, update, and delete options within polls.
  - Ensure votes are tracked accurately for each option.

- **Voting System**
  - Users can cast a vote for a poll option.
  - Users can change their vote; the system automatically updates vote counts.
  - Supports real-time vote counts and prevents voting on expired polls.

- **Authentication & Permissions**
  - All API endpoints require authenticated access.
  - Only authorized users can create or modify polls and options.

- **Caching**
  - Poll results are cached to reduce database load.
  - Cache is automatically invalidated when votes are cast or changed.

- **Audit Logging**
  - Tracks important actions, including poll creation, option creation, and votes cast.
  - Maintains a historical record of user activity for accountability.

---

## Project Structure

### Models
- **Poll**
  - `question`, `description`, `created_by`, `category`, `expires_at`, `is_public`
- **Category**
  - `id`, `name`, `description`
- **Option**
  - `poll`, `option_text`, `votes_count`
- **Vote**
  - `poll`, `option`, `user`
- **AuditLog**
  - `user`, `action`, `target_type`, `target_id`, `timestamp`

### API Endpoints
- `GET /polls/` – List all polls
- `POST /polls/` – Create a new poll
- `GET /polls/{id}/` – Retrieve poll details
- `PATCH /polls/{id}/` – Update a poll
- `DELETE /polls/{id}/` – Delete a poll
- `POST /polls/{poll_id}/options/` – Add a new option
- `PATCH /options/{id}/` – Update an option
- `DELETE /options/{id}/` – Delete an option
- `POST /polls/{poll_id}/vote/` – Cast or change a vote
- `GET /polls/{poll_id}/results/` – Retrieve poll results (cached for performance)

---

## Implementation Highlights
- **Atomic Transactions:** Ensures vote integrity when multiple users vote simultaneously.
- **Cache Invalidation:** Poll results cache is invalidated automatically after votes change.
- **Vote Handling Logic:** Handles first-time votes, changing votes, and prevents double-counting.
- **Audit Logs:** Every important user action is logged to the `AuditLog` model for tracking.

---

## Testing
- Fully tested with **Pytest**.
- Tests cover:
  - Poll creation, update, and deletion
  - Option management
  - Voting workflow, including changing votes
  - Poll results cache and invalidation
  - Audit logging for actions

All tests are passing, ensuring reliability and stability.

---

## Collaboration
- Designed to integrate with frontend clients (web/mobile apps).
- Supports secure and real-time interaction with multiple users.
- Backend API structure is ready for collaborative projects.

---

## Getting Started
1. Clone the repository:  
   ```
   git clone https://github.com/Tselot8/alx-project-nexus.git
   ```
2. Install dependencies and set up the virtual environment.

3. Apply migrations:
    ```
    python manage.py migrate
    ```

4. Create a superuser:
    ```
    python manage.py createsuperuser
    ```
5. Run the development server:
    ```
    python manage.py runserver
    ```
6. Interact with the API endpoints using an authenticated user.

This README provides a complete overview of Project Nexus, focusing on its functionality, architecture, and implementation. It is a ready-to-use backend system for building interactive polling applications. However, Project Nexus is an evolving backend system. Its features, performance, and security will be **constantly refined and improved** to ensure it remains robust, scalable, and aligned with best practices in backend development.