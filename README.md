# Task Tracker

A professional task management application built for the **Graduate Support Engineer Trainee Assessment**.

This application allows users to securely sign in, create tasks, view their task list, and seamlessly transition tasks across three states: **Planned**, **In Progress**, and **Complete**. It features a modern, dual-view interface (List and Kanban Board) and strict multi-tenant data isolation to ensure user privacy.

---

## Submission Links

- **Source Code Repository:** `[Add your GitHub repository URL here]`
- **Live Application URL:** `[Add your deployed live URL here, e.g., https://task-tracker-demo.onrender.com]`
- **Technology Stack:** Python 3.10+ (Flask), SQLite, Vanilla HTML5, CSS3, JavaScript (ES6+), RESTful JSON API.

---

## Table of Contents

- [Task Tracker](#task-tracker)
  - [Submission Links](#submission-links)
  - [Table of Contents](#table-of-contents)
  - [1. How to Access and Use the Application](#1-how-to-access-and-use-the-application)
  - [2. Login Instructions](#2-login-instructions)
  - [3. Important Assumptions Made](#3-important-assumptions-made)
  - [4. Known Limitations](#4-known-limitations)
  - [5. Important Notes and Warnings](#5-important-notes-and-warnings)
  - [6. Setup and Execution Instructions](#6-setup-and-execution-instructions)
    - [Prerequisites](#prerequisites)
    - [Step 1: Clone the Repository](#step-1-clone-the-repository)

---

## 1. How to Access and Use the Application

1. **Accessing the App:** Open the live deployment URL or navigate locally to `http://localhost:8080`.
2. **Authentication Options:**
   - **Email & Password:** Create an account or sign in securely.
   - **Quick Evaluator Sign-In:** One-click demo sign-in for instant local evaluation without setup.
3. **Adding a Task:**
   - Enter a **Title** (required).
   - Optionally enter a **Description**.
   - Select a **Priority** (*Low*, *Medium*, or *High*; defaults to *Medium*).
   - Choose a **Due Date** manually.
   - Click **+ Add Task**. Newly created tasks automatically start in the **Planned** state.
4. **Switching Views (List vs. Board):**
   - Click **List View** in the sidebar to view tasks linearly with full metadata.
   - Click **Board View** to view tasks in a 3-column Kanban layout (*Planned*, *In Progress*, *Complete*).
5. **Updating Task Status:**
   - **In List View:** Click any status button (*Planned*, *In Progress*, *Complete*) on the task card.
   - **In Board View:** Either click the status buttons or **drag and drop** a task card directly into any column.
6. **Deleting Tasks:**
   - Click **Delete** on a task to safely remove it from your view.

---

## 2. Login Instructions

- **Quick Evaluator Sign-In (Local Demo Mode):**
  - To enable reviewers to test all features immediately without requiring Google Cloud credentials, two demo accounts are built-in:
    - **Alex Johnson** (`alex.johnson@example.com`)
    - **Taylor Morgan** (`taylor.morgan@example.com`)
  - Both demo accounts use the exact same SQLite database and authorization pipeline as live logins.
- **Testing Multi-Tenant User Isolation:**
  - Sign in as **Alex Johnson** and create tasks.
  - Sign out, and sign in as **Taylor Morgan**. Taylor’s task list will be completely independent. Taylor cannot view, edit, or delete Alex’s tasks.

---

## 3. Important Assumptions Made

| Gap / Ambiguity | Assumption & Decision | Technical Rationale |
| --- | --- | --- |
| **Whose tasks does a user see?** | Tasks are strictly private to each authenticated user account. | Ensures multi-tenant privacy and data isolation. |
| **Required task fields?** | Title is required; description and due date are optional. | Keeps task entry rapid while enforcing database sanity. |
| **Initial task state?** | All newly created tasks start in **Planned** state. | Natural lifecycle for new work items before execution begins. |
| **Allowed state transitions?** | Non-restrictive transitions (any state can move to any other state). | Support engineers frequently need to re-open completed tickets. |

---

## 4. Known Limitations

1. **Storage Persistence:** The application uses SQLite for zero-configuration portability. On ephemeral hosting platforms (like Render's free tier), the SQLite file resets when the instance spins down.
2. **Google Authentication:** Real Google OAuth requires setting up credentials in the Google Cloud Console. The app uses a zero-config Demo login fallback for evaluators.

---

## 5. Important Notes and Warnings

- **Privacy & Security:** Tasks are scoped strictly to your account. However, do not store sensitive credentials or banking information in task descriptions.
- **Session Expiry:** Closing the browser retains your session until cookie expiry. When working on shared computers, always click **Sign out**.

---

## 6. Setup and Execution Instructions

### Prerequisites

- Python 3.10 or newer
- Git

### Step 1: Clone the Repository

```bash
git clone <your-repository-url>
cd task-tracker
